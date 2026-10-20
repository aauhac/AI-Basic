"""Loader for the 20 on-road EV charging logs (Deng et al., Applied Energy 2023, 339:120954).

Each data/raw/ev_20/#N.csv (extracted from external/.../#N.rar) contains BMS charging records:
record_time (yyyymmddHHMMSS), soc (%), pack voltage, charge current (negative = charging),
max/min cell voltage, max/min temperature, available energy (kWh) and available capacity (Ah).
Pack: BAIC EU500, CATL NCM, 90 cells in series, nominal 145 Ah (per repository README).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EV20_RAW = ROOT / "data" / "raw" / "ev_20"
NOMINAL_CAPACITY_AH = 145.0

COLUMNS = ["number", "record_time", "soc", "pack_voltage", "charge_current", "max_cell_voltage",
           "min_cell_voltage", "max_temperature", "min_temperature", "available_energy",
           "available_capacity"]


def vehicle_files(root: Path = EV20_RAW) -> dict[int, Path]:
    files = {int(p.stem.lstrip("#")): p for p in root.glob("#*.csv")}
    return dict(sorted(files.items()))


def load_vehicle(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, header=0)
    if len(df.columns) != len(COLUMNS):
        raise ValueError(f"{path.name}: expected {len(COLUMNS)} columns, got {list(df.columns)}")
    df.columns = COLUMNS
    df["record_time"] = pd.to_datetime(df["record_time"].astype("int64").astype(str), format="%Y%m%d%H%M%S")
    return df


def drop_exact_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Remove rows identical in every measured column (the CSV index column is ignored).
    Rows sharing a timestamp but differing in value are kept and counted."""
    cols = [c for c in df.columns if c != "number"]
    dup = df.duplicated(subset=cols, keep="first")
    out = df[~dup]
    conflict = int(out["record_time"].duplicated(keep=False).sum())
    return out.reset_index(drop=True), {"rows_in": len(df), "exact_duplicates_removed": int(dup.sum()),
                                        "rows_sharing_timestamp_with_different_values": conflict}


def split_sessions(df: pd.DataFrame, gap_s: float = 10.0, min_rows: int = 100) -> list[pd.DataFrame]:
    """Split into charging sessions where consecutive records are more than gap_s apart.

    Mirrors the segmentation in the repository's capacity_extract.py (10 s gap, >=100 rows).
    """
    df = df.sort_values("record_time", kind="stable").reset_index(drop=True)
    breaks = np.flatnonzero(df["record_time"].diff().dt.total_seconds().to_numpy() > gap_s)
    bounds = np.concatenate([[0], breaks, [len(df)]])
    return [df.iloc[a:b].reset_index(drop=True) for a, b in zip(bounds[:-1], bounds[1:]) if b - a >= min_rows]


def session_capacity(s: pd.DataFrame) -> dict:
    """Capacity estimate = integrated charge (Ah) / delta SOC, as in capacity_extract.py.

    Missing current values are counted, not filled; sessions with >10 % missing current or
    a non-positive SOC change return capacity NaN.
    """
    t = (s["record_time"] - s["record_time"].iloc[0]).dt.total_seconds().to_numpy()
    i = s["charge_current"].to_numpy(dtype=float)
    soc = s["soc"].to_numpy(dtype=float)
    dsoc_steps = np.diff(soc)
    n_nan = int(np.isnan(i).sum())
    d_soc = soc[-1] - soc[0]
    ok = n_nan <= 0.1 * len(i) and d_soc > 0
    q_ah = -np.trapezoid(np.nan_to_num(i), t) / 3600 if ok and n_nan == 0 else np.nan
    return {
        "start": s["record_time"].iloc[0], "end": s["record_time"].iloc[-1], "rows": len(s),
        "soc_start": soc[0], "soc_end": soc[-1], "delta_soc": d_soc,
        "charge_ah": q_ah,
        "throughput_ah": float(-np.trapezoid(np.nan_to_num(i), t) / 3600) if len(t) > 1 else 0.0,
        "capacity_ah": q_ah / d_soc * 100 if ok and n_nan == 0 else np.nan,
        "soc_jump_gt2": bool((dsoc_steps > 2).any()), "soc_drop_lt_neg0_1": bool((dsoc_steps < -0.1).any()),
        "current_nan": n_nan,
        "current_pos": int((i > 0).sum()),
        "mean_current": float(np.nanmean(i)),
        "duration_min": float(t[-1] / 60),
        "t_max_mean": float(s["max_temperature"].mean()), "t_min_mean": float(s["min_temperature"].mean()),
    }
