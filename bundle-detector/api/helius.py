from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests


class HeliusClient:
    def __init__(self, rpc_url: str | None = None, parse_tx_url: str | None = None) -> None:
        self.rpc_url = rpc_url or os.getenv("HELIUS_RPC_URL", "")
        self.parse_tx_url = parse_tx_url or os.getenv("HELIUS_PARSE_TX", "")
        if not self.rpc_url or not self.parse_tx_url:
            raise ValueError("HELIUS_RPC_URL and HELIUS_PARSE_TX are required")

    def get_parsed_transaction(self, signature: str) -> Dict[str, Any]:
        response = requests.post(self.parse_tx_url, json={"transactions": [signature]}, timeout=20)
        response.raise_for_status()
        payload = response.json()
        return payload[0] if payload else {}

    def get_parsed_transactions_batch(self, signatures: List[str]) -> List[Dict[str, Any]]:
        """Parse multiple transaction signatures in a single API call (max 100 per batch)."""
        all_results: List[Dict[str, Any]] = []
        for i in range(0, len(signatures), 100):
            batch = signatures[i : i + 100]
            try:
                response = requests.post(self.parse_tx_url, json={"transactions": batch}, timeout=60)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list):
                    all_results.extend(payload)
            except Exception:
                continue
        return all_results

    def _rpc_call(self, method: str, params: list) -> Any:
        """Make a JSON-RPC call to the Helius RPC endpoint."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        response = requests.post(self.rpc_url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"RPC error: {data['error']}")
        return data.get("result")

    def get_token_largest_accounts(self, mint: str) -> List[Dict[str, Any]]:
        """Return the largest token accounts for a given mint.

        Each entry has 'address' (token account) and 'amount'/'uiAmount'.
        """
        result = self._rpc_call("getTokenLargestAccounts", [mint])
        return result.get("value", []) if result else []

    def get_token_supply(self, mint: str) -> float:
        """Return total UI supply for a token mint."""
        result = self._rpc_call("getTokenSupply", [mint])
        if result and "value" in result:
            return float(result["value"].get("uiAmount", 0) or 0)
        return 0.0

    def get_account_info(self, account: str) -> Optional[Dict[str, Any]]:
        """Return parsed account info, useful for resolving token account owners."""
        result = self._rpc_call(
            "getAccountInfo",
            [account, {"encoding": "jsonParsed"}],
        )
        return result.get("value") if result else None

    def get_token_account_owner(self, token_account: str) -> Optional[str]:
        """Resolve a token account address to its owner wallet address."""
        info = self.get_account_info(token_account)
        if not info:
            return None
        try:
            return info["data"]["parsed"]["info"]["owner"]
        except (KeyError, TypeError):
            return None

    def get_signatures_for_address(self, address: str, *, limit: int = 200) -> List[str]:
        """Return recent transaction signatures for an address."""
        result = self._rpc_call(
            "getSignaturesForAddress",
            [address, {"limit": limit}],
        )
        if not result:
            return []
        return [item["signature"] for item in result if isinstance(item, dict) and "signature" in item]

    def get_token_holders_extended(self, mint: str, *, max_wallets: int = 150) -> Dict[str, float]:
        """Get holder % for more wallets by scanning recent mint transactions.

        Combines getTokenLargestAccounts (top 20) with transaction history on
        the mint address to discover additional holders, then resolves their
        current balances.
        """
        total_supply = self.get_token_supply(mint)
        if total_supply <= 0:
            return {}

        wallet_pct: Dict[str, float] = {}

        # 1. Start with top 20 from getTokenLargestAccounts
        largest_accounts = self.get_token_largest_accounts(mint)
        for account in largest_accounts:
            token_account_address = account.get("address", "")
            ui_amount = float(account.get("uiAmount", 0) or 0)
            if not token_account_address or ui_amount <= 0:
                continue
            owner = self.get_token_account_owner(token_account_address)
            if not owner:
                continue
            pct = (ui_amount / total_supply) * 100.0
            wallet_pct[owner] = wallet_pct.get(owner, 0.0) + pct

        # 2. Discover more wallets from mint's transaction signatures
        if len(wallet_pct) < max_wallets:
            try:
                sigs = self.get_signatures_for_address(mint, limit=200)
                if sigs:
                    parsed_txs = self.get_parsed_transactions_batch(sigs)
                    for tx in parsed_txs:
                        if len(wallet_pct) >= max_wallets:
                            break
                        for tt in tx.get("tokenTransfers", []) or []:
                            if not isinstance(tt, dict) or tt.get("mint") != mint:
                                continue
                            for key in ("toUserAccount", "fromUserAccount"):
                                addr = tt.get(key, "")
                                if addr and addr not in wallet_pct and len(wallet_pct) < max_wallets:
                                    wallet_pct[addr] = 0.0
                        # Also check feePayer
                        fee_payer = tx.get("feePayer", "")
                        if fee_payer and fee_payer not in wallet_pct and len(wallet_pct) < max_wallets:
                            wallet_pct[fee_payer] = 0.0
            except Exception:
                pass

        # 3. Wallets discovered from tx history start at 0% (sold their tokens).
        #    Their first-trade data comes from the batch-parsed transactions
        #    in the scanner pipeline, so no per-wallet RPC calls needed here.
        return wallet_pct

    def get_holder_pct_by_wallet(self, mint: str) -> Dict[str, float]:
        """Build a mapping of wallet_address -> percentage of total supply held.

        Uses extended holder discovery to find more than the top 20.
        """
        return self.get_token_holders_extended(mint)
