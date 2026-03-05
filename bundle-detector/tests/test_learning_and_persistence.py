from detection.layer1 import run_layer1_from_signatures
from detection.layer2 import run_layer2
from learning.feedback import LearningSystem


PLATFORMS = {"AxiomProgram1111111111111111111111111111111": "Axiom"}


class FakeHelius:
    def __init__(self, txs):
        self.txs = txs

    def get_parsed_transaction(self, signature):
        return self.txs[signature]


class FakeDatabase:
    def __init__(self):
        self.layer1_saved = []
        self.layer2_saved = []
        self.wallet_counts = {}

    def save_layer1_clusters(self, clusters, token_contract=None):
        self.layer1_saved.append((list(clusters), token_contract))
        return ["cluster-1"]

    def save_layer2_result(self, result, cluster_id=None):
        self.layer2_saved.append((result, cluster_id))

    def increment_wallet_bundling_counts(self, wallets):
        for w in wallets:
            self.wallet_counts[w] = self.wallet_counts.get(w, 0) + 1

    def fetch_wallet_rows(self, wallets):
        return [
            {
                "wallet_address": w,
                "times_seen_bundling": self.wallet_counts.get(w, 0),
                "is_known_bundler": self.wallet_counts.get(w, 0) >= 3,
            }
            for w in wallets
        ]

    def fetch_known_bundlers(self, wallets):
        return [w for w in wallets if self.wallet_counts.get(w, 0) >= 3]


class FakeGMGN:
    def wallet_holdings(self, wallet):
        return {"data": [{"token_address": "TKN", "amount": 1}]}

    def wallet_activity(self, wallet):
        base = 1_700_000_000 if wallet == "w1" else 1_700_000_100
        return {
            "data": [
                {"token_address": "TKN", "type": "buy", "timestamp": base, "amount": 1},
                {"token_address": "TKN", "type": "sell", "timestamp": base + 200, "amount": 1},
            ]
        }


def test_layer1_and_layer2_call_database_hooks_and_learning_promotes_after_three_seen():
    txs = {
        "s1": {
            "signature": "s1",
            "feePayer": "w1",
            "nativeTransfers": [{"toUserAccount": "T1pyyaTNZsKv2WcRAB8oVnk93mLJw2XzjtVYqCsaHqt", "amount": 1000}],
            "instructions": [{"programId": "AxiomProgram1111111111111111111111111111111", "accounts": ["x", "fee"]}],
        },
        "s2": {
            "signature": "s2",
            "feePayer": "w2",
            "nativeTransfers": [{"toUserAccount": "T1pyyaTNZsKv2WcRAB8oVnk93mLJw2XzjtVYqCsaHqt", "amount": 1000}],
            "instructions": [{"programId": "AxiomProgram1111111111111111111111111111111", "accounts": ["x", "fee"]}],
        },
    }

    db = FakeDatabase()
    learning = LearningSystem(db)

    clusters = run_layer1_from_signatures(
        ["s1", "s2"],
        FakeHelius(txs),
        PLATFORMS,
        database=db,
        token_contract="TOKENCA",
    )

    assert len(clusters) == 1
    assert len(db.layer1_saved) == 1
    assert db.layer1_saved[0][1] == "TOKENCA"

    for _ in range(3):
        result = run_layer2(
            ["w1", "w2"],
            FakeGMGN(),
            database=db,
            cluster_id="cluster-1",
            learning_system=learning,
        )

    assert result.internal_label == "POSSIBLE BUNDLE"
    assert len(db.layer2_saved) == 3
    assert db.fetch_known_bundlers(["w1", "w2"]) == ["w1", "w2"]
