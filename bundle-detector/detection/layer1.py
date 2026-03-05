from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


JITO_TIP_PROGRAMS = {
    "T1pyyaTNZsKv2WcRAB8oVnk93mLJw2XzjtVYqCsaHqt",
    "4R3gSG8BpU4t19KYj8CfnbtRpnT8gtk4dvTHxVRwc2r7",
}

# Keep this mapping explicit and runtime-configurable by caller.
# Keys are Solana program IDs and values are human-readable platform names.
PlatformPrograms = Dict[str, str]


@dataclass(frozen=True)
class WalletSignal:
    wallet: str
    signature: str
    platform_program_id: str
    platform_name: str
    fee_account: str
    jito_tip_lamports: int


@dataclass(frozen=True)
class Cluster:
    wallets: Tuple[str, ...]
    signatures: Tuple[str, ...]
    platform_program_id: str
    platform_name: str
    fee_account: str
    jito_tip_lamports: int


def _collect_instructions(parsed_tx: Dict[str, Any]) -> List[Dict[str, Any]]:
    instructions: List[Dict[str, Any]] = []

    for ins in parsed_tx.get("instructions", []) or []:
        if isinstance(ins, dict):
            instructions.append(ins)

    events = parsed_tx.get("events", {}) or {}
    for event in events.values():
        if not isinstance(event, dict):
            continue
        for ins in event.get("innerInstructions", []) or []:
            if isinstance(ins, dict):
                instructions.append(ins)

    return instructions


def detect_jito_tip(parsed_tx: Dict[str, Any]) -> Optional[int]:
    for transfer in parsed_tx.get("nativeTransfers", []) or []:
        if transfer.get("toUserAccount") in JITO_TIP_PROGRAMS:
            return int(transfer.get("amount") or 0)
    return None


def detect_platform_and_fee_account(
    parsed_tx: Dict[str, Any], platform_programs: PlatformPrograms
) -> Optional[Tuple[str, str, str]]:
    instructions = _collect_instructions(parsed_tx)
    for instruction in instructions:
        program_id = instruction.get("programId")
        if not program_id or program_id not in platform_programs:
            continue

        accounts = instruction.get("accounts", []) or []
        if not accounts:
            continue

        # In swap-style instructions, platform fee vault/account is commonly the last
        # account meta passed into the platform-specific instruction.
        fee_account = accounts[-1]
        if isinstance(fee_account, str) and fee_account:
            return program_id, platform_programs[program_id], fee_account

    return None


def extract_wallet_signal(
    parsed_tx: Dict[str, Any], platform_programs: PlatformPrograms
) -> Optional[WalletSignal]:
    wallet = parsed_tx.get("feePayer")
    signature = parsed_tx.get("signature")
    if not wallet or not signature:
        return None

    tip = detect_jito_tip(parsed_tx)
    platform_fee = detect_platform_and_fee_account(parsed_tx, platform_programs)
    if tip is None or platform_fee is None:
        return None

    platform_program_id, platform_name, fee_account = platform_fee
    return WalletSignal(
        wallet=wallet,
        signature=signature,
        platform_program_id=platform_program_id,
        platform_name=platform_name,
        fee_account=fee_account,
        jito_tip_lamports=tip,
    )


def detect_binary_bundles(signals: Sequence[WalletSignal]) -> List[Cluster]:
    grouped: Dict[Tuple[str, str, int], List[WalletSignal]] = {}
    for signal in signals:
        key = (signal.platform_program_id, signal.fee_account, signal.jito_tip_lamports)
        grouped.setdefault(key, []).append(signal)

    clusters: List[Cluster] = []
    for (program_id, fee_account, tip), members in grouped.items():
        if len(members) < 2:
            continue

        sorted_members = sorted(members, key=lambda m: m.wallet)
        clusters.append(
            Cluster(
                wallets=tuple(m.wallet for m in sorted_members),
                signatures=tuple(m.signature for m in sorted_members),
                platform_program_id=program_id,
                platform_name=sorted_members[0].platform_name,
                fee_account=fee_account,
                jito_tip_lamports=tip,
            )
        )

    return clusters


def run_layer1_from_parsed_txs(
    parsed_txs: Iterable[Dict[str, Any]],
    platform_programs: PlatformPrograms,
    *,
    database: Optional[Any] = None,
    token_contract: Optional[str] = None,
) -> List[Cluster]:
    signals = []
    for parsed_tx in parsed_txs:
        signal = extract_wallet_signal(parsed_tx, platform_programs)
        if signal is not None:
            signals.append(signal)
    clusters = detect_binary_bundles(signals)
    if database is not None:
        database.save_layer1_clusters(clusters, token_contract=token_contract)
    return clusters


def run_layer1_from_signatures(
    signatures: Iterable[str],
    helius_client: Any,
    platform_programs: PlatformPrograms,
    *,
    database: Optional[Any] = None,
    token_contract: Optional[str] = None,
) -> List[Cluster]:
    parsed_txs = [helius_client.get_parsed_transaction(signature) for signature in signatures]
    return run_layer1_from_parsed_txs(
        parsed_txs,
        platform_programs,
        database=database,
        token_contract=token_contract,
    )


# Backward-compatible helper for pre-fetched wallet/tx tuples.
def run_layer1(
    wallet_to_tx: Iterable[Tuple[str, Dict[str, Any]]],
    platform_programs: PlatformPrograms,
    *,
    database: Optional[Any] = None,
    token_contract: Optional[str] = None,
) -> List[Cluster]:
    parsed_txs: List[Dict[str, Any]] = []
    for wallet, tx in wallet_to_tx:
        tx_copy = dict(tx)
        tx_copy.setdefault("feePayer", wallet)
        tx_copy.setdefault("signature", f"unknown-{wallet}")
        parsed_txs.append(tx_copy)
    return run_layer1_from_parsed_txs(
        parsed_txs,
        platform_programs,
        database=database,
        token_contract=token_contract,
    )
