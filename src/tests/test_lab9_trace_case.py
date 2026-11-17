"""Regression test for the trace case in docs/trace_case.md (C-002 @ seed 11).

seeded_regression trusts the ticket's delay (5 days) over the orders table (2 days) at event 3,
then refunds 20.000đ where the label says denied. The fixed shape must not make that override.
Run: python -m pytest -q -m student -o addopts= -k trace_case
"""
from pathlib import Path

import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def run():
    from lab8.db import load_json, load_jsonl
    from lab9 import variants
    from lab9.eval import WORLD, make_task

    variants.register()
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    import tempfile

    def _run(shape):
        with tempfile.TemporaryDirectory(prefix="lab9-test-") as tmp:
            return make_task(shape, load_json(WORLD), claims, labels, Path(tmp))({"claim_id": "C-002", "seed": 11})

    return _run


def test_seeded_regression_overrides_db_at_event_3(run):
    trial = run("seeded_regression")
    events = trial["events"]
    assert events[2]["kind"] == "model_override"          # event 3 (1-based) is the first wrong step
    assert events[2]["payload"] == {"delay_days": 5}
    assert trial["snapshot"]["refund_vnd"] == 20000 and trial["snapshot"]["refund_count"] == 1
    assert trial["unexpected_rows"] == 0                    # the wrong refund is on its own claim


def test_the_code_grader_catches_it(run):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders

    trial = run("seeded_regression")
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output={"refund_vnd": 0, "approval_ok": True},
                           output=trial, duration=0.0, _span_tree=None, attributes={}, metrics={})
    assert graders.DbFactKept().evaluate(ctx).value is False
    assert graders.RefundAmountCorrect().evaluate(ctx).value is False


def test_fixed_keeps_the_db_fact(run):
    trial = run("fixed")
    assert all(e["kind"] != "model_override" for e in trial["events"])
    assert trial["snapshot"]["refund_vnd"] == 0
    assert trial["lab8_pass"] is True
