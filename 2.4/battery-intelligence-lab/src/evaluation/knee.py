"""Knee-point test on a short, noisy degradation series.

Compares a single line with a continuous two-segment line (breakpoint searched over the
observed x values, at least `min_side` points on each side) by BIC. A knee *candidate*
requires all of:
  - delta BIC (line - two-segment) >= DELTA_BIC_MIN  (strong evidence for the extra segment)
  - slope after the break is negative and at least SLOPE_RATIO_MIN x steeper than before
Anything else is reported as not detected. Callers add context checks (e.g. seasonality).
"""
from __future__ import annotations

import numpy as np

DELTA_BIC_MIN = 10.0
SLOPE_RATIO_MIN = 2.0


def _ols_rss(X, y):
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ coef
    return coef, float(r @ r)


def two_segment_fit(x, y, min_side: int = 4) -> dict:
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = x.size
    out = {"n": n, "candidate": False}
    if n < 2 * min_side + 1:
        out["reason"] = f"점 {n}개 < {2 * min_side + 1}개"
        return out
    X1 = np.column_stack([np.ones(n), x])
    c1, rss1 = _ols_rss(X1, y)
    best = None
    for xb in x[min_side - 1:n - min_side]:
        X2 = np.column_stack([np.ones(n), x, np.clip(x - xb, 0, None)])
        c2, rss2 = _ols_rss(X2, y)
        if best is None or rss2 < best[2]:
            best = (xb, c2, rss2)
    xb, c2, rss2 = best
    eps = 1e-12
    bic1 = n * np.log(rss1 / n + eps) + 2 * np.log(n)
    bic2 = n * np.log(rss2 / n + eps) + 4 * np.log(n)
    s_before, s_after = c2[1], c2[1] + c2[2]
    out.update({"slope_line": c1[1], "intercept_line": c1[0], "break_x": float(xb),
                "slope_before": float(s_before), "slope_after": float(s_after),
                "coef_two_segment": c2.tolist(), "delta_bic": float(bic1 - bic2)})
    steeper = s_after < 0 and (s_before >= 0 or s_after <= SLOPE_RATIO_MIN * s_before)
    out["candidate"] = bool(out["delta_bic"] >= DELTA_BIC_MIN and steeper)
    if not out["candidate"]:
        out["reason"] = ("ΔBIC 부족" if out["delta_bic"] < DELTA_BIC_MIN else "") + \
                        ("" if steeper else (" / " if out["delta_bic"] < DELTA_BIC_MIN else "") + "기울기 가속 조건 불충족")
    return out
