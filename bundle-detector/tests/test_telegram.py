from bot.telegram import render_bundle_report, render_header, render_cluster, render_page
from detection.layer1 import Cluster
from detection.scanner import RiskCluster, ScanResult, WalletInfo


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

    assert "\U0001f50d Bundle Report \u2014 $HELIX" in text
    assert "\u26a0\ufe0f Total Bundled: 24.26%" in text
    assert "\U0001f465 Unique Bundlers: 1" in text
    assert "\u2705 Clean Wallets: 76" in text


def test_risk_report_header():
    result = ScanResult(
        token_symbol="TEST",
        contract_address="abc123",
        overall_risk_score=66.9,
        risk_clusters=[],
        total_wallets_analyzed=100,
        total_supply_bought=21.30,
        total_supply_held=15.60,
        high_risk_count=4,
    )
    header = render_header(result)
    assert "Cluster Risk Analysis" in header
    assert "Token: TEST" in header
    assert "CA: abc123" in header
    assert "66.9%" in header
    assert "Risk Groups: 0 (4 high)" in header
    assert "Wallets Analyzed: 100" in header
    assert "Supply Bought: 21.30%" in header
    assert "Supply Held: 15.60%" in header


def test_risk_cluster_rendering():
    w1 = WalletInfo(address="wallet1", pct_held=2.5, pct_bought=3.0, category="New", still_holding=True)
    w2 = WalletInfo(address="wallet2", pct_held=1.5, pct_bought=2.0, category="New", still_holding=True)
    cluster = RiskCluster(
        cluster_id=1,
        wallets=[w1, w2],
        pct_bought=5.0,
        pct_held=4.0,
        volume_sol=2.5,
        risk_score=80.0,
        risk_label="VERY HIGH",
        flags=["2 wallets had their first trade within 1.0 minutes (2.0 days ago)", "100% are new wallets"],
        first_trade_span_minutes=1.0,
        pct_still_holding=1.0,
    )
    text = render_cluster(cluster)
    assert "Cluster #1" in text
    assert "80.0%" in text
    assert "VERY HIGH" in text
    assert "Wallets: 2" in text
    assert "5.000% of supply" in text
    assert "4.000% of supply" in text
    assert "2.50 SOL" in text
    assert "New: 2" in text
    assert "100% are new wallets" in text


def test_pagination():
    wallets = [WalletInfo(address=f"w{i}", pct_held=1.0, category="Regular") for i in range(4)]
    clusters = []
    for i in range(7):
        clusters.append(RiskCluster(
            cluster_id=i + 1,
            wallets=wallets[:2],
            pct_bought=1.0,
            pct_held=0.5,
            risk_score=50.0,
            risk_label="HIGH",
        ))

    result = ScanResult(
        token_symbol="TEST",
        contract_address="abc",
        overall_risk_score=50.0,
        risk_clusters=clusters,
        total_wallets_analyzed=20,
        total_supply_bought=7.0,
        total_supply_held=3.5,
        high_risk_count=7,
    )

    page1 = render_page(result, page=1)
    assert "Page 1/3" in page1

    page3 = render_page(result, page=3)
    assert "Page 3/3" in page3
