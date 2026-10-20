"""Loader for the NASA PCoE Li-ion battery aging .mat files (B0005 ... B0056).

Each file holds one MATLAB struct named after the battery (e.g. ``B0005``) with a single
field ``cycle``: a 1xN struct array whose elements have ``type`` ('charge' | 'discharge' |
'impedance'), ``ambient_temperature``, ``time`` (MATLAB date vector) and ``data``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.io import loadmat

NASA_RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "nasa"
RATED_CAPACITY_AH = 2.0  # stated in every NASA README (EOL = 1.4 Ah = 30 % fade, or 1.6 Ah = 20 %)
PRIORITY = ("B0005", "B0006", "B0007", "B0018")


@dataclass
class Cycle:
    index: int          # position in the original cycle array (0-based)
    type: str
    ambient_temperature: float
    start_time: datetime | None
    data: dict[str, np.ndarray]


def find_mat_files(root: Path = NASA_RAW) -> dict[str, Path]:
    """Map battery id -> .mat path (one path per id; duplicates were removed at extraction)."""
    return {p.stem: p for p in sorted(root.rglob("B*.mat"))}


def _datevec_to_datetime(vec) -> datetime | None:
    v = np.asarray(vec, dtype=float).ravel()
    if v.size != 6 or not np.all(np.isfinite(v)):
        return None
    y, mo, d, h, mi, s = v
    return datetime(int(y), int(mo), int(d), int(h), int(mi)) + timedelta(seconds=float(s))


def load_battery(path: Path) -> list[Cycle]:
    mat = loadmat(path, squeeze_me=True, struct_as_record=False)
    key = path.stem
    cycles = np.atleast_1d(mat[key].cycle)
    out = []
    for i, c in enumerate(cycles):
        d = c.data
        fields = {name: np.atleast_1d(np.asarray(getattr(d, name))) for name in d._fieldnames}
        out.append(Cycle(i, str(c.type).strip(), float(c.ambient_temperature),
                         _datevec_to_datetime(c.time), fields))
    return out


def discharge_table(battery_id: str, cycles: list[Cycle]) -> pd.DataFrame:
    """One row per discharge cycle with the measured Capacity field (no imputation)."""
    rows = []
    n = 0
    for c in cycles:
        if c.type != "discharge":
            continue
        n += 1
        cap = c.data.get("Capacity")
        t = c.data.get("Time")
        v = c.data.get("Voltage_measured")
        temp = c.data.get("Temperature_measured")
        rows.append({
            "battery": battery_id,
            "discharge_no": n,
            "cycle_index": c.index,
            "start_time": c.start_time,
            "ambient_temperature": c.ambient_temperature,
            "capacity_ah": float(cap[0]) if cap is not None and cap.size else np.nan,
            "n_samples": int(t.size) if t is not None else 0,
            "duration_s": float(t[-1] - t[0]) if t is not None and t.size > 1 else np.nan,
            "v_min": float(np.nanmin(v)) if v is not None and v.size else np.nan,
            "temp_max": float(np.nanmax(temp)) if temp is not None and temp.size else np.nan,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["soh_rated"] = df["capacity_ah"] / RATED_CAPACITY_AH
        first = df["capacity_ah"].dropna()
        df["soh_initial"] = df["capacity_ah"] / first.iloc[0] if len(first) else np.nan
    return df
