from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence


class SupabaseDatabase:
    def __init__(
        self,
        supabase_url: Optional[str] = None,
        service_key: Optional[str] = None,
        *,
        timeout_seconds: int = 20,
        http_session: Optional[Any] = None,
    ) -> None:
        self.supabase_url = (supabase_url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.service_key = service_key or os.getenv("SUPABASE_SERVICE_KEY", "")
        self.timeout_seconds = timeout_seconds
        if not self.supabase_url or not self.service_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")

        if http_session is None:
            import requests

            self.http_session = requests.Session()
        else:
            self.http_session = http_session

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }

    def _execute_sql(self, sql: str) -> None:
        attempts = [
            (f"{self.supabase_url}/rest/v1/rpc/exec_sql", {"sql": sql}),
            (f"{self.supabase_url}/sql/v1", {"query": sql}),
            (f"{self.supabase_url}/pg/v1/query", {"query": sql}),
        ]

        errors: List[str] = []
        for url, payload in attempts:
            response = self.http_session.post(url, json=payload, headers=self._headers, timeout=self.timeout_seconds)
            if 200 <= response.status_code < 300:
                return
            errors.append(f"{url} -> {response.status_code}: {getattr(response, 'text', '')}")

        raise RuntimeError("Supabase SQL execution failed across endpoints: " + " | ".join(errors))

    def ensure_tables(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS wallets (
            wallet_address TEXT PRIMARY KEY,
            first_seen TIMESTAMP,
            platform_preference VARCHAR,
            jito_tip_preference FLOAT,
            is_known_bundler BOOLEAN DEFAULT FALSE,
            times_seen_bundling INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS clusters (
            cluster_id TEXT PRIMARY KEY,
            wallet_addresses TEXT[],
            platform VARCHAR,
            jito_tip FLOAT,
            first_detected TIMESTAMP,
            times_seen_together INTEGER DEFAULT 0,
            tokens_bundled TEXT[],
            confirmed BOOLEAN DEFAULT FALSE
        );

        CREATE TABLE IF NOT EXISTS tokens (
            contract_address TEXT PRIMARY KEY,
            launch_timestamp TIMESTAMP,
            cluster_ids TEXT[],
            total_bundled_pct FLOAT,
            indexed_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS cooccurrence (
            wallet_a VARCHAR,
            wallet_b VARCHAR,
            shared_tokens TEXT[],
            entry_similarity_score FLOAT,
            exit_similarity_score FLOAT,
            times_confirmed_together INTEGER DEFAULT 0,
            PRIMARY KEY(wallet_a, wallet_b)
        );
        """
        self._execute_sql(ddl)

    def _upsert(self, table: str, rows: Sequence[Dict[str, Any]], on_conflict: Optional[str] = None) -> None:
        if not rows:
            return
        headers = dict(self._headers)
        prefer = "resolution=merge-duplicates,return=minimal"
        if on_conflict:
            prefer = f"{prefer},on_conflict={on_conflict}"
        headers["Prefer"] = prefer
        url = f"{self.supabase_url}/rest/v1/{table}"
        response = self.http_session.post(url, json=list(rows), headers=headers, timeout=self.timeout_seconds)
        response.raise_for_status()

    def _select(self, table: str, *, select: str, filters: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        params = {"select": select}
        if filters:
            params.update(filters)
        url = f"{self.supabase_url}/rest/v1/{table}"
        response = self.http_session.get(url, params=params, headers=self._headers, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def _cluster_id(self, wallets: Iterable[str], platform: str, fee_account: str, jito_tip_lamports: int) -> str:
        base = "|".join(sorted(wallets)) + f"|{platform}|{fee_account}|{jito_tip_lamports}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]

    def save_layer1_clusters(self, clusters: Iterable[Any], *, token_contract: Optional[str] = None) -> List[str]:
        self.ensure_tables()
        now = datetime.now(timezone.utc).isoformat()
        cluster_ids: List[str] = []

        wallet_rows: List[Dict[str, Any]] = []
        cluster_rows: List[Dict[str, Any]] = []

        for cluster in clusters:
            cluster_id = self._cluster_id(
                cluster.wallets,
                getattr(cluster, "platform_program_id", "unknown"),
                cluster.fee_account,
                cluster.jito_tip_lamports,
            )
            cluster_ids.append(cluster_id)
            cluster_rows.append(
                {
                    "cluster_id": cluster_id,
                    "wallet_addresses": list(cluster.wallets),
                    "platform": getattr(cluster, "platform_name", "unknown"),
                    "jito_tip": float(cluster.jito_tip_lamports),
                    "first_detected": now,
                    "times_seen_together": 1,
                    "tokens_bundled": [token_contract] if token_contract else [],
                    "confirmed": False,
                }
            )
            for wallet in cluster.wallets:
                wallet_rows.append(
                    {
                        "wallet_address": wallet,
                        "first_seen": now,
                        "platform_preference": getattr(cluster, "platform_name", "unknown"),
                        "jito_tip_preference": float(cluster.jito_tip_lamports),
                        "is_known_bundler": False,
                        "times_seen_bundling": 1,
                    }
                )

        self._upsert("clusters", cluster_rows, on_conflict="cluster_id")
        self._upsert("wallets", wallet_rows, on_conflict="wallet_address")

        if token_contract and cluster_ids:
            token_row = {
                "contract_address": token_contract,
                "launch_timestamp": now,
                "cluster_ids": cluster_ids,
                "total_bundled_pct": 0.0,
                "indexed_at": now,
            }
            self._upsert("tokens", [token_row], on_conflict="contract_address")

        return cluster_ids

    def save_layer2_result(self, layer2_result: Any, *, cluster_id: Optional[str] = None) -> None:
        self.ensure_tables()

        if cluster_id is not None:
            self._upsert("clusters", [{"cluster_id": cluster_id, "confirmed": layer2_result.confidence_level == "high"}], on_conflict="cluster_id")

        co_rows: List[Dict[str, Any]] = []
        for token_info in layer2_result.token_cooccurrence:
            for wallet_a, wallet_b in combinations(token_info.wallets, 2):
                co_rows.append(
                    {
                        "wallet_a": wallet_a,
                        "wallet_b": wallet_b,
                        "shared_tokens": [token_info.token],
                        "entry_similarity_score": 1.0 if token_info.entry_similar else 0.0,
                        "exit_similarity_score": 1.0 if token_info.exit_similar else 0.0,
                        "times_confirmed_together": 1,
                    }
                )

        self._upsert("cooccurrence", co_rows, on_conflict="wallet_a,wallet_b")

    def increment_wallet_bundling_counts(self, wallets: Iterable[str]) -> None:
        self.ensure_tables()
        now = datetime.now(timezone.utc).isoformat()
        existing_rows = self._select("wallets", select="wallet_address,times_seen_bundling,is_known_bundler", filters={"wallet_address": f"in.({','.join(wallets)})"})
        existing_map = {row["wallet_address"]: row for row in existing_rows if row.get("wallet_address")}

        updates = []
        for wallet in wallets:
            previous = int(existing_map.get(wallet, {}).get("times_seen_bundling") or 0)
            new_count = previous + 1
            updates.append(
                {
                    "wallet_address": wallet,
                    "first_seen": now,
                    "times_seen_bundling": new_count,
                    "is_known_bundler": new_count >= 3,
                }
            )

        self._upsert("wallets", updates, on_conflict="wallet_address")


    def fetch_wallet_rows(self, wallets: Iterable[str]) -> List[Dict[str, Any]]:
        wallet_list = list(wallets)
        if not wallet_list:
            return []
        return self._select(
            "wallets",
            select="wallet_address,times_seen_bundling,is_known_bundler",
            filters={"wallet_address": f"in.({','.join(wallet_list)})"},
        )

    def fetch_known_bundlers(self, wallets: Iterable[str]) -> List[str]:
        wallet_list = list(wallets)
        if not wallet_list:
            return []
        rows = self._select(
            "wallets",
            select="wallet_address,is_known_bundler",
            filters={
                "wallet_address": f"in.({','.join(wallet_list)})",
                "is_known_bundler": "eq.true",
            },
        )
        return [row["wallet_address"] for row in rows if row.get("wallet_address")]
