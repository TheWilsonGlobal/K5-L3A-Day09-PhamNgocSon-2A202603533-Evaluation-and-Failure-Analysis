"""python -m lab8.check_submission — kiểm format bài nộp trước khi push.

This does not grade. It checks that the instructor's grader will be able to read
what you hand in: shapes return a valid RunResult with a contract-v1 trace, the
report files exist and were produced by the lab tools, and the docs have the
machine-readable lines filled in. Fix every [FAIL] before submitting.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from lab8.console import utf8_stdio

STUDENT_SHAPES = ("workflow", "single", "orchestrator")
ALL_SHAPES = ("workflow", "single", "orchestrator", "swarm")
PUBLIC_SEEDS = [11, 22, 33, 44, 55]


class Report:
    def __init__(self) -> None:
        self.fails = 0
        self.warns = 0

    def ok(self, msg: str) -> None:
        print(f"[ OK ] {msg}")

    def fail(self, msg: str, fix: str) -> None:
        self.fails += 1
        print(f"[FAIL] {msg}\n       -> {fix}")

    def warn(self, msg: str) -> None:
        self.warns += 1
        print(f"[WARN] {msg}")


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def check_shapes(rep: Report) -> None:
    from lab8.app import prepare_store
    from lab8.benchmark import run_trial
    from lab8.db import connect, load_jsonl
    from lab8.metrics import check_trace, trial_pass

    claims = {row["claim_id"]: row for row in load_jsonl(_root() / "data" / "public_claims.jsonl")}
    single_run = [cid for cid in claims if cid not in ("C-011", "C-012")]
    with tempfile.TemporaryDirectory(prefix="lab8-check-", ignore_cleanup_errors=True) as tmp:
        for shape in STUDENT_SHAPES:
            passed = 0
            problems: dict[str, int] = {}
            for claim_id in single_run:
                store = Path(tmp) / f"{shape}-{claim_id}.sqlite"
                prepare_store(store)
                started = time.time()
                payload, error = run_trial(shape, claim_id, 11, store)
                if error is None and payload["error_reason"] == "not_implemented":
                    error = "not_implemented"
                if error is None:
                    trace_ok, trace_reason = check_trace(payload, started_at=started)
                    if not trace_ok:
                        error = trace_reason
                if error is None:
                    conn = connect(store)
                    try:
                        good, reason = trial_pass(payload, claims[claim_id]["expected"], conn, started_at=started)
                    finally:
                        conn.close()
                    if good:
                        passed += 1
                        continue
                    error = reason
                key = error.split(":", 1)[0]
                problems[key] = problems.get(key, 0) + 1
            total = len(single_run)
            fatal = {k: v for k, v in problems.items() if k in (
                "not_implemented", "exception", "invalid_result", "wrong_claim_id",
                "missing_trace", "stale_trace", "invalid_trace", "trace_run_id_mismatch",
            )}
            if fatal:
                detail = ", ".join(f"{k} x{v}" for k, v in fatal.items())
                rep.fail(
                    f"shape {shape}: lỗi format trên claim public (seed 11): {detail}",
                    "run_claim phải trả lab8.schemas.RunResult (dùng lab8.shapes.common.finish), có trace "
                    "đúng mục 'Trace contract v1' trong README, và không được ném exception",
                )
            elif passed < total:
                detail = ", ".join(f"{k} x{v}" for k, v in problems.items())
                rep.warn(f"shape {shape}: format đúng, {passed}/{total} claim public pass ở seed 11 ({detail})")
            else:
                rep.ok(f"shape {shape}: format đúng, {passed}/{total} claim public pass ở seed 11")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def check_reports(rep: Report) -> None:
    root = _root()
    bench_path = root / "reports" / "benchmark.json"
    bench = _load_json(bench_path)
    cmd = ("python -m lab8.benchmark --shapes workflow,single,orchestrator,swarm "
           "--cases data/public_claims.jsonl --seeds 11,22,33,44,55 --out reports/benchmark.json")
    if not isinstance(bench, dict) or "by_shape" not in bench or "controlled_variables" not in bench:
        rep.fail("thiếu reports/benchmark.json hoặc file không do lab8.benchmark tạo", f"chạy: {cmd}")
    else:
        shapes = set(bench["by_shape"])
        seeds = bench["controlled_variables"].get("seeds")
        claim_ids = bench["controlled_variables"].get("claim_ids") or []
        missing = [s for s in ALL_SHAPES if s not in shapes]
        if missing:
            rep.fail(f"reports/benchmark.json thiếu shape {missing}", f"chạy: {cmd}")
        elif seeds != PUBLIC_SEEDS:
            rep.fail(f"reports/benchmark.json có seeds {seeds}, cần {PUBLIC_SEEDS}", f"chạy: {cmd}")
        elif len(claim_ids) < 10:
            rep.fail(f"reports/benchmark.json có {len(claim_ids)} claim, cần ≥ 10", f"chạy: {cmd}")
        else:
            rep.ok(f"reports/benchmark.json: 4 shape x {len(claim_ids)} claim x 5 seed")

    crash = _load_json(root / "reports" / "crash.json")
    if not isinstance(crash, dict) or "crash_safety" not in crash:
        rep.fail("thiếu reports/crash.json", "chạy: python -m lab8.crash_test --count 20 --out reports/crash.json")
    elif crash["crash_safety"] != "20/20":
        rep.fail(f"reports/crash.json crash_safety = {crash['crash_safety']}", "cổng crash cần 20/20")
    else:
        rep.ok("reports/crash.json: 20/20")


def _field(text: str, label: str) -> str | None:
    match = re.search(rf"^\s*-\s*{re.escape(label)}\s*:(.*)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def check_docs(rep: Report) -> None:
    root = _root()
    adr = (root / "docs" / "decision_adr.md").read_text(encoding="utf-8")
    shape = _field(adr, "Shape chọn")
    if shape is None:
        rep.fail("docs/decision_adr.md: không thấy dòng '- Shape chọn:'", "giữ nguyên dòng nhãn trong mẫu")
    elif shape.strip("`").lower() not in ALL_SHAPES:
        rep.fail(
            f"docs/decision_adr.md: Shape chọn = {shape!r}",
            "ghi đúng một trong: workflow, single, orchestrator, swarm (ví dụ '- Shape chọn: workflow')",
        )
    else:
        rep.ok(f"docs/decision_adr.md: Shape chọn = {shape.strip('`').lower()}")
    for label in ("Commit hash", "Run id dẫn chứng", "Pass rate / pass^5 / seed min-max / variance",
                  "Cost per success (mô phỏng, VND)", "Crash safety", "Secret leak / approval bypass"):
        value = _field(adr, label)
        if not value:
            rep.fail(f"docs/decision_adr.md: '{label}' còn trống", f"điền '- {label}: ...' trên cùng dòng")

    contrib = (root / "docs" / "contributions.md").read_text(encoding="utf-8")
    rows = [line for line in contrib.splitlines() if line.startswith("|") and "---" not in line][1:]
    filled = [row for row in rows if row.strip("| ").replace("|", "").strip()]
    if not filled:
        rep.fail("docs/contributions.md: chưa có dòng thành viên nào", "mỗi người một dòng: tên, vai, commit, test")
    else:
        rep.ok(f"docs/contributions.md: {len(filled)} thành viên")

    card = (root / "docs" / "research_card.md").read_text(encoding="utf-8")
    empty = []
    for line in card.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] in ("CÂU", "SOURCE", "CLAIM", "BOUNDARY", "HYPOTHESIS", "METHOD", "FAILURE / METRIC"):
            if not cells[2]:
                empty.append(cells[0])
    if empty:
        rep.fail(f"docs/research_card.md: còn trống {empty}", "điền cột 'Nhóm điền'")
    else:
        rep.ok("docs/research_card.md: đã điền đủ")

    bonus = root / "docs" / "bonus_report.md"
    if bonus.exists():
        text = bonus.read_text(encoding="utf-8")
        if not re.search(r"Bonus report:\s*B[1-6]\b", text):
            rep.fail("docs/bonus_report.md: tiêu đề phải là '# Bonus report: B1' .. 'B6'", "dùng khung trong docs/bonus_topics.md")
        else:
            rep.ok("docs/bonus_report.md: đã khai topic")


def check_git(rep: Report) -> None:
    root = _root()
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        rep.warn("không chạy được git, không đọc được commit hash")
        return
    if dirty.stdout.strip():
        rep.warn("còn thay đổi chưa commit; commit xong rồi mới ghi hash vào docs/decision_adr.md")
    print(f"       commit hash: {head.stdout.strip()}")


def main() -> int:
    utf8_stdio()
    rep = Report()
    print("== shapes ==")
    check_shapes(rep)
    print("== reports ==")
    check_reports(rep)
    print("== docs ==")
    check_docs(rep)
    print("== git ==")
    check_git(rep)
    print(f"\n{rep.fails} FAIL, {rep.warns} WARN")
    if rep.fails:
        print("Sửa hết FAIL trước khi nộp. WARN chỉ là gợi ý, không phải lỗi format.")
    return 1 if rep.fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
