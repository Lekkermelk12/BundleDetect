from database.models import SupabaseDatabase


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeHTTPSession:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, json, headers, timeout):
        self.posts.append((url, json, headers, timeout))
        return FakeResponse(200, {})

    def get(self, url, params, headers, timeout):
        self.gets.append((url, params, headers, timeout))
        return FakeResponse(200, [])


def test_ensure_tables_executes_expected_schema_sql():
    http = FakeHTTPSession()
    db = SupabaseDatabase("https://example.supabase.co", "svc-key", http_session=http)

    db.ensure_tables()

    assert len(http.posts) == 1
    sql = http.posts[0][1]["sql"]
    assert "CREATE TABLE IF NOT EXISTS wallets" in sql
    assert "wallet_address TEXT PRIMARY KEY" in sql
    assert "CREATE TABLE IF NOT EXISTS clusters" in sql
    assert "wallet_addresses TEXT[]" in sql
    assert "CREATE TABLE IF NOT EXISTS tokens" in sql
    assert "contract_address TEXT PRIMARY KEY" in sql
    assert "CREATE TABLE IF NOT EXISTS cooccurrence" in sql
    assert "times_confirmed_together INTEGER" in sql
