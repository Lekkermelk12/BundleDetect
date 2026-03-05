from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import AsyncIterator, Iterable

import websockets

PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
RAYDIUM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzefc6vM8ah9R3AKM6W"


@dataclass(frozen=True)
class LaunchEvent:
    signature: str
    slot: int
    program_id: str


class HeliusLaunchMonitor:
    def __init__(self, websocket_url: str | None = None) -> None:
        self.websocket_url = websocket_url or os.getenv("HELIUS_WEBSOCKET", "")
        if not self.websocket_url:
            raise ValueError("HELIUS_WEBSOCKET is required")

    async def subscribe(self, program_ids: Iterable[str]) -> AsyncIterator[LaunchEvent]:
        async with websockets.connect(self.websocket_url) as ws:
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": list(program_ids)},
                            {"commitment": "processed"},
                        ],
                    }
                )
            )

            while True:
                payload = json.loads(await ws.recv())
                result = payload.get("params", {}).get("result", {})
                value = result.get("value", {})
                signature = value.get("signature")
                if not signature:
                    continue
                mentions = value.get("mentions", [])
                program_id = next((x for x in mentions if x in program_ids), "")
                if not program_id:
                    continue
                yield LaunchEvent(
                    signature=signature,
                    slot=int(result.get("context", {}).get("slot", 0)),
                    program_id=program_id,
                )


async def run_forever() -> None:
    logging.basicConfig(level=logging.INFO)
    monitor = HeliusLaunchMonitor()
    async for event in monitor.subscribe([PUMPFUN_PROGRAM, RAYDIUM_PROGRAM]):
        logging.info("detected launch tx=%s slot=%s via=%s", event.signature, event.slot, event.program_id)


if __name__ == "__main__":
    asyncio.run(run_forever())
