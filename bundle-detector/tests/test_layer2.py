from detection.layer2 import run_layer2


class FakeGMGNClient:
    def __init__(self, holdings_map, activity_map):
        self.holdings_map = holdings_map
        self.activity_map = activity_map

    def wallet_holdings(self, wallet_address: str):
        return self.holdings_map[wallet_address]

    def wallet_activity(self, wallet_address: str):
        return self.activity_map[wallet_address]


def _holdings(tokens):
    return {"data": [{"token_address": t, "amount": 1} for t in tokens]}


def _activity(token, buy_ts, sell_ts):
    return [
        {"token_address": token, "type": "buy", "timestamp": buy_ts, "amount": 1},
        {"token_address": token, "type": "sell", "timestamp": sell_ts, "amount": 1},
    ]


def test_layer2_marks_confirmed_when_three_tokens_have_similar_entry_and_exit():
    wallets = ["w1", "w2", "w3", "w4"]
    holdings_map = {
        "w1": _holdings(["T1", "T2", "T3"]),
        "w2": _holdings(["T1", "T2", "T3"]),
        "w3": _holdings(["T1", "T2", "T3"]),
        "w4": _holdings(["OTHER"]),
    }

    activity_map = {
        "w1": {"data": _activity("T1", 1_700_000_000, 1_700_000_400)
                + _activity("T2", 1_700_000_020, 1_700_000_420)
                + _activity("T3", 1_700_000_030, 1_700_000_430)},
        "w2": {"data": _activity("T1", 1_700_000_120, 1_700_000_500)
                + _activity("T2", 1_700_000_100, 1_700_000_480)
                + _activity("T3", 1_700_000_140, 1_700_000_530)},
        "w3": {"data": _activity("T1", 1_700_000_240, 1_700_000_560)
                + _activity("T2", 1_700_000_260, 1_700_000_580)
                + _activity("T3", 1_700_000_250, 1_700_000_590)},
        "w4": {"data": _activity("OTHER", 1_700_010_000, 1_700_012_000)},
    }

    result = run_layer2(wallets, FakeGMGNClient(holdings_map, activity_map))

    assert result.adaptive_threshold_count == 2
    assert result.shared_tokens == ("T1", "T2", "T3")
    assert result.confidence_level == "high"
    assert result.internal_label == "CONFIRMED BUNDLE"


def test_layer2_marks_possible_when_only_one_shared_token():
    wallets = ["a", "b", "c", "d", "e"]
    holdings_map = {
        "a": _holdings(["X"]),
        "b": _holdings(["X"]),
        "c": _holdings(["Y"]),
        "d": _holdings(["Z"]),
        "e": _holdings(["Q"]),
    }

    activity_map = {
        "a": {"data": _activity("X", 1_700_000_000, 1_700_000_500)},
        "b": {"data": _activity("X", 1_700_000_200, 1_700_000_650)},
        "c": {"data": _activity("Y", 1_700_100_000, 1_700_100_500)},
        "d": {"data": _activity("Z", 1_700_200_000, 1_700_200_500)},
        "e": {"data": _activity("Q", 1_700_300_000, 1_700_300_500)},
    }

    result = run_layer2(wallets, FakeGMGNClient(holdings_map, activity_map))

    assert result.adaptive_threshold_count == 2
    assert result.shared_tokens == ("X",)
    assert result.confidence_level == "low"
    assert result.internal_label == "POSSIBLE BUNDLE"
