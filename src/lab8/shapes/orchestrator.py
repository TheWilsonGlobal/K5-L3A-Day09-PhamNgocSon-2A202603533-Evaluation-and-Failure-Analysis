"""Shape C — orchestrator plus read-only investigators.

The orchestrator builds an allowlisted handoff (no parent_secret, headers or full
claim row), investigators run read tools only, and the orchestrator quotes from
the investigator's order view and calls the host. Only the sanitized handoff is
traced.
"""

from __future__ import annotations

import sqlite3

from lab8.db import connect
from lab8.handoff import make_handoff
from lab8.mock_llm import complete
from lab8.runtime import run_readonly_investigators
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes._commit import commit_quote
from lab8.shapes.common import finish, safe_dump
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace

SHAPE = "orchestrator"
INVESTIGATOR_TOOLS = ["lookup_order", "lookup_policy", "lookup_refund_history", "compute_compensation"]


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, claim_id: str, *, seed: int, crash_at: str | None) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id(SHAPE, claim_id, seed))

    budget.add_tool(tool_cost())
    claim = get_claim_view(conn, claim_id)
    if not claim.get("found"):
        trace.add("error", {"reason": "unknown_claim"})
        return finish(conn, shape=SHAPE, claim_id=claim_id, seed=seed, status="failed",
                      proposal_amount=0, budget=budget, trace=trace, error_reason="unknown_claim")

    complete(budget, seed=seed, purpose="plan", prompt="plan")  # orchestrator plan call

    if not claim.get("order_id"):
        complete(budget, seed=seed, purpose="draft", prompt="needs_info")
        trace.add("decision", {"status": "needs_info"})
        return finish(conn, shape=SHAPE, claim_id=claim_id, seed=seed, status="needs_info",
                      proposal_amount=0, budget=budget, trace=trace, error_reason="missing_order_id")

    handoff = make_handoff(
        request_id=f"REQ-{claim_id}",
        claim_id=claim_id,
        task="check_applicable_policy",
        facts={},
        allowed_tools=INVESTIGATOR_TOOLS,
    )
    trace.add("handoff", safe_dump(handoff))

    investigated = run_readonly_investigators(conn, budget, handoff, principal_id=claim["principal_id"])
    tools = investigated["tools"]
    order_view = tools.get("lookup_order", {})
    trace.add("investigator", {
        "visible": bool(order_view.get("visible")),
        "refund_history": {k: v for k, v in (tools.get("lookup_refund_history") or {}).items()
                           if k in ("refund_count", "refunded_vnd")},
    })

    if not order_view.get("visible"):
        complete(budget, seed=seed, purpose="draft", prompt="escalated")
        trace.add("decision", {"status": "escalated", "why": order_view.get("reason")})
        return finish(conn, shape=SHAPE, claim_id=claim_id, seed=seed, status="escalated",
                      proposal_amount=0, budget=budget, trace=trace, error_reason=order_view.get("reason"))

    quote_payload = tools.get("compute_compensation") or {"amount_vnd": 0, "reason": "no_quote"}
    complete(budget, seed=seed, purpose="draft", prompt=f"proposal={quote_payload.get('amount_vnd')}")

    return commit_quote(
        conn, shape=SHAPE, claim_id=claim_id, seed=seed, quote_payload=quote_payload,
        budget=budget, trace=trace, crash_at=crash_at,
    )
