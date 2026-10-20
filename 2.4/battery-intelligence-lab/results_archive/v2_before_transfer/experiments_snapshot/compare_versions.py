"""Compare pre-audit results (results_archive/v1_before_audit/results) with the current run.

Writes results/audit/before_after_<table>.csv (one row per key, v1/v2 values and delta) and
results/audit/before_after_summary.csv. Single models were not changed by the audit, so their
deltas are expected to be 0 and serve as a reproducibility check.

Usage: .venv/Scripts/python -m experiments.compare_versions
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "results_archive" / "v1_before_audit" / "results"
V2 = ROOT / "results"
OUT = V2 / "audit"

TABLES = [  # (name, relative path, keys, v1 value column, v2 value column)
    ("exp_A", "nasa/exp_A_split_comparison.csv", ["split", "model"], "MAE", "MAE"),
    ("exp_B", "nasa/exp_B_small_data.csv", ["n_train_per_battery", "model"], "MAE", "MAE"),
    ("exp_C", "nasa/exp_C_lobo.csv", ["held_out", "model"], "MAE", "MAE"),
    ("exp_E", "nasa/exp_E_feature_sets.csv", ["validation", "feature_set", "model"], "MAE", "MAE"),
    ("supp_soh_rated", "nasa/supp_soh_rated_target.csv", ["validation", "held_out", "model"], "MAE", "MAE"),
    ("future_soh", "nasa/future_soh.csv", ["horizon", "validation", "model"], "MAE", "MAE"),
    ("rul", "nasa/rul_results.csv", ["battery", "method"], "MAE", "MAE_success_only"),
    ("ev10", "ev10/ev10_external_eval.csv", ["window", "case", "model"], "MAE", "MAE"),
    ("ev20_trend", "ev20/ev20_vehicle_trend.csv", ["vehicle"], "slope_ah_per_month", "slope_ah_per_month"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, rel, keys, c1, c2 in TABLES:
        a, b = pd.read_csv(V1 / rel), pd.read_csv(V2 / rel)
        for k in keys:
            a[k], b[k] = a[k].astype(str), b[k].astype(str)
        a = a.groupby(keys, sort=False)[c1].mean().rename("v1").reset_index()
        b_cols = [c2] + (["success_rate", "n_fail_no_crossing"] if name == "rul" else [])
        b = b.groupby(keys, sort=False)[b_cols].mean().rename(columns={c2: "v2"}).reset_index()
        m = a.merge(b, on=keys, how="outer", indicator=True)
        m["delta"] = m["v2"] - m["v1"]
        m["changed"] = ~np.isclose(m["v1"], m["v2"], rtol=0, atol=1e-9, equal_nan=True)
        m["status"] = m["_merge"].map({"both": "both", "left_only": "v1 only (removed)", "right_only": "v2 only (new)"})
        m = m.drop(columns="_merge")
        m.to_csv(OUT / f"before_after_{name}.csv", index=False)
        model_col = "model" if "model" in keys else ("method" if "method" in keys else None)
        is_stack = m[model_col].str.contains("Stacking") if model_col else pd.Series(False, index=m.index)
        both = m["status"] == "both"
        summary.append({"table": name, "metric": f"{c1} → {c2}", "rows_v1": int((m["status"] != "v2 only (new)").sum()),
                        "rows_v2": int((m["status"] != "v1 only (removed)").sum()), "rows_changed": int((m["changed"] & both).sum()),
                        "changed_stacking_rows": int((m["changed"] & both & is_stack).sum()),
                        "changed_non_stacking_rows": int((m["changed"] & both & ~is_stack).sum()),
                        "max_abs_delta_non_stacking": float(m.loc[both & ~is_stack, "delta"].abs().max() or 0),
                        "rows_only_in_v1": int((m["status"] == "v1 only (removed)").sum()),
                        "rows_only_in_v2": int((m["status"] == "v2 only (new)").sum())})
    s = pd.DataFrame(summary)
    s.to_csv(OUT / "before_after_summary.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 20)
    print(s.to_string(index=False))


if __name__ == "__main__":
    main()
