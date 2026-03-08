from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the bundle-detector directory (where main.py lives),
# regardless of the working directory the process was started from.
_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE / ".env")

from bot.telegram import run as run_bot  # noqa: E402
from indexer.monitor import run_forever as run_monitor  # noqa: E402


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
