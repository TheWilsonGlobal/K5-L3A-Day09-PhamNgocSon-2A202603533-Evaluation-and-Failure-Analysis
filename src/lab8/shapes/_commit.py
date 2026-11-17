"""Shared host-commit step for student shapes.

Only this step touches the ledger. It always passes the FULL quote to
`durability.issue_refund` (the host subtracts earlier refunds itself) and never
swallows `InjectedCrash`.
"""

from __future__ import annotations

import sqlite3

from lab8.durability import InjectedCrash, issue_refund
from lab8.schemas import Budget, RunResult
from lab8.shapes.common import finish
from lab8.trace import Trace


def commit_quote(
    conn: sqlite3.Connection,
    *,
    shape: str,
    claim_id: str,
    seed: int,
    quote_payload: dict,
    budget: Budget,
    trace: Trace,
    crash_at: str | None,
) -> RunResult:
    proposal = int(quote_payload.get("amount_vnd") or 0)
    trace.add("quote", {"amount_vnd": proposal, "reason": quote_payload.get("reason")})

    if proposal <= 0:
        trace.add("decision", {"status": "denied", "why": "quote_zero"})
        return finish(
            conn, shape=shape, claim_id=claim_id, seed=seed, status="denied",
            proposal_amount=0, budget=budget, trace=trace,
            error_reason=quote_payload.get("reason"),
        )

    try:
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise

    if not outcome["ok"]:
        status = "failed" if outcome["conflict"] else "denied"
        trace.add("decision", {"status": status, "why": outcome["reason"]})
        return finish(
            conn, shape=shape, claim_id=claim_id, seed=seed, status=status,
            proposal_amount=proposal, budget=budget, trace=trace,
            error_reason=outcome["reason"],
        )

    trace.add("decision", {"status": "resolved"})
    return finish(
        conn, shape=shape, claim_id=claim_id, seed=seed, status="resolved",
        proposal_amount=proposal, budget=budget, trace=trace, error_reason=None,
    )
