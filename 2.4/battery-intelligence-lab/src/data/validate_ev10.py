"""Open BatPackdata.mat and verify its structure, labels and README claims.

Writes results/validation/ev10_summary.csv and ev10_segments.csv.
Usage: .venv/Scripts/python -m src.data.validate_ev10
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.ev10 import EV10_MAT, ROOT, load_ev10

OUT = ROOT / "results" / "validation"

# Values printed in the repository README table (vehicle, rated Ah, cells, SOH %)
README_TABLE = {1: (234, 96, 94.30), 2: (174, 104, 93.85), 3: (100, 84, 78.91), 4: (115, 100, 87.77),
                5: (174, 96, 82.21), 6: (100, 88, 92.87), 7: (110, 90, 96.98), 8: (152, 108, 90.81),
                9: (150, 84, 101.71), 10: (100, 90, 99.08)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    packs = load_ev10()
    rows, segs = [], []
    for p in packs:
        veh = int(p["Veh"])
        inf, soc_ranges = p["data"]["Inf"], p["data"]["SOC"]
        q_total = 0.0
        dt_ratio = []
        for j, (seg, rng) in enumerate(zip(inf, soc_ranges)):
            i, q = seg["I_load"], seg["Q"]
            lens = {k: v.size for k, v in seg.items()}
            # Q is cumulative Ah within a segment; dQ*3600/|I| gives the implied sample period (s)
            dq = np.diff(q)
            mask = np.abs(i[1:]) > 1
            if mask.any():
                dt_ratio.append(np.median(dq[mask] * 3600 / np.abs(i[1:][mask])))
            q_total += float(q[-1])
            lo, hi = (float(x) for x in rng.split("-"))
            segs.append({"veh": veh, "segment": j, "soc_range": rng, "soc_lo": lo, "soc_hi": hi,
                         "n": lens["Q"], "lengths_equal": len(set(lens.values())) == 1,
                         "q_end_ah": float(q[-1]), "q_monotonic": bool(np.all(dq >= -1e-3)),
                         "i_min": float(i.min()), "i_max": float(i.max()), "i_pos_count": int((i > 0).sum()),
                         "vmax_min": float(seg["Vmax"].min()), "vmax_max": float(seg["Vmax"].max()),
                         "vmax_ge_vmean": bool(np.all(seg["Vmax"] >= seg["Vmean"] - 1e-6)),
                         "nan": int(sum(np.isnan(v).sum() for v in seg.values()))})
        soc_lo = min(float(r.split("-")[0]) for r in soc_ranges)
        soc_hi = max(float(r.split("-")[1]) for r in soc_ranges)
        rc, nc, sohp = README_TABLE[veh]
        rows.append({
            "veh": veh, "type": p["Type"], "Cn_file": p["Cn"], "Cn_readme": rc,
            "Ncell_file": p["Ncell"], "Ncell_readme": nc,
            "SOH_file_pct": round(p["SOH"] * 100, 2), "SOH_readme_pct": sohp,
            "n_segments": len(inf), "n_samples": sum(s["Q"].size for s in inf),
            "soc_covered": f"{soc_lo:g}-{soc_hi:g}",
            "sum_Q_ah": round(q_total, 3), "sum_Q_over_Cn": round(q_total / p["Cn"], 5),
            "implied_dt_s": round(float(np.median(dt_ratio)), 3) if dt_ratio else np.nan,
            "soc_ocv_points": p["SOC_OCV"].shape[0],
        })
    df = pd.DataFrame(rows)
    df["SOH_matches_readme"] = (df["SOH_file_pct"] - df["SOH_readme_pct"]).abs() < 0.01
    df["Cn_matches_readme"] = df["Cn_file"] == df["Cn_readme"]
    df["SOH_eq_sumQ_over_Cn"] = (df["SOH_file_pct"] / 100 - df["sum_Q_over_Cn"]).abs() < 1e-3
    df.to_csv(OUT / "ev10_summary.csv", index=False)
    seg_df = pd.DataFrame(segs)
    seg_df.to_csv(OUT / "ev10_segments.csv", index=False)

    pd.set_option("display.width", 250, "display.max_columns", 40)
    print(f"file: {EV10_MAT.name}  vehicles: {len(df)}")
    print(df.to_string(index=False))
    print("\nsegments: total", len(seg_df), "| any NaN:", int(seg_df["nan"].sum()),
          "| unequal lengths:", int((~seg_df["lengths_equal"]).sum()),
          "| Q non-monotonic:", int((~seg_df["q_monotonic"]).sum()),
          "| segments with positive current samples:", int((seg_df["i_pos_count"] > 0).sum()),
          "| Vmax<Vmean:", int((~seg_df["vmax_ge_vmean"]).sum()))


if __name__ == "__main__":
    main()
