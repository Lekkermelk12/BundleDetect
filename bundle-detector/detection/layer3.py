"""Layer 3 — Time-linked funding detection.

Groups wallets that were funded (created / first received SOL) within a
configurable time window.  The default window is ±24 hours (86 400 seconds).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


FUNDING_WINDOW_SECONDS: int = 86_400  # ±24 hours


@dataclass(frozen=True)
class FundingSignal:
    wallet: str
    first_funding_timestamp: Optional[int]  # unix epoch seconds


@dataclass(frozen=True)
class FundingCluster:
    wallets: Tuple[str, ...]
    earliest_funding: int
    latest_funding: int
    span_seconds: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_timestamp(value: Any) -> Optional[int]:
    """Best-effort extraction of a unix-epoch timestamp."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = int(value)
        if ts > 10_000_000_000:
            ts = ts // 1000
        return ts
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return _parse_timestamp(int(text))
    return None


def _fetch_first_funding_timestamp(wallet: str, helius_client: Any) -> Optional[int]:
    """Use Helius parsed transaction history to find the wallet's earliest inbound SOL transfer."""
    import os, requests  # noqa: E401

    history_url = os.getenv("HELIUS_PARSE_HISTORY", "")
    if not history_url:
        return None

    url = history_url.replace("{address}", wallet)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        txs = resp.json()
    except Exception:
        return None

    if not isinstance(txs, list) or not txs:
        return None

    # Helius returns newest-first; find the earliest timestamp
    earliest: Optional[int] = None
    for tx in txs:
        ts = _parse_timestamp(tx.get("timestamp"))
        if ts is not None:
            earliest = ts if earliest is None else min(earliest, ts)
    return earliest


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def build_funding_signals(
    wallet_addresses: Sequence[str],
    helius_client: Any,
) -> List[FundingSignal]:
    """Fetch first-funding timestamps for each wallet."""
    signals: List[FundingSignal] = []
    for wallet in wallet_addresses:
        ts = _fetch_first_funding_timestamp(wallet, helius_client)
        signals.append(FundingSignal(wallet=wallet, first_funding_timestamp=ts))
    return signals


def detect_time_linked_clusters(
    signals: Sequence[FundingSignal],
    window_seconds: int = FUNDING_WINDOW_SECONDS,
) -> List[FundingCluster]:
    """Group wallets whose first-funding timestamps fall within *window_seconds* of each other.

    Uses a greedy sweep: sort by timestamp, then extend each cluster while the
    span from the cluster's earliest timestamp stays within the window.
    """
    timed = [(s.wallet, s.first_funding_timestamp) for s in signals if s.first_funding_timestamp is not None]
    if len(timed) < 2:
        return []

    timed.sort(key=lambda t: t[1])  # type: ignore[arg-type]

    clusters: List[FundingCluster] = []
    i = 0
    while i < len(timed):
        group_wallets = [timed[i][0]]
        earliest = timed[i][1]
        j = i + 1
        while j < len(timed) and (timed[j][1] - earliest) <= window_seconds:  # type: ignore[operator]
            group_wallets.append(timed[j][0])
            j += 1
        if len(group_wallets) >= 2:
            latest = timed[j - 1][1]
            clusters.append(
                FundingCluster(
                    wallets=tuple(sorted(group_wallets)),
                    earliest_funding=earliest,  # type: ignore[arg-type]
                    latest_funding=latest,  # type: ignore[arg-type]
                    span_seconds=latest - earliest,  # type: ignore[operator]
                )
            )
        i = j  # advance past the current group

    return clusters


def run_layer3(
    wallet_addresses: Sequence[str],
    helius_client: Any,
    *,
    window_seconds: int = FUNDING_WINDOW_SECONDS,
) -> List[FundingCluster]:
    """End-to-end Layer 3: fetch funding timestamps and cluster wallets."""
    signals = build_funding_signals(wallet_addresses, helius_client)
    return detect_time_linked_clusters(signals, window_seconds=window_seconds)
