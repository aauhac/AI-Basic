"""EOL / RUL definitions and a history-only extrapolation predictor.

EOL threshold: 1.4 Ah (30 % fade of the 2.0 Ah rating, per the NASA README for B0005/6/7/18).
EOL cycle = first discharge_no whose measured capacity <= threshold.
RUL at discharge k = EOL cycle - k (defined for k <= EOL only). A battery that never reaches
the threshold is right-censored: no RUL label exists, only the bound RUL(k) > last_no - k.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EOL_AH = 1.4


def eol_cycle(discharge_no, capacity, threshold: float = EOL_AH):
    discharge_no, capacity = np.asarray(discharge_no), np.asarray(capacity, float)
    hit = np.flatnonzero(capacity <= threshold)
    return int(discharge_no[hit[0]]) if hit.size else None


def add_rul(df: pd.DataFrame, threshold: float = EOL_AH) -> tuple[pd.DataFrame, dict]:
    """Adds eol_no, rul (NaN for censored batteries or rows after EOL) and censored flag."""
    df = df.copy()
    eols = {}
    df["rul"] = np.nan
    df["eol_no"] = np.nan
    for b, g in df.groupby("battery"):
        g = g.sort_values("discharge_no")
        e = eol_cycle(g["discharge_no"], g["capacity_ah"], threshold)
        eols[b] = e
        if e is not None:
            m = (df["battery"] == b) & (df["discharge_no"] <= e)
            df.loc[m, "rul"] = e - df.loc[m, "discharge_no"]
            df.loc[df["battery"] == b, "eol_no"] = e
    df["censored"] = df["battery"].map(lambda b: eols[b] is None)
    return df, eols


def extrapolate_rul(history_no, history_cap, threshold: float = EOL_AH, window: int | None = None,
                    horizon_max: int = 1000) -> float:
    """Fit a line to the observed capacity history (optionally only the last `window` points)
    and return cycles until the line reaches `threshold`, counted from the last observed cycle.
    Uses nothing but the history passed in. Returns inf ("no crossing") if the fitted line is
    not decreasing or would reach the threshold more than `horizon_max` cycles ahead."""
    x, y = np.asarray(history_no, float), np.asarray(history_cap, float)
    if window:
        x, y = x[-window:], y[-window:]
    if x.size < 3:
        return np.nan
    slope, intercept = np.polyfit(x, y, 1)
    k = x[-1]
    if slope >= -1e-12:  # flat within float error
        return np.inf
    crossing = (threshold - intercept) / slope
    rul = max(np.ceil(crossing - 1e-9) - k, 0.0)  # tolerance: float error must not add a cycle
    return float(rul) if rul <= horizon_max else np.inf
