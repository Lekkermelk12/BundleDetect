from api.gmgn import GMGNClient


class FakeSessionManager:
    def __init__(self, tokens):
        self.tokens = list(tokens)
        self.calls = []

    def get_bearer_token(self, force_refresh: bool = False):
        self.calls.append(force_refresh)
        return self.tokens.pop(0)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class FakeHTTPSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, headers, timeout):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return self.responses.pop(0)


def test_wallet_activity_uses_buy_and_sell_and_retries_on_401():
    manager = FakeSessionManager(tokens=["expired-token", "fresh-token"])
    http = FakeHTTPSession(
        responses=[
            FakeResponse(401, {"error": "expired"}),
            FakeResponse(200, {"ok": True, "data": []}),
        ]
    )
    client = GMGNClient(manager, http_session=http)

    payload = client.wallet_activity("wallet-abc")

    assert payload == {"ok": True, "data": []}
    assert len(http.calls) == 2
    assert http.calls[0]["headers"]["Authorization"] == "Bearer expired-token"
    assert http.calls[1]["headers"]["Authorization"] == "Bearer fresh-token"
    assert http.calls[1]["params"]["type"] == ["buy", "sell"]
    assert manager.calls == [False, True]


def test_wallet_daily_profits_and_holdings_pass_wallet_address():
    manager = FakeSessionManager(tokens=["token", "token"])
    http = FakeHTTPSession(
        responses=[
            FakeResponse(200, {"endpoint": "daily"}),
            FakeResponse(200, {"endpoint": "holdings"}),
        ]
    )
    client = GMGNClient(manager, http_session=http)

    daily = client.wallet_daily_profits("wallet-xyz")
    holdings = client.wallet_holdings("wallet-xyz")

    assert daily["endpoint"] == "daily"
    assert holdings["endpoint"] == "holdings"
    assert http.calls[0]["url"].endswith("/wallet/daily_profits")
    assert http.calls[1]["url"].endswith("/wallet/holdings")
    assert http.calls[0]["params"]["address"] == "wallet-xyz"
    assert http.calls[1]["params"]["address"] == "wallet-xyz"
