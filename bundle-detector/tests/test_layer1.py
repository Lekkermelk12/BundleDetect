from detection.layer1 import run_layer1_from_signatures

PLATFORMS = {
    "AxiomProgram1111111111111111111111111111111": "Axiom",
    "PhotonProgram111111111111111111111111111111": "Photon",
}


class FakeHeliusClient:
    def __init__(self, tx_map):
        self.tx_map = tx_map

    def get_parsed_transaction(self, signature: str):
        return self.tx_map[signature]


def parsed_tx(signature: str, wallet: str, program: str, fee: str, tip: int):
    return {
        "signature": signature,
        "feePayer": wallet,
        "nativeTransfers": [
            {
                "toUserAccount": "T1pyyaTNZsKv2WcRAB8oVnk93mLJw2XzjtVYqCsaHqt",
                "amount": tip,
            }
        ],
        "instructions": [{"programId": program, "accounts": ["source", fee]}],
    }


def test_layer1_from_signatures_groups_on_exact_triplet_match():
    tx_map = {
        "sig1": parsed_tx(
            "sig1",
            "wallet1",
            "AxiomProgram1111111111111111111111111111111",
            "feeA",
            20_000,
        ),
        "sig2": parsed_tx(
            "sig2",
            "wallet2",
            "AxiomProgram1111111111111111111111111111111",
            "feeA",
            20_000,
        ),
        # same platform+tip but different fee account -> NOT same bundle
        "sig3": parsed_tx(
            "sig3",
            "wallet3",
            "AxiomProgram1111111111111111111111111111111",
            "feeB",
            20_000,
        ),
        # same platform+fee but different tip -> NOT same bundle
        "sig4": parsed_tx(
            "sig4",
            "wallet4",
            "AxiomProgram1111111111111111111111111111111",
            "feeA",
            25_000,
        ),
    }

    clusters = run_layer1_from_signatures(["sig1", "sig2", "sig3", "sig4"], FakeHeliusClient(tx_map), PLATFORMS)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.wallets == ("wallet1", "wallet2")
    assert cluster.platform_program_id == "AxiomProgram1111111111111111111111111111111"
    assert cluster.fee_account == "feeA"
    assert cluster.jito_tip_lamports == 20_000
