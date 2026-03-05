from __future__ import annotations

import os
from typing import Any, Iterable

from detection.layer1 import Cluster


def format_wallet(wallet: str) -> str:
    if len(wallet) <= 8:
        return wallet
    return f"{wallet[:4]}...{wallet[-4:]}"


def render_bundle_report(symbol: str, clusters: Iterable[Cluster], clean_wallet_count: int, total_bundled_pct: float) -> str:
    clusters = list(clusters)
    lines = [f"🔍 Bundle Report — ${symbol}", ""]

    for idx, cluster in enumerate(clusters, 1):
        share = round(total_bundled_pct / max(len(clusters), 1), 2)
        lines.append(f"🚨 Bundler #{idx} — {share}% supply")
        for wallet in cluster.wallets:
            lines.append(f"• {format_wallet(wallet)}")
        lines.append("")

    lines.extend(
        [
            f"⚠️ Total Bundled: {total_bundled_pct:.2f}%",
            f"👥 Unique Bundlers: {len(clusters)}",
            f"✅ Clean Wallets: {clean_wallet_count}",
        ]
    )
    return "\n".join(lines)


async def start(update: Any, context: Any) -> None:
    await update.message.reply_text("Send /scan <SYMBOL> to get a bundle report.")


async def scan(update: Any, context: Any) -> None:
    symbol = context.args[0] if context.args else "UNKNOWN"
    report = render_bundle_report(symbol=symbol, clusters=[], clean_wallet_count=0, total_bundled_pct=0.0)
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
