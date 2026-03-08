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

    def get_holder_pct_by_wallet(self, mint: str) -> Dict[str, float]:
        """Build a mapping of wallet_address -> percentage of total supply held.

        Fetches the largest token accounts, resolves each to its owner wallet,
        and calculates the percentage of total supply each wallet holds.
        """
        total_supply = self.get_token_supply(mint)
        if total_supply <= 0:
            return {}

        largest_accounts = self.get_token_largest_accounts(mint)
        wallet_pct: Dict[str, float] = {}

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

        return wallet_pct
