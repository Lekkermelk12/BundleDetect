"""Full scan pipeline — orchestrates holder resolution, clustering, and risk analysis."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests


@dataclass
class WalletInfo:
    address: str
    pct_held: float = 0.0
    pct_bought: float = 0.0
    volume_sol: float = 0.0
    first_trade_ts: Optional[int] = None  # first trade on THIS token
    wallet_age_ts: Optional[int] = None   # first ever transaction
    category: str = "Regular"             # New / Regular / Sniper
    still_holding: bool = True


@dataclass
class RiskCluster:
    cluster_id: int
    wallets: List[WalletInfo]
    pct_bought: float = 0.0
    pct_held: float = 0.0
    volume_sol: float = 0.0
    risk_score: float = 0.0
    risk_label: str = "LOW"
    flags: List[str] = field(default_factory=list)
    first_trade_span_minutes: Optional[float] = None
    first_trade_age_days: Optional[float] = None
    common_funding: bool = False
    pct_still_holding: float = 0.0


@dataclass
class ScanResult:
    token_symbol: str
    contract_address: str
    overall_risk_score: float
    risk_clusters: List[RiskCluster]
    total_wallets_analyzed: int
    total_supply_bought: float
    total_supply_held: float
    high_risk_count: int


# ---------------------------------------------------------------------------
# Helius helpers
# ---------------------------------------------------------------------------

_history_cache: Dict[str, List[Dict[str, Any]]] = {}


def _helius_parse_history(wallet: str, limit: int = 100) -> List[Dict[str, Any]]:
    if wallet in _history_cache:
        return _history_cache[wallet]

    history_url = os.getenv("HELIUS_PARSE_HISTORY", "")
    if not history_url:
        return []
    url = history_url.replace("{address}", wallet)
    try:
        resp = requests.get(url, params={"limit": limit}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result = data if isinstance(data, list) else []
    except Exception:
        result = []

    _history_cache[wallet] = result
    return result


def _get_wallet_first_tx_timestamp(wallet: str) -> Optional[int]:
    """Earliest transaction timestamp for a wallet (wallet age)."""
    txs = _helius_parse_history(wallet, limit=100)
    earliest: Optional[int] = None
    for tx in txs:
        ts = tx.get("timestamp")
        if isinstance(ts, (int, float)) and ts > 0:
            ts = int(ts)
            if ts > 10_000_000_000:
                ts = ts // 1000
            earliest = ts if earliest is None else min(earliest, ts)
    return earliest


def _get_first_trade_on_token(wallet: str, mint: str) -> Tuple[Optional[int], float]:
    """Find the earliest trade timestamp for a specific token, plus total SOL volume."""
    txs = _helius_parse_history(wallet, limit=100)
    first_ts: Optional[int] = None
    total_sol = 0.0

    for tx in txs:
        # Check if this tx involves our token
        description = str(tx.get("description", "")).lower()
        token_transfers = tx.get("tokenTransfers", []) or []
        involves_token = any(
            t.get("mint") == mint for t in token_transfers if isinstance(t, dict)
        )

        if not involves_token and mint.lower() not in description:
            continue

        ts = tx.get("timestamp")
        if isinstance(ts, (int, float)) and ts > 0:
            ts = int(ts)
            if ts > 10_000_000_000:
                ts = ts // 1000
            first_ts = ts if first_ts is None else min(first_ts, ts)

        # Sum SOL volume from native transfers
        for nt in tx.get("nativeTransfers", []) or []:
            if isinstance(nt, dict):
                amount = nt.get("amount", 0)
                if isinstance(amount, (int, float)):
                    total_sol += abs(amount) / 1e9  # lamports to SOL

    return first_ts, total_sol


def _estimate_pct_bought(wallet: str, mint: str, total_supply: float) -> float:
    """Estimate the total % of supply a wallet bought by looking at net token inflows per tx.

    We compute the net inflow per transaction (inflows - outflows) and only sum
    positive nets, to avoid double-counting intermediate routing within a single swap.
    """
    if total_supply <= 0:
        return 0.0
    txs = _helius_parse_history(wallet, limit=100)
    total_bought = 0.0

    for tx in txs:
        net_in = 0.0
        for tt in tx.get("tokenTransfers", []) or []:
            if not isinstance(tt, dict) or tt.get("mint") != mint:
                continue
            amount = float(tt.get("tokenAmount", 0) or 0)
            to_acc = tt.get("toUserAccount", "")
            from_acc = tt.get("fromUserAccount", "")
            if to_acc == wallet:
                net_in += amount
            elif from_acc == wallet:
                net_in -= amount
        if net_in > 0:
            total_bought += net_in

    if total_bought <= 0:
        return 0.0
    return (total_bought / total_supply) * 100.0


# ---------------------------------------------------------------------------
# Categorization & risk
# ---------------------------------------------------------------------------

NEW_WALLET_THRESHOLD_DAYS = 7


def _categorize_wallet(wallet_info: WalletInfo, token_launch_ts: Optional[int]) -> str:
    now = int(time.time())
    age_seconds = (now - wallet_info.wallet_age_ts) if wallet_info.wallet_age_ts else None

    if age_seconds is not None and age_seconds < NEW_WALLET_THRESHOLD_DAYS * 86400:
        return "New"

    # Sniper: bought within first 60 seconds of token launch
    if (
        token_launch_ts is not None
        and wallet_info.first_trade_ts is not None
        and abs(wallet_info.first_trade_ts - token_launch_ts) < 60
    ):
        return "Sniper"

    return "Regular"


def _compute_cluster_risk(cluster: RiskCluster) -> float:
    """Compute a 0-100 risk score for a cluster."""
    score = 0.0

    # Base score from cluster size
    n = len(cluster.wallets)
    if n >= 5:
        score += 30
    elif n >= 3:
        score += 20
    else:
        score += 10

    # New wallet ratio
    new_count = sum(1 for w in cluster.wallets if w.category == "New")
    new_ratio = new_count / max(n, 1)
    score += new_ratio * 25

    # Still holding ratio
    if cluster.pct_still_holding >= 0.9:
        score += 15
    elif cluster.pct_still_holding >= 0.5:
        score += 8

    # Time-linked buying (first trades within short window)
    if cluster.first_trade_span_minutes is not None:
        if cluster.first_trade_span_minutes < 1:
            score += 20
        elif cluster.first_trade_span_minutes < 5:
            score += 15
        elif cluster.first_trade_span_minutes < 30:
            score += 10

    # Common funding
    if cluster.common_funding:
        score += 10

    # Supply concentration
    if cluster.pct_held > 5:
        score += 10
    elif cluster.pct_held > 2:
        score += 5

    return min(score, 100.0)


def _risk_label(score: float) -> str:
    if score >= 70:
        return "VERY HIGH"
    elif score >= 45:
        return "HIGH"
    elif score >= 25:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Funding source analysis
# ---------------------------------------------------------------------------

def _check_common_funding(wallets: List[str]) -> bool:
    """Check if wallets share common SOL funding sources."""
    if len(wallets) < 2:
        return False

    funding_sources: Dict[str, set] = {}
    for wallet in wallets[:10]:  # limit API calls
        txs = _helius_parse_history(wallet, limit=20)
        sources: set = set()
        for tx in txs:
            for nt in tx.get("nativeTransfers", []) or []:
                if isinstance(nt, dict):
                    to_acc = nt.get("toUserAccount", "")
                    from_acc = nt.get("fromUserAccount", "")
                    if to_acc == wallet and from_acc:
                        sources.add(from_acc)
        funding_sources[wallet] = sources

    # Check for overlap
    wallet_list = list(funding_sources.keys())
    for i in range(len(wallet_list)):
        for j in range(i + 1, len(wallet_list)):
            overlap = funding_sources[wallet_list[i]] & funding_sources[wallet_list[j]]
            # Exclude known programs/system accounts
            overlap = {a for a in overlap if len(a) > 20}
            if overlap:
                return True
    return False


# ---------------------------------------------------------------------------
# Batch pre-fetch from mint transaction history
# ---------------------------------------------------------------------------

def _prefetch_mint_tx_data(
    mint: str, helius_client: Any
) -> Dict[str, Dict[str, Any]]:
    """Batch-fetch transaction data for a mint and extract per-wallet metrics.

    Returns {wallet: {first_trade_ts, volume_sol, pct_bought}} built from
    the mint's transaction signatures, avoiding per-wallet API calls.
    """
    total_supply = helius_client.get_token_supply(mint)
    try:
        sigs = helius_client.get_signatures_for_address(mint, limit=200)
        parsed_txs = helius_client.get_parsed_transactions_batch(sigs) if sigs else []
    except Exception:
        return {}

    wallet_data: Dict[str, Dict[str, Any]] = {}
    # {wallet: {first_trade_ts, volume_sol, net_tokens_in}}

    for tx in parsed_txs:
        ts = tx.get("timestamp")
        if isinstance(ts, (int, float)) and ts > 0:
            ts = int(ts)
            if ts > 10_000_000_000:
                ts = ts // 1000
        else:
            ts = None

        # Track per-wallet net token inflow and SOL volume for this tx
        tx_wallet_tokens: Dict[str, float] = {}
        tx_wallet_sol: Dict[str, float] = {}

        for tt in tx.get("tokenTransfers", []) or []:
            if not isinstance(tt, dict) or tt.get("mint") != mint:
                continue
            amount = float(tt.get("tokenAmount", 0) or 0)
            to_acc = tt.get("toUserAccount", "")
            from_acc = tt.get("fromUserAccount", "")
            if to_acc:
                tx_wallet_tokens[to_acc] = tx_wallet_tokens.get(to_acc, 0) + amount
            if from_acc:
                tx_wallet_tokens[from_acc] = tx_wallet_tokens.get(from_acc, 0) - amount

        for nt in tx.get("nativeTransfers", []) or []:
            if not isinstance(nt, dict):
                continue
            amount = nt.get("amount", 0)
            if isinstance(amount, (int, float)):
                sol = abs(amount) / 1e9
                from_acc = nt.get("fromUserAccount", "")
                to_acc = nt.get("toUserAccount", "")
                # Attribute volume to wallets involved in token transfers
                if from_acc in tx_wallet_tokens:
                    tx_wallet_sol[from_acc] = tx_wallet_sol.get(from_acc, 0) + sol
                if to_acc in tx_wallet_tokens:
                    tx_wallet_sol[to_acc] = tx_wallet_sol.get(to_acc, 0) + sol

        for wallet, net_tokens in tx_wallet_tokens.items():
            if wallet not in wallet_data:
                wallet_data[wallet] = {
                    "first_trade_ts": ts,
                    "volume_sol": 0.0,
                    "net_tokens_in": 0.0,
                }
            wd = wallet_data[wallet]
            if ts is not None:
                if wd["first_trade_ts"] is None or ts < wd["first_trade_ts"]:
                    wd["first_trade_ts"] = ts
            wd["volume_sol"] += tx_wallet_sol.get(wallet, 0.0)
            if net_tokens > 0:
                wd["net_tokens_in"] += net_tokens

    # Convert net_tokens_in to pct_bought
    for wd in wallet_data.values():
        if total_supply > 0 and wd["net_tokens_in"] > 0:
            wd["pct_bought"] = (wd["net_tokens_in"] / total_supply) * 100.0
        else:
            wd["pct_bought"] = 0.0

    return wallet_data


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def run_scan(
    contract_address: str,
    helius_client: Any,
    *,
    token_symbol: str = "",
) -> ScanResult:
    """Run the full scan pipeline for a token contract."""
    _history_cache.clear()

    # 1. Get holder data
    holder_pct = helius_client.get_holder_pct_by_wallet(contract_address)
    total_supply = helius_client.get_token_supply(contract_address)

    if not holder_pct:
        return ScanResult(
            token_symbol=token_symbol or contract_address[:8],
            contract_address=contract_address,
            overall_risk_score=0.0,
            risk_clusters=[],
            total_wallets_analyzed=0,
            total_supply_bought=0.0,
            total_supply_held=0.0,
            high_risk_count=0,
        )

    # 2. Pre-fetch batch transaction data for all wallets from mint history
    #    This avoids per-wallet API calls for first trade / volume / bought.
    mint_tx_data = _prefetch_mint_tx_data(contract_address, helius_client)

    # 3. Build WalletInfo for each holder
    wallet_infos: Dict[str, WalletInfo] = {}
    for wallet_addr, pct in holder_pct.items():
        info = WalletInfo(address=wallet_addr, pct_held=pct)
        info.still_holding = pct > 0.001

        pre = mint_tx_data.get(wallet_addr)
        if pre:
            info.first_trade_ts = pre["first_trade_ts"]
            info.volume_sol = pre["volume_sol"]
            info.pct_bought = pre["pct_bought"]
            info.wallet_age_ts = pre["first_trade_ts"]  # approximate age from trade
        else:
            # Fallback: per-wallet API call (only for top 20 holders not in batch)
            first_trade, vol_sol = _get_first_trade_on_token(wallet_addr, contract_address)
            info.first_trade_ts = first_trade
            info.volume_sol = vol_sol
            info.wallet_age_ts = _get_wallet_first_tx_timestamp(wallet_addr)
            info.pct_bought = _estimate_pct_bought(wallet_addr, contract_address, total_supply)

        if info.pct_bought < info.pct_held:
            info.pct_bought = info.pct_held

        wallet_infos[wallet_addr] = info

    # 3. Determine token launch timestamp (earliest first trade across all wallets)
    all_trade_ts = [w.first_trade_ts for w in wallet_infos.values() if w.first_trade_ts]
    token_launch_ts = min(all_trade_ts) if all_trade_ts else None

    # Categorize wallets
    for info in wallet_infos.values():
        info.category = _categorize_wallet(info, token_launch_ts)

    # 4. Cluster wallets by time-linked first trades
    now = int(time.time())
    clusters = _cluster_by_first_trade(list(wallet_infos.values()))

    # 4b. Resolve actual token balances for clustered wallets that show 0% held.
    #     These wallets were discovered from tx history but weren't in top 20 holders.
    clustered_addrs = {w.address for group in clusters for w in group}
    for addr in clustered_addrs:
        info = wallet_infos.get(addr)
        if info and info.pct_held < 0.001 and total_supply > 0:
            balance = helius_client.get_token_balance(addr, contract_address)
            if balance > 0:
                info.pct_held = (balance / total_supply) * 100.0
                info.still_holding = True

    # 5. Build RiskCluster objects
    risk_clusters: List[RiskCluster] = []
    for idx, cluster_wallets in enumerate(clusters, 1):
        rc = RiskCluster(cluster_id=idx, wallets=cluster_wallets)

        rc.pct_bought = sum(w.pct_bought for w in cluster_wallets)
        rc.pct_held = sum(w.pct_held for w in cluster_wallets)
        rc.volume_sol = sum(w.volume_sol for w in cluster_wallets)

        # First trade span
        trade_ts = [w.first_trade_ts for w in cluster_wallets if w.first_trade_ts]
        if len(trade_ts) >= 2:
            span = max(trade_ts) - min(trade_ts)
            rc.first_trade_span_minutes = span / 60.0
            rc.first_trade_age_days = (now - min(trade_ts)) / 86400.0

        # Still holding
        holding_count = sum(1 for w in cluster_wallets if w.still_holding)
        rc.pct_still_holding = holding_count / max(len(cluster_wallets), 1)

        # Common funding (only check for smaller clusters to limit API calls)
        if len(cluster_wallets) <= 10:
            rc.common_funding = _check_common_funding([w.address for w in cluster_wallets])

        # Build flags
        rc.flags = _build_flags(rc)

        # Compute risk
        rc.risk_score = _compute_cluster_risk(rc)
        rc.risk_label = _risk_label(rc.risk_score)

        # Drop weak clusters: time proximity alone is not enough.
        # Require at least one additional signal: common funding, meaningful
        # supply concentration, or very tight timing (< 10 seconds).
        has_funding_signal = rc.common_funding
        has_supply_signal = rc.pct_bought >= 0.5 or rc.pct_held >= 0.5
        has_tight_timing = (
            rc.first_trade_span_minutes is not None
            and rc.first_trade_span_minutes < 0.17  # ~10 seconds
        )
        has_volume_signal = rc.volume_sol >= 2.0

        if has_funding_signal or has_supply_signal or has_tight_timing or has_volume_signal:
            risk_clusters.append(rc)

    # Sort by amount held descending
    risk_clusters.sort(key=lambda c: c.pct_held, reverse=True)

    # Re-number after sort
    for i, rc in enumerate(risk_clusters, 1):
        rc.cluster_id = i

    # Filter out empty clusters (no supply held or bought)
    nonempty = [c for c in risk_clusters if c.pct_held > 0.001 or c.pct_bought > 0.001]
    empty_count = len(risk_clusters) - len(nonempty)

    total_bought = sum(c.pct_bought for c in risk_clusters)
    total_held = sum(c.pct_held for c in risk_clusters)
    high_risk = sum(1 for c in risk_clusters if c.risk_score >= 45)

    overall_risk = 0.0
    if risk_clusters:
        overall_risk = sum(c.risk_score * c.pct_held for c in risk_clusters) / max(total_held, 0.01)

    return ScanResult(
        token_symbol=token_symbol or contract_address[:8],
        contract_address=contract_address,
        overall_risk_score=min(overall_risk, 100.0),
        risk_clusters=risk_clusters,
        total_wallets_analyzed=len(wallet_infos),
        total_supply_bought=total_bought,
        total_supply_held=total_held,
        high_risk_count=high_risk,
    )


# ---------------------------------------------------------------------------
# Clustering by first-trade proximity
# ---------------------------------------------------------------------------

TRADE_CLUSTER_WINDOW_SECONDS = 60  # 1 minute — tighter to avoid false positives
TRADE_CLUSTER_WINDOW_RELAXED = 300  # 5 minutes — used when cluster has extra signals
MAX_CLUSTER_SIZE = 20  # cap to avoid giant clusters from batch data

# Minimum thresholds to consider a wallet for clustering
MIN_VOLUME_SOL = 0.5  # ignore dust buys
MIN_PCT_BOUGHT = 0.01  # ignore negligible supply


def _cluster_by_first_trade(wallets: List[WalletInfo]) -> List[List[WalletInfo]]:
    """Group wallets whose first trades on the token are close in time.

    Only considers wallets above minimum volume/supply thresholds to avoid
    flagging random retail buyers as bundlers.  Uses a tight 1-minute window
    by default; clusters are later validated for additional signals.
    """
    # Filter out dust/retail wallets — they are not bundlers
    eligible = [
        w for w in wallets
        if w.first_trade_ts is not None
        and (w.volume_sol >= MIN_VOLUME_SOL or w.pct_bought >= MIN_PCT_BOUGHT)
    ]

    if len(eligible) < 2:
        return []

    timed = [(w, w.first_trade_ts) for w in eligible]
    timed.sort(key=lambda t: t[1])  # type: ignore[arg-type]

    clusters: List[List[WalletInfo]] = []
    group: List[WalletInfo] = [timed[0][0]]
    group_start = timed[0][1]

    for k in range(1, len(timed)):
        wallet, ts = timed[k]
        prev_ts = timed[k - 1][1]
        gap = ts - prev_ts  # type: ignore[operator]
        span = ts - group_start  # type: ignore[operator]

        # Start new group if gap > half window, total span > window, or size cap hit
        if gap > TRADE_CLUSTER_WINDOW_SECONDS // 2 or span > TRADE_CLUSTER_WINDOW_SECONDS or len(group) >= MAX_CLUSTER_SIZE:
            if len(group) >= 2:
                clusters.append(group)
            group = [wallet]
            group_start = ts
        else:
            group.append(wallet)

    if len(group) >= 2:
        clusters.append(group)

    return clusters


# ---------------------------------------------------------------------------
# Flag generation
# ---------------------------------------------------------------------------

def _build_flags(cluster: RiskCluster) -> List[str]:
    flags: List[str] = []

    # First trade timing
    if cluster.first_trade_span_minutes is not None and cluster.first_trade_age_days is not None:
        n = len(cluster.wallets)
        span_str = f"{cluster.first_trade_span_minutes:.1f}"
        if cluster.first_trade_age_days < 1:
            age_str = f"{cluster.first_trade_age_days * 24:.1f} hours ago"
        elif cluster.first_trade_age_days < 0.042:  # ~1 hour
            age_str = f"{cluster.first_trade_age_days * 1440:.1f} minutes ago"
        else:
            age_str = f"{cluster.first_trade_age_days:.1f} days ago"
        flags.append(f"{n} wallets had their first trade within {span_str} minutes ({age_str})")

    # Common funding
    if cluster.common_funding:
        sharing_count = sum(1 for w in cluster.wallets if True)  # all in cluster
        flags.append(f"{sharing_count} wallets share common funding sources")

    # New wallet ratio
    new_count = sum(1 for w in cluster.wallets if w.category == "New")
    if new_count == len(cluster.wallets) and new_count > 0:
        flags.append("100% are new wallets")

    # Sniper ratio
    sniper_count = sum(1 for w in cluster.wallets if w.category == "Sniper")
    if sniper_count == len(cluster.wallets) and sniper_count > 0:
        flags.append("100% are sniper wallets")

    # Still holding
    if cluster.pct_still_holding >= 0.95:
        flags.append("100% still holding")
    elif cluster.pct_still_holding > 0:
        pct = int(cluster.pct_still_holding * 100)
        flags.append(f"{pct}% still holding")

    return flags
