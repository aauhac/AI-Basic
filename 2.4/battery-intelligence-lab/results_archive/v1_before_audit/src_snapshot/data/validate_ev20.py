"""Open every EV20 CSV and verify columns, time order, gaps, missing/abnormal values, and
whether a capacity series can be extracted.

Writes:
  results/validation/ev20_summary.csv          one row per vehicle
  data/processed/ev20_session_capacity.csv     one row per charging session (computed, no fill)
Usage: .venv/Scripts/python -m src.data.validate_ev20
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.ev20 import NOMINAL_CAPACITY_AH, ROOT, load_vehicle, session_capacity, split_sessions, vehicle_files

OUT_VAL = ROOT / "results" / "validation"
OUT_PROC = ROOT / "data" / "processed"

# physically plausible bounds used only to count abnormal values (nothing is removed)
BOUNDS = {"soc": (0, 100), "pack_voltage": (200, 400), "charge_current": (-400, 50),
          "max_cell_voltage": (2.5, 4.35), "min_cell_voltage": (2.5, 4.35),
          "max_temperature": (-30, 70), "min_temperature": (-30, 70),
          "available_energy": (0, 60), "available_capacity": (0, 160)}


def main() -> None:
    OUT_VAL.mkdir(parents=True, exist_ok=True)
    OUT_PROC.mkdir(parents=True, exist_ok=True)
    files = vehicle_files()
    print(f"found {len(files)} vehicle CSVs: {sorted(files)}  missing: {sorted(set(range(1, 21)) - set(files))}")
    summaries, sessions_all = [], []
    for vid, path in files.items():
        df = load_vehicle(path)
        dt = df["record_time"].diff().dt.total_seconds()
        row = {
            "vehicle": vid, "rows": len(df),
            "first": df["record_time"].min(), "last": df["record_time"].max(),
            "span_days": (df["record_time"].max() - df["record_time"].min()).days,
            "time_sorted": bool((dt.dropna() >= 0).all()),
            "dup_timestamps": int(df["record_time"].duplicated().sum()),
            "median_dt_s": float(dt.median()),
            "nan_total": int(df.drop(columns="number").isna().sum().sum()),
            "nan_cols": ";".join(f"{c}={n}" for c, n in df.isna().sum().items() if n),
            "current_pos_rows": int((df["charge_current"] > 0).sum()),
            "cellV_max_lt_min": int((df["max_cell_voltage"] < df["min_cell_voltage"]).sum()),
            "temp_max_lt_min": int((df["max_temperature"] < df["min_temperature"]).sum()),
        }
        for c, (lo, hi) in BOUNDS.items():
            row[f"out_{c}"] = int(((df[c] < lo) | (df[c] > hi)).sum())
        # BMS-reported full capacity implied by available_capacity / SOC (only where SOC >= 50 %)
        m = df["soc"] >= 50
        row["bms_full_cap_median"] = float((df.loc[m, "available_capacity"] / df.loc[m, "soc"] * 100).median())

        sess = split_sessions(df)
        caps = pd.DataFrame([session_capacity(s) for s in sess])
        caps.insert(0, "vehicle", vid)
        sessions_all.append(caps)
        clean = caps[~caps["soc_jump_gt2"] & ~caps["soc_drop_lt_neg0_1"] & caps["capacity_ah"].notna()]
        wide = clean[clean["delta_soc"] >= 30]
        row.update({
            "sessions": len(caps), "sessions_paper_filter": len(clean), "sessions_dsoc_ge30": len(wide),
            "cap_median_dsoc30": float(wide["capacity_ah"].median()) if len(wide) else np.nan,
            "cap_first3m_dsoc30": float(wide[wide["start"] < wide["start"].min() + pd.Timedelta(days=90)]["capacity_ah"].median()) if len(wide) else np.nan,
            "cap_last3m_dsoc30": float(wide[wide["start"] > wide["start"].max() - pd.Timedelta(days=90)]["capacity_ah"].median()) if len(wide) else np.nan,
        })
        summaries.append(row)
        print(f"#{vid:2d}: rows={len(df):7d}  {row['first']:%Y-%m-%d}..{row['last']:%Y-%m-%d}  sessions={len(caps)} "
              f"clean={len(clean)} dsoc>=30={len(wide)}  cap(first3m->last3m)={row['cap_first3m_dsoc30']:.1f}->{row['cap_last3m_dsoc30']:.1f} Ah")

    summary = pd.DataFrame(summaries)
    summary["fade_pct_first_to_last3m"] = (1 - summary["cap_last3m_dsoc30"] / summary["cap_first3m_dsoc30"]) * 100
    summary["soh_last3m_vs_nominal"] = summary["cap_last3m_dsoc30"] / NOMINAL_CAPACITY_AH
    summary.to_csv(OUT_VAL / "ev20_summary.csv", index=False)
    pd.concat(sessions_all, ignore_index=True).to_csv(OUT_PROC / "ev20_session_capacity.csv", index=False)
    pd.set_option("display.width", 300, "display.max_columns", 60)
    print()
    print(summary.drop(columns=["first", "last"]).to_string(index=False))


if __name__ == "__main__":
    main()
