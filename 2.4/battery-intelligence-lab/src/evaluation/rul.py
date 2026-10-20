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


def rul_summary(pred: pd.DataFrame, eols: dict, last_obs: dict, penalty: float = 1000.0) -> pd.DataFrame:
    """Per (battery, method) RUL scores with failures reported, never silently dropped.

    A prediction "fails" when it is not finite (no EOL crossing within the horizon).
      success_rate        finite predictions / origins
      MAE_success_only    MAE over finite predictions (as in the pre-audit table)
      MAE_fail_penalized  MAE with failures counted as RUL = penalty
      MAE_common          MAE over the origins where every method of that battery succeeded
    Censored batteries get only the observation-consistency check (pred EOL <= last observed).
    """
    rows = []
    for b, gb in pred.groupby("battery", sort=False):
        ok = gb.assign(fin=np.isfinite(gb["rul_pred"])).groupby("origin_no")["fin"].all()
        common = set(ok.index[ok])
        for method, g in gb.groupby("method", sort=False):
            fin = np.isfinite(g["rul_pred"]).to_numpy()
            base = {"battery": b, "method": method, "n_origins": len(g), "n_success": int(fin.sum()),
                    "n_fail_no_crossing": int((~fin).sum()), "success_rate": float(fin.mean()),
                    "n_negative_pred": int((g["rul_pred"] < 0).sum())}
            if eols.get(b) is not None:
                e = eols[b]
                s = g[fin]
                pen = np.where(fin, g["rul_pred"], penalty)
                gc = g[g["origin_no"].isin(common)]
                at = {}
                for frac in (0.25, 0.5, 0.75):
                    k = max(20, int(round(e * frac)))
                    gk = g[g["origin_no"] == k]
                    at[f"abs_err_at_{int(frac * 100)}pct_life"] = float(abs(gk["rul_pred"] - gk["rul_true"]).iloc[0]) if len(gk) else np.nan
                rows.append({**base, "status": "EOL observed", "eol_true": e,
                             "MAE_success_only": float(np.mean(np.abs(s["rul_pred"] - s["rul_true"]))) if len(s) else np.nan,
                             "RMSE_success_only": float(np.sqrt(np.mean((s["rul_pred"] - s["rul_true"]) ** 2))) if len(s) else np.nan,
                             "MAE_fail_penalized": float(np.mean(np.abs(pen - g["rul_true"]))),
                             "n_common_origins": len(gc),
                             "MAE_common": float(np.mean(np.abs(gc["rul_pred"] - gc["rul_true"]))) if len(gc) else np.nan, **at})
            else:
                eol_pred = g["origin_no"] + g["rul_pred"]
                contradicted = int((np.isfinite(eol_pred) & (eol_pred <= last_obs[b])).sum())
                rows.append({**base, "status": f"censored (no EOL by #{last_obs[b]})", "eol_true": np.nan,
                             "pred_eol_le_last_observed": contradicted, "share_contradicted": contradicted / len(g)})
    return pd.DataFrame(rows)


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
