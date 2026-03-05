from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List


@dataclass(frozen=True)
class LearningUpdate:
    wallets_seen: int
    newly_known_bundlers: List[str]
    known_bundlers_in_launch: List[str]


class LearningSystem:
    def __init__(self, database: Any) -> None:
        self.database = database

    def process_cluster_detection(self, wallet_addresses: Iterable[str]) -> LearningUpdate:
        wallets = list(dict.fromkeys(wallet_addresses))
        self.database.increment_wallet_bundling_counts(wallets)
        known_after_update = set(self.database.fetch_known_bundlers(wallets))

        wallet_rows = self.database.fetch_wallet_rows(wallets)
        newly_known: List[str] = [
            row["wallet_address"]
            for row in wallet_rows
            if row.get("is_known_bundler") is True and int(row.get("times_seen_bundling") or 0) == 3 and row.get("wallet_address")
        ]

        return LearningUpdate(
            wallets_seen=len(wallets),
            newly_known_bundlers=sorted(newly_known),
            known_bundlers_in_launch=sorted(known_after_update),
        )

    def flag_known_bundlers(self, wallet_addresses: Iterable[str]) -> List[str]:
        return sorted(self.database.fetch_known_bundlers(wallet_addresses))
