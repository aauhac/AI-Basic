"""Per-discharge-cycle feature table for NASA cells.

One row per discharge cycle k of a battery. Every input feature is computed only from
operations that happened *before* discharge k started:
  - the charge cycle immediately preceding discharge k (charge group / charge_ah group),
  - the most recent impedance measurement before discharge k (impedance group),
  - capacities of discharges 1..k-1 (history group),
  - the discharge counter k itself (cycle group).
The discharge k curve is never used as input: its duration x current reconstructs the
capacity label.

Targets: capacity_ah (measured), soh_init = C_k / C_1, soh_rated = C_k / 2.0 Ah.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.data.nasa import RATED_CAPACITY_AH, Cycle, find_mat_files, load_battery

CC_ON_A = 1.0          # charge current above this marks the start of CC charging
CV_V = 4.195           # terminal voltage treated as reaching the 4.2 V CV setpoint
CHARGE_END_A = 0.05    # current below this after CV is treated as end of charge
MIN_CHARGE_AH = 1.0    # charges delivering less than this are incomplete (invalid)
IMP_RANGE_OHM = (0.0, 1.0)

FEATURE_GROUPS = {
    "charge": ["chg_cc_time_s", "chg_cv_time_s", "chg_v_start", "chg_t_390_410_s",
               "chg_temp_mean", "chg_temp_max", "chg_temp_rise", "chg_ic_peak", "chg_ic_peak_v"],
    "charge_ah": ["chg_cc_ah", "chg_total_ah"],
    "impedance": ["imp_re", "imp_rct"],
    "cycle": ["discharge_no"],
    "history": ["soh_lag1", "soh_lag2", "soh_roll3", "soh_slope5"],
}
# voltage windows (V) whose charged Ah is used for the NASA -> EV10 comparison only
TRANSFER_WINDOWS = [(3.90, 4.00), (3.95, 4.05)]


def window_col(v1: float, v2: float) -> str:
    return f"q_win_{int(round(v1 * 100))}_{int(round(v2 * 100))}_ah"


def window_charge(v: np.ndarray, dq: np.ndarray, v1: float, v2: float) -> float:
    """Ah charged while voltage was in [v1, v2). NaN unless the curve spans the whole window."""
    if v.size == 0 or np.nanmin(v) > v1 or np.nanmax(v) < v2:
        return np.nan
    m = (v >= v1) & (v < v2) & (dq > 0)
    return float(dq[m].sum())


@dataclass
class Log:
    counts: dict = field(default_factory=dict)

    def add(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + int(n)


def charge_features(c: Cycle, log: Log) -> dict:
    v, i, t, temp = (c.data[k] for k in ("Voltage_measured", "Current_measured", "Time", "Temperature_measured"))
    finite = np.isfinite(v) & np.isfinite(i) & np.isfinite(t) & np.isfinite(temp)
    log.add("charge_samples_total", v.size)
    log.add("charge_samples_nonfinite_dropped", int((~finite).sum()))
    v, i, t, temp = v[finite], i[finite], t[finite], temp[finite]
    out = {k: np.nan for k in FEATURE_GROUPS["charge"] + FEATURE_GROUPS["charge_ah"]}
    out.update({window_col(a, b): np.nan for a, b in TRANSFER_WINDOWS})
    on_idx = np.flatnonzero(i > CC_ON_A)
    if t.size < 10 or on_idx.size == 0:
        log.add("charge_invalid_no_cc")
        return out
    on = on_idx[0]
    reach_idx = np.flatnonzero(v[on:] >= CV_V)
    if reach_idx.size == 0:
        log.add("charge_invalid_no_cv")
        return out
    reach = on + reach_idx[0]
    total_ah = np.trapezoid(np.clip(i, 0, None), t) / 3600
    if total_ah < MIN_CHARGE_AH:
        log.add("charge_invalid_low_ah")
        return out
    after = np.flatnonzero(i[reach:] >= CHARGE_END_A)
    end = reach + (after[-1] if after.size else 0)
    dt = np.diff(t)
    dq = np.concatenate([[0.0], i[1:] * dt / 3600])  # Ah delivered in the interval ending at each sample
    cc = slice(on, reach + 1)
    k10 = on + np.searchsorted(t[on:] - t[on], 10.0)
    t390 = np.flatnonzero(v[on:reach + 1] >= 3.90)
    t410 = np.flatnonzero(v[on:reach + 1] >= 4.10)
    # incremental capacity dQ/dV over the CC phase, 10 mV bins between 3.90 and 4.20 V
    bins = np.arange(3.90, 4.2001, 0.01)
    hist, _ = np.histogram(v[cc], bins=bins, weights=np.clip(dq[cc], 0, None))
    ic = hist / 0.01
    out.update({
        "chg_cc_time_s": t[reach] - t[on],
        "chg_cv_time_s": max(t[end] - t[reach], 0.0),
        "chg_v_start": v[min(k10, v.size - 1)],
        "chg_t_390_410_s": (t[on + t410[0]] - t[on + t390[0]]) if t390.size and t410.size and v[on] < 3.90 else np.nan,
        "chg_temp_mean": temp[on:end + 1].mean(),
        "chg_temp_max": temp[on:end + 1].max(),
        "chg_temp_rise": temp[on:end + 1].max() - temp[on],
        "chg_ic_peak": ic.max(),
        "chg_ic_peak_v": bins[np.argmax(ic)] + 0.005,
        "chg_cc_ah": float(dq[on + 1:reach + 1].sum()),
        "chg_total_ah": total_ah,
    })
    for a, b in TRANSFER_WINDOWS:
        out[window_col(a, b)] = window_charge(v[cc], dq[cc], a, b)
    log.add("charge_valid")
    return out


def build_table(battery_id: str, cycles: list[Cycle], log: Log | None = None) -> pd.DataFrame:
    """Feature/target table for one battery from its (possibly truncated) cycle list."""
    log = log or Log()
    rows = []
    last_charge: Cycle | None = None
    last_imp: tuple[float, float] | None = None
    n_dis = 0
    for c in cycles:
        if c.type == "charge":
            last_charge = c
        elif c.type == "impedance":
            re, rct = float(c.data["Re"][0]), float(c.data["Rct"][0])
            lo, hi = IMP_RANGE_OHM
            if np.isfinite(re) and np.isfinite(rct) and lo < re < hi and lo < rct < hi:
                last_imp = (re, rct)
            else:
                log.add("impedance_invalid_skipped")
        elif c.type == "discharge":
            n_dis += 1
            cap = c.data.get("Capacity")
            cap = float(cap[0]) if cap is not None and cap.size else np.nan
            row = {"battery": battery_id, "discharge_no": n_dis, "cycle_index": c.index,
                   "start_time": c.start_time, "capacity_ah": cap}
            if last_charge is not None:
                row.update(charge_features(last_charge, log))
            else:
                log.add("discharge_without_preceding_charge")
            row["imp_re"], row["imp_rct"] = last_imp if last_imp else (np.nan, np.nan)
            if last_imp is None:
                log.add("discharge_without_prior_impedance")
            rows.append(row)
            last_charge = None  # a charge feeds only the discharge right after it
    df = pd.DataFrame(rows)
    bad = ~(df["capacity_ah"] > 0)
    log.add("discharge_rows_total", len(df))
    log.add("discharge_rows_dropped_capacity_le0_or_nan", int(bad.sum()))
    df = df[~bad].reset_index(drop=True)
    first = df["capacity_ah"].iloc[0]
    df["soh_init"] = df["capacity_ah"] / first
    df["soh_rated"] = df["capacity_ah"] / RATED_CAPACITY_AH
    prev = df["soh_init"].shift(1)
    df["soh_lag1"] = prev
    df["soh_lag2"] = df["soh_init"].shift(2)
    df["soh_roll3"] = prev.rolling(3, min_periods=3).mean()
    df["soh_slope5"] = prev.rolling(5, min_periods=5).apply(lambda y: np.polyfit(np.arange(5), y, 1)[0], raw=True)
    return df


def build_nasa_table(batteries=("B0005", "B0006", "B0007", "B0018")) -> tuple[pd.DataFrame, dict]:
    files = find_mat_files()
    logs, frames = {}, []
    for b in batteries:
        log = Log()
        frames.append(build_table(b, load_battery(files[b]), log))
        logs[b] = log.counts
    return pd.concat(frames, ignore_index=True), logs


def feature_list(*groups: str) -> list[str]:
    return [c for g in groups for c in FEATURE_GROUPS[g]]
