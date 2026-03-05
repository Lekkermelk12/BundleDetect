from bot.telegram import render_bundle_report
from detection.layer1 import Cluster


def test_report_format():
    cluster = Cluster(
        wallets=("7xKj12343mPq", "9pLm12348vRt"),
        signatures=("sig1", "sig2"),
        platform_program_id="AxiomProgram1111111111111111111111111111111",
        platform_name="Axiom",
        fee_account="fee",
        jito_tip_lamports=5,
    )
    text = render_bundle_report("HELIX", [cluster], clean_wallet_count=76, total_bundled_pct=24.26)

    assert "🔍 Bundle Report — $HELIX" in text
    assert "⚠️ Total Bundled: 24.26%" in text
    assert "👥 Unique Bundlers: 1" in text
    assert "✅ Clean Wallets: 76" in text
