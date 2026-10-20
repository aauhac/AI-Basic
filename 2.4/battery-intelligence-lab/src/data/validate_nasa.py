"""Open every NASA .mat file and verify its actual structure and values.

Writes:
  data/processed/nasa_discharge_capacity.csv   one row per discharge cycle (measured values only)
  results/validation/nasa_summary.csv          one row per battery
  results/validation/nasa_validation.json      field inventory and anomaly counts

Usage: .venv/Scripts/python -m src.data.validate_nasa
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from src.data.nasa import NASA_RAW, PRIORITY, RATED_CAPACITY_AH, find_mat_files, load_battery, discharge_table

ROOT = NASA_RAW.parents[2]
OUT_VAL = ROOT / "results" / "validation"
OUT_PROC = ROOT / "data" / "processed"


def main() -> None:
    OUT_VAL.mkdir(parents=True, exist_ok=True)
    OUT_PROC.mkdir(parents=True, exist_ok=True)
    files = find_mat_files()
    print(f"found {len(files)} .mat files; priority present: "
          + ", ".join(f"{b}={'Y' if b in files else 'N'}" for b in PRIORITY))

    field_sets: dict[str, Counter] = defaultdict(Counter)
    report = {"batteries": {}}
    summaries, tables = [], []

    for bid, path in files.items():
        cycles = load_battery(path)
        types = Counter(c.type for c in cycles)
        for c in cycles:
            field_sets[c.type][tuple(sorted(c.data))] += 1

        # numeric sanity on every array of every cycle
        nan_arrays = inf_arrays = empty_arrays = 0
        nonmono_time = 0
        length_mismatch = 0
        for c in cycles:
            for name, arr in c.data.items():
                if arr.size == 0:
                    empty_arrays += 1
                    continue
                if np.iscomplexobj(arr):
                    vals = np.concatenate([arr.real, arr.imag])
                else:
                    vals = arr.astype(float, copy=False)
                nan_arrays += int(np.isnan(vals).any())
                inf_arrays += int(np.isinf(vals).any())
            if c.type in ("charge", "discharge"):
                t = c.data.get("Time")
                if t is not None and t.size > 1 and np.any(np.diff(t) < 0):
                    nonmono_time += 1
                lens = {k: v.size for k, v in c.data.items() if k != "Capacity"}
                if len(set(lens.values())) > 1:
                    length_mismatch += 1

        starts = [c.start_time for c in cycles]
        valid = [s for s in starts if s is not None]
        start_nonmono = sum(1 for a, b in zip(valid, valid[1:]) if b < a)

        df = discharge_table(bid, cycles)
        tables.append(df)
        cap = df["capacity_ah"] if not df.empty else pd.Series(dtype=float)
        caps = cap.dropna()
        summaries.append({
            "battery": bid,
            "folder": path.parent.name,
            "n_cycles_total": len(cycles),
            "n_charge": types.get("charge", 0),
            "n_discharge": types.get("discharge", 0),
            "n_impedance": types.get("impedance", 0),
            "ambient_temps": ";".join(f"{t:g}" for t in sorted({c.ambient_temperature for c in cycles})),
            "first_start": min(valid) if valid else None,
            "last_start": max(valid) if valid else None,
            "cap_first_ah": caps.iloc[0] if len(caps) else np.nan,
            "cap_last_ah": caps.iloc[-1] if len(caps) else np.nan,
            "cap_min_ah": caps.min() if len(caps) else np.nan,
            "cap_max_ah": caps.max() if len(caps) else np.nan,
            "cap_missing": int(cap.isna().sum()),
            "cap_le_0": int((caps <= 0).sum()),
            "cap_gt_rated": int((caps > RATED_CAPACITY_AH).sum()),
            "cap_below_1_0": int((caps < 1.0).sum()),
            "reaches_1_4ah": bool((caps <= 1.4).any()),
            "reaches_1_6ah": bool((caps <= 1.6).any()),
            "arrays_with_nan": nan_arrays,
            "arrays_with_inf": inf_arrays,
            "empty_arrays": empty_arrays,
            "time_nonmonotonic_cycles": nonmono_time,
            "field_length_mismatch_cycles": length_mismatch,
            "start_time_missing": len(starts) - len(valid),
            "start_time_backwards": start_nonmono,
        })

    summary = pd.DataFrame(summaries)
    summary.to_csv(OUT_VAL / "nasa_summary.csv", index=False)
    pd.concat(tables, ignore_index=True).to_csv(OUT_PROC / "nasa_discharge_capacity.csv", index=False)

    report["field_sets"] = {t: [{"fields": list(k), "count": n} for k, n in c.most_common()]
                            for t, c in field_sets.items()}
    report["batteries"] = summary.to_dict(orient="records")
    (OUT_VAL / "nasa_validation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    pd.set_option("display.width", 250, "display.max_columns", 40)
    print(summary.drop(columns=["folder"]).to_string(index=False))
    print("\nfield sets by cycle type:")
    for t, c in field_sets.items():
        for k, n in c.most_common():
            print(f"  {t:10s} x{n:4d}: {', '.join(k)}")


if __name__ == "__main__":
    main()
