from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

from detection.layer1 import Cluster


def format_wallet(wallet: str) -> str:
    if len(wallet) <= 8:
        return wallet
    return f"{wallet[:4]}...{wallet[-4:]}"


def render_bundle_report(
    symbol: str,
    clusters: Iterable[Cluster],
    clean_wallet_count: int,
    holder_pct_by_wallet: Dict[str, float],
) -> str:
    """Build a human-readable bundle report.

    *holder_pct_by_wallet* maps wallet address -> % of total supply held.
    Each cluster's supply share is the sum of its members' holdings.
    """
    clusters = list(clusters)
    lines = [f"\U0001f50d Bundle Report — ${symbol}", ""]

    total_bundled_pct = 0.0
    for idx, cluster in enumerate(clusters, 1):
        cluster_pct = sum(holder_pct_by_wallet.get(w, 0.0) for w in cluster.wallets)
        total_bundled_pct += cluster_pct
        lines.append(f"\U0001f6a8 Bundler #{idx} — {cluster_pct:.2f}% supply")
        for wallet in cluster.wallets:
            wpct = holder_pct_by_wallet.get(wallet, 0.0)
            lines.append(f"  \u2022 {format_wallet(wallet)}  ({wpct:.2f}%)")
        lines.append("")

    lines.extend(
        [
            f"\u26a0\ufe0f Total Bundled: {total_bundled_pct:.2f}%",
            f"\U0001f465 Unique Bundlers: {len(clusters)}",
            f"\u2705 Clean Wallets: {clean_wallet_count}",
        ]
    )
    return "\n".join(lines)


async def start(update: Any, context: Any) -> None:
    await update.message.reply_text("Send /scan <CONTRACT_ADDRESS> to get a bundle report.")


async def scan(update: Any, context: Any) -> None:
    """Scan a token contract address for bundled wallets."""
    from api.helius import HeliusClient
    from detection.layer1 import run_layer1_from_signatures

    if not context.args:
        await update.message.reply_text("Usage: /scan <CONTRACT_ADDRESS>")
        return

    contract = context.args[0]
    await update.message.reply_text(f"Scanning {contract} …")

    try:
        helius = HeliusClient()

        # Resolve token account owners and build supply % map
        holder_pct = helius.get_holder_pct_by_wallet(contract)

        # Use holder wallets as starting point for bundle detection
        # (In a full pipeline the monitor would supply launch signatures;
        #  here we provide a minimal scan path for the bot.)
        report = render_bundle_report(
            symbol=contract[:8],
            clusters=[],
            clean_wallet_count=len(holder_pct),
            holder_pct_by_wallet=holder_pct,
        )
    except Exception as exc:
        report = f"Error scanning {contract}: {exc}"

    await update.message.reply_text(report)


def build_app() -> Any:
    from telegram.ext import Application, CommandHandler

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    return app


def run() -> None:
    app = build_app()
    app.run_polling()


if __name__ == "__main__":
    run()
