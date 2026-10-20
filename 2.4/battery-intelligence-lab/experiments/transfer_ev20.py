"""Can the NASA-trained transfer pipeline be applied to the EV20 long-term charging logs?

Uses the pipeline fixed in results/transfer/selection.json (NASA-only choice) and the A0
baseline. No EV20-specific model is trained. EV20 has no independently measured SOH, so the
NASA predictions are compared with the existing *estimated* capacity trend (Ah/ΔSOC / 145 Ah),
which is itself not ground truth.

Voltage: pack_voltage / 90 (90 cells in series) = mean cell voltage incl. interconnect drop,
the EV20 counterpart of EV10's Vmean. Charged Ah per sample: I * dt (8-10 s sampling).

Usage: .venv/Scripts/python -m experiments.transfer_ev20
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from experiments.transfer_experiments import fit_full
from src.data.ev20 import NOMINAL_CAPACITY_AH, drop_exact_duplicates, load_vehicle, split_sessions, vehicle_files
from src.features.transfer_features import METHODS, method_features, step_resistance
from src.utils import write_json
from src.viz import INK, MUTED, SERIES, plt, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "transfer" / "ev20"
SERIES_CELLS = 90
MIN_SESSIONS_PER_MONTH = 5


def session_arrays(s: pd.DataFrame):
    t = (s["record_time"] - s["record_time"].iloc[0]).dt.total_seconds().to_numpy()
    i = -s["charge_current"].to_numpy(float)  # charging positive
    v = s["pack_voltage"].to_numpy(float) / SERIES_CELLS
    dq = np.concatenate([[0.0], i[1:] * np.diff(t) / 3600])
    return v, dq, np.clip(i, 0, None), i


def main():
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    sel = json.loads((ROOT / "results" / "transfer" / "selection.json").read_text(encoding="utf-8"))["selection"]
    pipelines = {"final": (sel["method"], sel["model"]), "A0": ("A0", sel["per_method_representative"]["A0"])}
    nasa = pd.read_csv(ROOT / "results" / "transfer" / "nasa_transfer_features.csv")
    models = {k: fit_full(nasa, m, mo, "soh_rated")[0] for k, (m, mo) in pipelines.items()}

    rows, vstats = [], []
    for vid, path in vehicle_files().items():
        df, _ = drop_exact_duplicates(load_vehicle(path))
        sessions = [s for s in split_sessions(df, 10.0, 100)
                    if not (np.diff(s["soc"].to_numpy()) > 2).any() and not (np.diff(s["soc"].to_numpy()) < -0.1).any()
                    and not (s["charge_current"] > 0).any()]
        r, n_steps = step_resistance([-s["charge_current"].to_numpy(float) for s in sessions],
                                     [s["pack_voltage"].to_numpy(float) / SERIES_CELLS for s in sessions])
        mean_cell = (df["max_cell_voltage"] + df["min_cell_voltage"]) / 2
        vstats.append({"vehicle": vid, "sessions": len(sessions), "r_step_ohm": r, "n_current_steps": n_steps,
                       "median_packV_over_90_minus_mid_cell_V": float(np.median(df["pack_voltage"] / SERIES_CELLS - mean_cell)),
                       "median_dt_s": float(df["record_time"].diff().dt.total_seconds().median())})
        vrows, feats = [], {k: [] for k in pipelines}
        for s in sessions:
            v, dq, i_abs, _ = session_arrays(s)
            vrows.append({"vehicle": vid, "start": s["record_time"].iloc[0], "soc_start": s["soc"].iloc[0], "soc_end": s["soc"].iloc[-1],
                          "mean_c_rate": float(np.mean(i_abs) / NOMINAL_CAPACITY_AH), "t_max_mean": float(s["max_temperature"].mean())})
            for key, (m, _) in pipelines.items():
                feats[key].append(method_features(v, dq, i_abs, NOMINAL_CAPACITY_AH, r, m))
        vdf = pd.DataFrame(vrows)
        for key in pipelines:  # one batched prediction per vehicle and pipeline
            X = pd.DataFrame(feats[key])
            ok = X.notna().all(axis=1).to_numpy()
            vdf[f"covered_{key}"] = ok
            vdf[f"pred_{key}"] = np.nan
            if ok.any():
                vdf.loc[ok, f"pred_{key}"] = models[key].predict(X[ok])
        rows.append(vdf)
        print(f"#{vid}: sessions {len(sessions)} R {r * 1000:.3f} mOhm", flush=True)
    sess = pd.concat(rows, ignore_index=True)
    sess["month"] = sess["start"].dt.to_period("M").dt.to_timestamp()
    sess.to_csv(OUT / "ev20_session_predictions.csv", index=False)
    vs = pd.DataFrame(vstats)
    vs.to_csv(OUT / "ev20_signal_check.csv", index=False)

    cap = pd.read_csv(ROOT / "results" / "ev20" / "ev20_monthly.csv", parse_dates=["month"])
    cap["cap_ratio"] = cap["cap_median"] / NOMINAL_CAPACITY_AH
    comp_rows, monthly = [], []
    for key in pipelines:
        g = sess[sess[f"covered_{key}"]].groupby(["vehicle", "month"])
        m = g[f"pred_{key}"].agg(["median", "size"]).reset_index().rename(columns={"median": "pred_median", "size": "n_pred"})
        m = m[m["n_pred"] >= MIN_SESSIONS_PER_MONTH].merge(cap[["vehicle", "month", "elapsed_month", "cap_ratio"]], on=["vehicle", "month"])
        m["pipeline"] = key
        monthly.append(m)
        for v, gv in m.groupby("vehicle"):
            if len(gv) < 6:
                continue
            sp, _ = np.polyfit(gv["elapsed_month"], gv["pred_median"], 1)
            sc, _ = np.polyfit(gv["elapsed_month"], gv["cap_ratio"], 1)
            comp_rows.append({"pipeline": key, "vehicle": v, "months": len(gv),
                              "spearman_pred_vs_cap_ratio": float(spearmanr(gv["pred_median"], gv["cap_ratio"])[0]),
                              "slope_pred_per_year": sp * 12, "slope_cap_ratio_per_year": sc * 12,
                              "mean_pred": float(gv["pred_median"].mean()), "mean_cap_ratio": float(gv["cap_ratio"].mean()),
                              "pred_range": float(np.ptp(gv["pred_median"]))})
    monthly = pd.concat(monthly, ignore_index=True)
    monthly.to_csv(OUT / "ev20_monthly_pred_vs_capacity.csv", index=False)
    comp = pd.DataFrame(comp_rows)
    comp.to_csv(OUT / "ev20_trend_comparison.csv", index=False)
    cov = sess.groupby("vehicle")[[f"covered_{k}" for k in pipelines]].mean().reset_index()
    cov.to_csv(OUT / "ev20_window_coverage.csv", index=False)

    fig, axes = plt.subplots(4, 5, figsize=(16, 11), sharex=True, sharey=True)
    for ax, (v, g) in zip(axes.ravel(), cap.groupby("vehicle")):
        ax.plot(g["elapsed_month"], g["cap_ratio"], color=INK, lw=1.8, label="추정 용량 / 145 Ah (SOC 기반)")
        for key, color in [("A0", SERIES[0]), ("final", SERIES[1])]:
            mm = monthly[(monthly["vehicle"] == v) & (monthly["pipeline"] == key)]
            ax.plot(mm["elapsed_month"], mm["pred_median"], color=color, lw=1.2,
                    label=f"NASA 모델 {pipelines[key][0]}/{pipelines[key][1]}")
        ax.set_title(f"#{v}", fontsize=9)
    for ax in axes[-1]:
        ax.set_xlabel("관측 경과 개월")
    for ax in axes[:, 0]:
        ax.set_ylabel("SOH / 용량 비율")
    axes[0, 0].legend(fontsize=6)
    fig.suptitle("EV20: NASA 학습 모델의 월별 예측 SOH vs SOC 기반 추정 용량 비율 (둘 다 실측 SOH 아님)", fontsize=11)
    save(fig, OUT / "figures" / "ev20_nasa_pred_vs_capacity.png")

    summ = comp.groupby("pipeline").agg(vehicles=("vehicle", "size"), spearman_median=("spearman_pred_vs_cap_ratio", "median"),
                                        spearman_positive=("spearman_pred_vs_cap_ratio", lambda s: int((s > 0).sum())),
                                        slope_pred_median=("slope_pred_per_year", "median"),
                                        slope_cap_median=("slope_cap_ratio_per_year", "median"),
                                        mean_pred=("mean_pred", "mean"), mean_cap=("mean_cap_ratio", "mean")).reset_index()
    summ.to_csv(OUT / "ev20_trend_summary.csv", index=False)
    write_json({"pipelines": pipelines, "voltage": "pack_voltage/90", "c_rated_ah": NOMINAL_CAPACITY_AH,
                "session_filter": "간격 10 s 분할, 100행 이상, SOC 점프·하락 없음, 양(+) 전류 없음",
                "label_note": "EV20에는 독립 측정 SOH가 없음: 비교 대상은 SOC 기반 추정 용량 비율",
                "runtime_s": time.perf_counter() - t0}, OUT / "ev20_transfer_config.json")
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(vs.round(5).to_string(index=False))
    print(cov.round(3).to_string(index=False))
    print(summ.round(4).to_string(index=False))
    print(comp.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
