"""Statistics for the Lab 9 eval factory (M2 judge calibration, M4 paired bootstrap, M6 pass^k).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py and tests/test_lab9_advanced.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy import stats as sps

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def _pairs(human: Sequence[str], judge: Sequence[str]) -> list[tuple[str, str]]:
    if len(human) != len(judge):
        raise ValueError(f"human and judge lengths differ: {len(human)} != {len(judge)}")
    return [(str(h).strip().upper(), str(j).strip().upper()) for h, j in zip(human, judge)]


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    out = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for h, j in _pairs(human, judge):
        if h == POS and j == POS:
            out["tp"] += 1
        elif h != POS and j == POS:
            out["fp"] += 1
        elif h == POS and j != POS:
            out["fn"] += 1
        else:
            out["tn"] += 1
    return out


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    """precision = tp/(tp+fp), recall = tp/(tp+fn); 0.0 when the denominator is 0."""
    cm = confusion(human, judge)
    precision = cm["tp"] / (cm["tp"] + cm["fp"]) if cm["tp"] + cm["fp"] else 0.0
    recall = cm["tp"] / (cm["tp"] + cm["fn"]) if cm["tp"] + cm["fn"] else 0.0
    return precision, recall


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    cm = confusion(human, judge)
    n = sum(cm.values())
    if n == 0:
        raise ValueError("kappa undefined for an empty sample")
    p_o = (cm["tp"] + cm["tn"]) / n
    p_fail_h = (cm["tp"] + cm["fn"]) / n
    p_fail_j = (cm["tp"] + cm["fp"]) / n
    p_pass_h = (cm["fp"] + cm["tn"]) / n
    p_pass_j = (cm["fn"] + cm["tn"]) / n
    p_e = p_fail_h * p_fail_j + p_pass_h * p_pass_j
    if math.isclose(p_e, 1.0, abs_tol=1e-12):
        raise ValueError("kappa undefined: chance agreement is 1 (constant judge or constant human)")
    return (p_o - p_e) / (1.0 - p_e)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1].
    true = (p_obs + spec - 1) / (sens + spec - 1). Undefined when sens + spec == 1 (judge no better than chance)."""
    denom = sensitivity + specificity - 1.0
    if math.isclose(denom, 0.0, abs_tol=1e-12):
        raise ValueError("Rogan-Gladen undefined: sensitivity + specificity == 1")
    return min(1.0, max(0.0, (observed_rate + specificity - 1.0) / denom))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) from a percentile bootstrap that resamples items in pairs.
    If a == b on every item return (0.0, 0.0, 0.0)."""
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    if len(a) == 0:
        raise ValueError("paired bootstrap needs at least one item")
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if np.array_equal(x, y):
        return 0.0, 0.0, 0.0

    def diff_of_means(u, v, axis=-1):
        return np.mean(u, axis=axis) - np.mean(v, axis=axis)

    res = sps.bootstrap((x, y), diff_of_means, paired=True, vectorized=True, method="percentile",
                        n_resamples=n_resamples, confidence_level=confidence,
                        random_state=np.random.default_rng(rng))
    ci = res.confidence_interval
    return float(np.mean(x) - np.mean(y)), float(ci.low), float(ci.high)


def _check_nk(n: int, c: int, k: int) -> None:
    if k < 1 or n < 1:
        raise ValueError(f"need n >= 1 and k >= 1, got n={n}, k={k}")
    if k > n:
        raise ValueError(f"k={k} cannot exceed n={n}")
    if c < 0 or c > n:
        raise ValueError(f"c={c} must be between 0 and n={n}")


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    _check_nk(n, c, k)
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    _check_nk(n, c, k)
    return math.comb(c, k) / math.comb(n, k)
