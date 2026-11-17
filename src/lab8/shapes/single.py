"""Shape B — one bounded ReAct agent (max 8 steps).

`decide` only picks read tools and trusts structured tool results, never ticket
text. After the loop the host validates the quote and is the only writer.
Each decide call is counted as one MockLLM call so cost stays comparable.
"""

from __future__ import annotations

import sqlite3

from lab8.db import connect
from lab8.mock_llm import complete
from lab8.runtime import run_react
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes._commit import commit_quote
from lab8.shapes.common import finish
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace

SHAPE = "single"
MAX_STEPS = 8


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


def _make_decide(budget: Budget, trace: Trace, seed: int, claim: dict):
    state: dict = {"phase": 0, "order": None, "visible": None, "reason": None, "quote": None}

    def decide(seen: dict) -> dict:
        complete(budget, seed=seed, purpose="decide", prompt=f"phase={state['phase']}")
        last = seen.get("last_tool")
        result = seen.get("last_result") or {}
        if last == "lookup_order":
            state["visible"] = bool(result.get("visible"))
            state["reason"] = result.get("reason")
            state["order"] = result.get("order")
        elif last == "compute_compensation":
            state["quote"] = result
        trace.add("step", {"phase": state["phase"], "last_tool": last})

        phase = state["phase"]
        state["phase"] += 1
        if phase == 0:
            if not claim.get("order_id"):
                return {"final": {"status": "needs_info", "error_reason": "missing_order_id"}}
            return {"tool": "lookup_order",
                    "args": {"order_id": claim["order_id"], "principal_id": claim["principal_id"]}}
        if phase == 1:
            if not state["visible"]:
                return {"final": {"status": "escalated", "error_reason": state["reason"]}}
            return {"tool": "lookup_refund_history",
                    "args": {"order_id": claim["order_id"], "principal_id": claim["principal_id"]}}
        if phase == 2:
            return {"tool": "lookup_policy", "args": {}}
        if phase == 3:
            return {"tool": "compute_compensation", "args": {"order": state["order"]}}
        return {"final": {"status": "quoted", "quote": state["quote"]}}

    return decide


def _run(conn: sqlite3.Connection, claim_id: str, *, seed: int, crash_at: str | None) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id(SHAPE, claim_id, seed))

    budget.add_tool(tool_cost())
    claim = get_claim_view(conn, claim_id)
    if not claim.get("found"):
        trace.add("error", {"reason": "unknown_claim"})
        return finish(conn, shape=SHAPE, claim_id=claim_id, seed=seed, status="failed",
                      proposal_amount=0, budget=budget, trace=trace, error_reason="unknown_claim")

    # Model never sees the ticket text; only ids needed for read tools.
    safe_claim = {k: claim.get(k) for k in ("claim_id", "principal_id", "order_id")}
    decide = _make_decide(budget, trace, seed, safe_claim)
    outcome = run_react(conn, budget, observation={"claim": safe_claim}, decide=decide,
                        max_steps=MAX_STEPS, worker=True)
    final = outcome["final"]
    trace.add("loop", {"stopped": outcome["stopped"], "status": final.get("status")})

    status = final.get("status")
    if status in ("needs_info", "escalated", "failed"):
        complete(budget, seed=seed, purpose="draft", prompt=status)
        return finish(conn, shape=SHAPE, claim_id=claim_id, seed=seed, status=status,
                      proposal_amount=0, budget=budget, trace=trace,
                      error_reason=final.get("error_reason"))

    return commit_quote(
        conn, shape=SHAPE, claim_id=claim_id, seed=seed, quote_payload=final.get("quote") or {},
        budget=budget, trace=trace, crash_at=crash_at,
    )
