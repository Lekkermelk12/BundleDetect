from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional

from detection.scanner import RiskCluster, ScanResult


CLUSTERS_PER_PAGE = 3


# ---------------------------------------------------------------------------
# Risk bar rendering
# ---------------------------------------------------------------------------

def _risk_bar(score: float) -> str:
    """Render a 10-block progress bar like ████████░░."""
    filled = round(score / 10)
    return "\u2588" * filled + "\u2591" * (10 - filled)


def _risk_emoji(score: float) -> str:
    if score >= 70:
        return "\U0001f534"  # red circle
    elif score >= 45:
        return "\U0001f7e1"  # yellow circle
    elif score >= 25:
        return "\U0001f7e0"  # orange circle
    return "\U0001f7e2"  # green circle


def _cluster_icon(cluster: RiskCluster) -> str:
    """Pick 1-2 indicator emojis for a cluster like TrenchScanner uses."""
    icons = []
    if cluster.first_trade_span_minutes is not None and cluster.first_trade_span_minutes < 5:
        icons.append("\u26a1")  # lightning — tight trade timing
    if cluster.common_funding:
        icons.append("\U0001f4b0")  # money bag — common funding
    new_ratio = sum(1 for w in cluster.wallets if w.category == "New") / max(len(cluster.wallets), 1)
    if new_ratio >= 0.8 and not icons:
        icons.append("\U0001f525")  # fire — new wallets
    if cluster.pct_still_holding >= 0.9 and "\u26a1" not in icons:
        icons.append("\u23f1\ufe0f")  # stopwatch — still holding
    return " ".join(icons[:2]) if icons else "\u26a0\ufe0f"


def _category_summary(cluster: RiskCluster) -> Dict[str, int]:
    cats: Dict[str, int] = {}
    for w in cluster.wallets:
        cats[w.category] = cats.get(w.category, 0) + 1
    return cats


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def render_header(result: ScanResult) -> str:
    """Render the top statistics block (shown on every page)."""
    emoji = _risk_emoji(result.overall_risk_score)
    bar = _risk_bar(result.overall_risk_score)
    lines = [
        "\U0001f3af Cluster Risk Analysis",
        "\u2501" * 20,
        f"Token: {result.token_symbol}",
        f"CA: {result.contract_address}",
        "",
        "\U0001f4ca Overall Statistics",
        f"\u251c\u2500 Risk Score: {emoji} {bar} {result.overall_risk_score:.1f}%",
        f"\u251c\u2500 Risk Groups: {len(result.risk_clusters)} ({result.high_risk_count} high)",
        f"\u251c\u2500 Wallets Analyzed: {result.total_wallets_analyzed}",
        f"\u251c\u2500 Supply Bought: {result.total_supply_bought:.2f}%",
        f"\u2514\u2500 Supply Held: {result.total_supply_held:.2f}%",
    ]
    return "\n".join(lines)


def render_cluster(cluster: RiskCluster) -> str:
    """Render a single cluster block."""
    icon = _cluster_icon(cluster)
    emoji = _risk_emoji(cluster.risk_score)
    bar = _risk_bar(cluster.risk_score)
    cats = _category_summary(cluster)

    lines = [
        f"{emoji} Cluster #{cluster.cluster_id} {icon}",
        f"\u251c\u2500 Risk: {bar} {cluster.risk_score:.1f}% [{cluster.risk_label}]",
        f"\u251c\u2500 Wallets: {len(cluster.wallets)}",
        f"\u251c\u2500 Holdings:",
        f"\u2502  \u251c\u2500 Bought: {cluster.pct_bought:.3f}% of supply",
        f"\u2502  \u251c\u2500 Current: {cluster.pct_held:.3f}% of supply",
        f"\u2502  \u2514\u2500 Volume: {cluster.volume_sol:.2f} SOL",
        f"\u251c\u2500 Categories:",
    ]
    cat_items = list(cats.items())
    for i, (cat, count) in enumerate(cat_items):
        prefix = "\u2514\u2500" if i == len(cat_items) - 1 else "\u251c\u2500"
        lines.append(f"\u2502  {prefix} {cat}: {count}")

    if cluster.flags:
        lines.append(f"\u2514\u2500 \u26a0\ufe0f Flags:")
        for i, flag in enumerate(cluster.flags):
            prefix = "\u2514\u2500" if i == len(cluster.flags) - 1 else "\u251c\u2500"
            lines.append(f"   {prefix} {flag}")

    return "\n".join(lines)


def render_page(result: ScanResult, page: int = 1) -> str:
    """Render a full page of the report (header + clusters for this page)."""
    nonempty = [c for c in result.risk_clusters if c.pct_held > 0.001 or c.pct_bought > 0.001]
    empty_count = len(result.risk_clusters) - len(nonempty)
    total_pages = max(1, math.ceil(len(nonempty) / CLUSTERS_PER_PAGE))
    page = max(1, min(page, total_pages))

    start = (page - 1) * CLUSTERS_PER_PAGE
    end = start + CLUSTERS_PER_PAGE
    page_clusters = nonempty[start:end]

    header = render_header(result)
    sort_line = f"\U0001f3af Risk Clusters (Page {page}/{total_pages})"
    hidden = f" ({empty_count} empty hidden)" if empty_count else ""
    sort_line += f"\nSorted by: Amount Held{hidden}"

    body_parts = [render_cluster(c) for c in page_clusters]

    parts = [header, "", sort_line, ""] + body_parts
    return "\n".join(parts)


def total_pages(result: ScanResult) -> int:
    nonempty = [c for c in result.risk_clusters if c.pct_held > 0.001 or c.pct_bought > 0.001]
    return max(1, math.ceil(len(nonempty) / CLUSTERS_PER_PAGE))


# ---------------------------------------------------------------------------
# Legacy report (kept for backward compatibility / tests)
# ---------------------------------------------------------------------------

def render_bundle_report(
    symbol: str,
    clusters: Any,
    clean_wallet_count: int,
    holder_pct_by_wallet: Dict[str, float],
) -> str:
    """Build a human-readable bundle report (legacy format)."""
    from detection.layer1 import Cluster as L1Cluster

    cluster_list = list(clusters)
    lines = ["\U0001f50d Bundle Report \u2014 $" + symbol, ""]

    total_bundled_pct = 0.0
    for idx, cluster in enumerate(cluster_list, 1):
        cluster_pct = sum(holder_pct_by_wallet.get(w, 0.0) for w in cluster.wallets)
        total_bundled_pct += cluster_pct
        lines.append(f"\U0001f6a8 Bundler #{idx} \u2014 {cluster_pct:.2f}% supply")
        for wallet in cluster.wallets:
            wpct = holder_pct_by_wallet.get(wallet, 0.0)
            lines.append(f"  \u2022 {wallet[:4]}...{wallet[-4:]}  ({wpct:.2f}%)")
        lines.append("")

    lines.extend([
        f"\u26a0\ufe0f Total Bundled: {total_bundled_pct:.2f}%",
        f"\U0001f465 Unique Bundlers: {len(cluster_list)}",
        f"\u2705 Clean Wallets: {clean_wallet_count}",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram handlers
# ---------------------------------------------------------------------------

async def start(update: Any, context: Any) -> None:
    await update.message.reply_text(
        "\U0001f3af Bundle Risk Scanner\n\n"
        "Send /scan <CONTRACT_ADDRESS> to get a cluster risk analysis.\n"
        "Send /scan <CONTRACT_ADDRESS> <PAGE> to view a specific page."
    )


async def scan(update: Any, context: Any) -> None:
    """Scan a token contract address for bundled wallets."""
    from api.helius import HeliusClient
    from detection.scanner import run_scan

    if not context.args:
        await update.message.reply_text("Usage: /scan <CONTRACT_ADDRESS> [page]")
        return

    contract = context.args[0]
    page = 1
    if len(context.args) >= 2:
        try:
            page = int(context.args[1])
        except ValueError:
            pass

    await update.message.reply_text(f"\U0001f50e Scanning {contract} \u2026")

    try:
        helius = HeliusClient()
        result = run_scan(contract, helius, token_symbol=contract[:8])

        if not result.risk_clusters:
            await update.message.reply_text(
                f"\u2705 No risk clusters found for {contract}\n"
                f"Wallets analyzed: {result.total_wallets_analyzed}"
            )
            return

        n_pages = total_pages(result)

        # Send all pages
        for p in range(1, n_pages + 1):
            report = render_page(result, page=p)
            await update.message.reply_text(report)

    except Exception as exc:
        await update.message.reply_text(f"\u274c Error scanning {contract}: {exc}")


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
