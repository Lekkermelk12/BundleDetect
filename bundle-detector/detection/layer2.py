from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class WalletTokenState:
    token: str
    entry_timestamp: Optional[int]
    exit_timestamp: Optional[int]
    buy_amount: float


@dataclass(frozen=True)
class TokenCooccurrence:
    token: str
    wallets: Tuple[str, ...]
    entry_similar: bool
    exit_similar: bool
    entry_span_seconds: Optional[int]
    exit_span_seconds: Optional[int]


@dataclass(frozen=True)
class Layer2Result:
    wallet_addresses: Tuple[str, ...]
    adaptive_threshold_count: int
    shared_tokens: Tuple[str, ...]
    token_cooccurrence: Tuple[TokenCooccurrence, ...]
    confidence_level: str
    internal_label: str


TOKEN_KEYS = (
    "token_address",
    "tokenAddress",
    "mint",
    "address",
    "contract_address",
    "contractAddress",
    "ca",
)


def _extract_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    for key in ("data", "items", "list", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            for nested_key in ("items", "list", "records"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [row for row in nested if isinstance(row, dict)]

    return []


def _extract_token_address(record: Dict[str, Any]) -> Optional[str]:
    for key in TOKEN_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    token = record.get("token")
    if isinstance(token, dict):
        for key in TOKEN_KEYS:
            value = token.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _parse_timestamp(value: Any) -> Optional[int]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        ts = int(value)
        # Heuristic for milliseconds
        if ts > 10_000_000_000:
            ts = ts // 1000
        return ts

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return _parse_timestamp(int(text))

        normalized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            return None

    return None


def _extract_amount(record: Dict[str, Any]) -> float:
    for key in ("amount", "size", "qty", "quantity", "volume", "value"):
        value = record.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return 0.0


def _extract_wallet_states(holdings_payload: Dict[str, Any], activity_payload: Dict[str, Any]) -> Dict[str, WalletTokenState]:
    states: Dict[str, Dict[str, Any]] = {}

    for row in _extract_records(holdings_payload):
        token = _extract_token_address(row)
        if not token:
            continue
        states.setdefault(token, {"buy_amount": 0.0, "entry": None, "exit": None})
        states[token]["buy_amount"] = max(states[token]["buy_amount"], _extract_amount(row))

    events = _extract_records(activity_payload)
    # Keep deterministic order based on timestamp ascending when available.
    events = sorted(events, key=lambda r: _parse_timestamp(r.get("timestamp") or r.get("time") or r.get("created_at")) or 0)

    for row in events:
        token = _extract_token_address(row)
        if not token:
            continue

        ts = _parse_timestamp(row.get("timestamp") or row.get("time") or row.get("created_at"))
        event_type = str(row.get("type") or row.get("side") or "").lower()
        amount = _extract_amount(row)

        states.setdefault(token, {"buy_amount": 0.0, "entry": None, "exit": None})

        if event_type == "buy":
            if ts is not None:
                prev = states[token]["entry"]
                states[token]["entry"] = ts if prev is None else min(prev, ts)
            states[token]["buy_amount"] += amount
        elif event_type == "sell":
            if ts is not None:
                prev = states[token]["exit"]
                states[token]["exit"] = ts if prev is None else max(prev, ts)

    return {
        token: WalletTokenState(
            token=token,
            entry_timestamp=values["entry"],
            exit_timestamp=values["exit"],
            buy_amount=float(values["buy_amount"]),
        )
        for token, values in states.items()
    }


def _timestamps_within_window(timestamps: Sequence[Optional[int]], window_seconds: int) -> Tuple[bool, Optional[int]]:
    normalized = [ts for ts in timestamps if ts is not None]
    if len(normalized) < 2:
        return False, None

    span = max(normalized) - min(normalized)
    return span <= window_seconds, span


def run_layer2(
    wallet_addresses: Iterable[str],
    gmgn_client: Any,
    *,
    threshold_ratio: float = 0.30,
    timestamp_window_seconds: int = 600,
    database: Optional[Any] = None,
    cluster_id: Optional[str] = None,
    learning_system: Optional[Any] = None,
) -> Layer2Result:
    wallets = tuple(wallet_addresses)
    if not wallets:
        return Layer2Result(
            wallet_addresses=(),
            adaptive_threshold_count=0,
            shared_tokens=(),
            token_cooccurrence=(),
            confidence_level="low",
            internal_label="POSSIBLE BUNDLE",
        )

    wallet_states: Dict[str, Dict[str, WalletTokenState]] = {}
    for wallet in wallets:
        holdings = gmgn_client.wallet_holdings(wallet)
        activity = gmgn_client.wallet_activity(wallet)
        wallet_states[wallet] = _extract_wallet_states(holdings, activity)

    token_to_wallets: Dict[str, Set[str]] = {}
    for wallet, states in wallet_states.items():
        for token in states.keys():
            token_to_wallets.setdefault(token, set()).add(wallet)

    threshold_count = max(1, ceil(len(wallets) * threshold_ratio))

    cooccurrences: List[TokenCooccurrence] = []
    for token, token_wallets in token_to_wallets.items():
        if len(token_wallets) < threshold_count:
            continue

        sorted_wallets = tuple(sorted(token_wallets))
        entries = [wallet_states[w][token].entry_timestamp for w in sorted_wallets]
        exits = [wallet_states[w][token].exit_timestamp for w in sorted_wallets]

        entry_similar, entry_span = _timestamps_within_window(entries, timestamp_window_seconds)
        exit_similar, exit_span = _timestamps_within_window(exits, timestamp_window_seconds)

        cooccurrences.append(
            TokenCooccurrence(
                token=token,
                wallets=sorted_wallets,
                entry_similar=entry_similar,
                exit_similar=exit_similar,
                entry_span_seconds=entry_span,
                exit_span_seconds=exit_span,
            )
        )

    cooccurrences.sort(key=lambda c: c.token)
    shared_tokens = tuple(c.token for c in cooccurrences)

    similar_entry_exit_count = sum(1 for c in cooccurrences if c.entry_similar and c.exit_similar)
    if similar_entry_exit_count >= 3:
        confidence = "high"
        internal_label = "CONFIRMED BUNDLE"
    else:
        confidence = "low"
        internal_label = "POSSIBLE BUNDLE"

    result = Layer2Result(
        wallet_addresses=wallets,
        adaptive_threshold_count=threshold_count,
        shared_tokens=shared_tokens,
        token_cooccurrence=tuple(cooccurrences),
        confidence_level=confidence,
        internal_label=internal_label,
    )

    if database is not None:
        database.save_layer2_result(result, cluster_id=cluster_id)
    if learning_system is not None:
        learning_system.process_cluster_detection(wallets)

    return result
