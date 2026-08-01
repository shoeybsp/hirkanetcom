from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_input_page_has_packet_flow_disclaimer():
    text = read("templates/client/policy_evaluation.html")
    assert "not a full FortiGate packet-flow simulation" in text
    assert "Validate proposed changes" in text


def test_result_pages_label_outputs_as_heuristic():
    single = read("templates/client/results.html")
    batch = read("templates/client/batch_results.html")
    assert "Heuristic recommendation" in single
    assert "Top recommended candidate" in single
    assert "Decision-support only" in batch
    assert "Top Recommended Candidates" in batch


def test_documentation_explains_material_limitations():
    readme = read("README.md")
    manual = read("USER_MANUAL.md")
    for phrase in ("policy order", "NAT", "VDOM", "runtime"):
        assert phrase in readme
    assert "not a definitive FortiGate allow/deny decision" in manual


def test_engine_contract_is_not_authoritative_simulation():
    text = read("engine/evaluator.py")
    assert "Heuristic FortiGate policy candidate evaluator" in text
    assert "must not be used as an authoritative allow/deny" in text
