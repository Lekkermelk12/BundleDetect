from __future__ import annotations

import argparse
import asyncio

from bot.telegram import run as run_bot
from indexer.monitor import run_forever as run_monitor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Solana bundle detector")
    parser.add_argument("mode", choices=["bot", "monitor"], help="Component to run")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "bot":
        run_bot()
    else:
        asyncio.run(run_monitor())


if __name__ == "__main__":
    main()
