"""Shape A — deterministic workflow.

Fixed Python steps. Money comes from `compute_compensation` (order row + current
policy), never from ticket text. MockLLM is only used to draft reply text.
The host (`durability.issue_refund`) is the only writer and gets the FULL quote.
"""

from __future__ import annotations

import sqlite3

from lab8.db import connect
from lab8.mock_llm import complete
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes._commit import commit_quote
from lab8.shapes.common import finish
from lab8.tools import compute_compensation, get_claim_view, lookup_order, tool_cost
from lab8.trace import Trace

SHAPE = "workflow"


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

    # 1. Read claim through the allowlisted view.
    budget.add_tool(tool_cost())
    claim = get_claim_view(conn, claim_id)
    if not claim.get("found"):
        trace.add("error", {"reason": "unknown_claim"})
        return finish(conn, shape=SHAPE, claim_id=claim_id, seed=seed, status="failed",
                      proposal_amount=0, budget=budget, trace=trace, error_reason="unknown_claim")
    trace.add("claim", {"claim_id": claim_id, "has_order_id": bool(claim.get("order_id"))})

    # 2. Missing order id -> needs_info (never parse it from the ticket).
    if not claim.get("order_id"):
        complete(budget, seed=seed, purpose="draft", prompt="needs_info")
        trace.add("decision", {"status": "needs_info"})
        return finish(conn, shape=SHAPE, claim_id=claim_id, seed=seed, status="needs_info",
                      proposal_amount=0, budget=budget, trace=trace, error_reason="missing_order_id")

    # 3. Order visible to this principal?
    budget.add_tool(tool_cost())
    view = lookup_order(conn, claim["order_id"], claim["principal_id"])
    if not view.get("visible"):
        complete(budget, seed=seed, purpose="draft", prompt="escalated")
        trace.add("decision", {"status": "escalated", "why": view.get("reason")})
        return finish(conn, shape=SHAPE, claim_id=claim_id, seed=seed, status="escalated",
                      proposal_amount=0, budget=budget, trace=trace, error_reason=view.get("reason"))
    order = view["order"]
    trace.add("order", order)

    # 4. Quote from the structured order row. Ticket delay numbers are ignored.
    budget.add_tool(tool_cost())
    quote_payload = compute_compensation(conn, order)

    complete(budget, seed=seed, purpose="draft", prompt=f"proposal={quote_payload.get('amount_vnd')}")

    # 5-7. Host commit with the full quote.
    return commit_quote(
        conn, shape=SHAPE, claim_id=claim_id, seed=seed, quote_payload=quote_payload,
        budget=budget, trace=trace, crash_at=crash_at,
    )
