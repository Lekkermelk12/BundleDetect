from __future__ import annotations

import os
from typing import Any, Dict

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
