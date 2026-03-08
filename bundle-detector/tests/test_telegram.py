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
    holder_pct = {"7xKj12343mPq": 12.13, "9pLm12348vRt": 12.13}
    text = render_bundle_report("HELIX", [cluster], clean_wallet_count=76, holder_pct_by_wallet=holder_pct)

    assert "\U0001f50d Bundle Report — $HELIX" in text
    assert "\u26a0\ufe0f Total Bundled: 24.26%" in text
    assert "\U0001f465 Unique Bundlers: 1" in text
    assert "\u2705 Clean Wallets: 76" in text
