"""Charge-curve features of EV10 packs that are comparable with NASA cells.

Only a narrow voltage window of the mean-cell-voltage curve is used. The SOH label of
BatPackdata equals (total charged Ah over the full 0-100 % charge) / Cn, so any feature
built from the whole charge would reconstruct the label; `MAX_LABEL_FRACTION` caps how much
of the total charge a window may cover.
"""
from __future__ import annotations

import numpy as np

from src.features.nasa_features import window_charge

MAX_LABEL_FRACTION = 0.5


def concat_curve(pack: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Mean-cell voltage, Ah increment, current and segment id per sample (segments in file order).
    The increment of sample j is Q[j] - Q[j-1] within the same segment (Q restarts per segment)."""
    v, dq, cur, seg = [], [], [], []
    for k, s in enumerate(pack["data"]["Inf"]):
        q = s["Q"]
        v.append(s["Vmean"][1:])
        dq.append(np.diff(q))
        cur.append(s["I_load"][1:])
        seg.append(np.full(q.size - 1, k))
    return np.concatenate(v), np.concatenate(dq), np.concatenate(cur), np.concatenate(seg)


def window_features(pack: dict, v1: float, v2: float) -> dict:
    v, dq, cur, seg = concat_curve(pack)
    total = float(sum(s["Q"][-1] for s in pack["data"]["Inf"]))
    q = window_charge(v, dq, v1, v2)
    m = (v >= v1) & (v < v2) & (dq > 0)
    frac = q / total if np.isfinite(q) else np.nan
    if np.isfinite(frac) and frac >= MAX_LABEL_FRACTION:
        raise ValueError(f"window {v1}-{v2} V covers {frac:.0%} of the label-defining charge")
    return {
        "q_win_ah": q,
        "q_win_norm": q / pack["Cn"] if np.isfinite(q) else np.nan,
        "window_fraction_of_total_q": frac,
        "segments_in_window": int(np.unique(seg[m]).size) if m.any() else 0,
        "c_rate_in_window": float(np.sum(np.abs(cur[m]) * dq[m]) / np.sum(dq[m]) / pack["Cn"]) if m.any() else np.nan,
        "v_min": float(v.min()), "v_max": float(v.max()),
    }


def charge_weighted_c_rate(pack: dict) -> float:
    v, dq, cur, _ = concat_curve(pack)
    m = dq > 0
    return float(np.sum(np.abs(cur[m]) * dq[m]) / np.sum(dq[m]) / pack["Cn"])
