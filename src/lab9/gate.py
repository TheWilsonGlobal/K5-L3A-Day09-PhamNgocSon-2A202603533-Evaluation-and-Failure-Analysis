"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def _ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version only: thresholds may tighten, never loosen (M7)."""
    problems = []
    base_metrics = {m["id"]: m for m in base_spec.get("metrics", [])}
    spec_metrics = {m["id"]: m for m in spec.get("metrics", [])}
    for mid, bm in base_metrics.items():
        if mid not in spec_metrics:
            problems.append(f"ratchet: metric {mid} removed from spec")
            continue
        m = spec_metrics[mid]
        bth, th = bm.get("threshold") or {}, m.get("threshold") or {}
        if bm.get("blocking") and not m.get("blocking"):
            problems.append(f"ratchet: {mid} is blocking on main, not in this PR")
        if "max" in bth and th.get("max", float("inf")) > bth["max"]:
            problems.append(f"ratchet: {mid} max rose {bth['max']} -> {th.get('max')}")
        if "min" in bth and th.get("min", float("-inf")) < bth["min"]:
            problems.append(f"ratchet: {mid} min fell {bth['min']} -> {th.get('min')}")
        if bth.get("no_significant_drop") and not th.get("no_significant_drop"):
            problems.append(f"ratchet: {mid} dropped no_significant_drop")
    base_slices = {s_["name"]: s_ for s_ in base_spec.get("slices") or []}
    spec_slices = {s_["name"]: s_ for s_ in spec.get("slices") or []}
    for name, bs in base_slices.items():
        if name not in spec_slices:
            problems.append(f"ratchet: slice {name} removed from spec")
            continue
        ss = spec_slices[name]
        if bs.get("blocking") and not ss.get("blocking"):
            problems.append(f"ratchet: slice {name} is blocking on main, not in this PR")
        if "min" in bs and ss.get("min", float("-inf")) < bs["min"]:
            problems.append(f"ratchet: slice {name} min fell {bs['min']} -> {ss.get('min')}")
        if bs.get("no_significant_drop") and not ss.get("no_significant_drop"):
            problems.append(f"ratchet: slice {name} dropped no_significant_drop")
    return problems


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate."""
    problems: list[str] = []
    for k, v in pr["metrics"].items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            problems.append(f"metric {k} is {v}")
    n_items, n_seeds = pr["manifest"]["items"], len(pr["manifest"]["seeds"])
    keys = [(r["item_id"], r["seed"]) for r in pr["rows"]]
    if len(keys) != n_items * n_seeds:
        problems.append(f"{len(keys)} rows, expected {n_items} items x {n_seeds} seeds = {n_items * n_seeds}")
    if len(set(keys)) != len(keys):
        problems.append("duplicated (item, seed) rows")
    base_keys = {(r["item_id"], r["seed"]) for r in base["rows"]}
    if set(keys) != base_keys:
        extra, missing = sorted(set(keys) - base_keys), sorted(base_keys - set(keys))
        problems.append(f"(item, seed) set differs from baseline: extra {extra[:3]}, missing {missing[:3]}")
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s): {pr['evaluator_failures'][0]}")
    graded = [m["id"] for m in spec["metrics"]]
    for r in pr["rows"]:
        crashed = [m for m in graded if m in r and r[m] is None]
        if crashed:
            problems.append(f"{r['item_id']}@{r['seed']}: grader returned None for {crashed}")
            break
    base_slices = {r["item_id"]: sorted(r.get("slices") or []) for r in base["rows"]}
    for r in pr["rows"]:
        if sorted(r.get("slices") or []) != base_slices.get(r["item_id"]):
            problems.append(f"{r['item_id']}: slice labels differ from baseline (relabelled)")
            break
    if base_spec is not None and base_spec.get("eval_set_version") == spec.get("eval_set_version"):
        problems += _ratchet_problems(spec, base_spec)
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec["slices"]:
        name, metric = sl["name"], sl["metric"]
        cur = per_item(pr, metric, slice_name=name)
        value = sum(cur.values()) / len(cur) if cur else None
        verdict, note = "ok", ""
        if value is None:
            verdict = "missing"
        elif "min" in sl and value < sl["min"]:
            verdict = "fail"
        if sl.get("no_significant_drop") and cur:
            ref = per_item(base, metric, slice_name=name)
            keys = sorted(set(cur) & set(ref))
            if keys:
                d, lo, hi = stats.paired_bootstrap([cur[k] for k in keys], [ref[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(f"slice:{name}/{metric}")
        tag = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        shown = "-" if value is None else f"{value:.4f}"
        lines.append(f"  slice {name:<17} {metric:<22} {shown:<8} {json.dumps({k: v for k, v in sl.items() if k in ('min', 'no_significant_drop')}):<40} {note:<28} {tag}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
