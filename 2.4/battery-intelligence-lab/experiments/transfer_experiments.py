"""NASA -> EV10 transfer experiments with normalisation / correction. Outputs: results/transfer/.

Protocol
  1. NASA transfer table: for each discharge of B0005/6/7/18, common features of the preceding
     charge (methods A0..C2, src/features/transfer_features.py), target soh_rated = C/2.0 Ah.
  2. Selection uses NASA only: every (method, model) is scored by NASA leave-one-battery-out
     MAE; the minimum is the final pipeline. The choice is written to selection.json *before*
     EV10 labels are read for scoring.
  3. The final pipeline is fit on all NASA rows and applied once to EV10 (external test).
     Every other (method, model) EV10 score is reported as exploratory only.
  4. EV10 labels are never used for training, selection, windows or correction constants.

Usage: .venv/Scripts/python -m experiments.transfer_experiments
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.data.ev10 import load_ev10
from src.data.nasa import RATED_CAPACITY_AH, find_mat_files, load_battery
from src.evaluation.metrics import fit_predict, scores
from src.evaluation.splits import lobo_splits, temporal_split
from src.features.nasa_features import build_nasa_table
from src.features.transfer_features import (BIN_COLS, METHODS, RATIO_COLS, curve_features, ev10_curve,
                                            ev10_resistance, ev10_sample_soc, method_features,
                                            nasa_charge_curve, soc_ocv_table)
from src.models.zoo import HYPERPARAMS, MODEL_NAMES, fit_kwargs, make_model
from src.utils import write_json
from src.viz import BATTERY_COLOR, INK, MODEL_COLOR, MUTED, SERIES, plt, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "transfer"
FIG = OUT / "figures"
BATTERIES = ["B0005", "B0006", "B0007", "B0018"]
TARGET = "soh_rated"
EXCLUDE_VEH = {5: "README·파일 라벨 불일치 (Cn 174 vs 147 Ah)"}
README_SOH5 = 0.8221
ALL_FEATS = ["q390_400"] + BIN_COLS + RATIO_COLS
N_BOOT = 10000


# ---------------------------------------------------------------- tables
def nasa_transfer_table() -> pd.DataFrame:
    base, _ = build_nasa_table(BATTERIES)
    rows = []
    for b in BATTERIES:
        last, n = None, 0
        for c in load_battery(find_mat_files()[b]):
            if c.type == "charge":
                last = c
            elif c.type == "discharge":
                n += 1
                row = {"battery": b, "discharge_no": n}
                if last is not None:
                    v, dq, i, r = nasa_charge_curve(last)
                    total = float(dq.sum())
                    valid = total >= 1.0 and v.size > 10 and v.max() >= 4.195
                    row.update({"r_onset_ohm": r, "charge_total_ah": total, "charge_valid": valid})
                    if valid:
                        raw = curve_features(v, dq, i, RATED_CAPACITY_AH)
                        ir = curve_features(v, dq, i, RATED_CAPACITY_AH, r)
                        row.update({f"raw_{k}": x for k, x in raw.items()})
                        row.update({f"ir_{k}": x for k, x in ir.items()})
                rows.append(row)
                last = None
    feats = pd.DataFrame(rows)
    df = base[["battery", "discharge_no", "capacity_ah", "soh_init", "soh_rated"]].merge(feats, on=["battery", "discharge_no"], how="left")
    df["soh_charge_rated"] = np.where(df["charge_valid"] == True, df["charge_total_ah"] / RATED_CAPACITY_AH, np.nan)  # noqa: E712
    return df


def method_matrix(df: pd.DataFrame, method: str) -> pd.DataFrame:
    pre = "ir_" if METHODS[method]["ir"] else "raw_"
    return df[[pre + f for f in METHODS[method]["features"]]].set_axis(METHODS[method]["features"], axis=1)


def ev10_table(packs) -> pd.DataFrame:
    rows = []
    for p in packs:
        veh = int(p["Veh"])
        v, dq, i, _ = ev10_curve(p)
        r, n_steps = ev10_resistance(p)
        raw = curve_features(v, dq, i, p["Cn"])
        ir = curve_features(v, dq, i, p["Cn"], r)
        m = (v >= 3.90) & (v < 4.05) & (dq > 0)
        row = {"veh": veh, "Cn": p["Cn"], "Ncell": p["Ncell"], "soh_file": p["SOH"],
               "r_step_ohm": r, "n_current_steps": n_steps,
               "c_rate_in_window": float(np.sum(i[m] * dq[m]) / np.sum(dq[m]) / p["Cn"]) if m.any() else np.nan,
               "i_in_window_a": float(np.sum(i[m] * dq[m]) / np.sum(dq[m])) if m.any() else np.nan,
               "vmean_max": float(v.max()),
               "soc_lo": min(float(x.split("-")[0]) for x in p["data"]["SOC"]),
               "soc_hi": max(float(x.split("-")[1]) for x in p["data"]["SOC"])}
        row.update({f"raw_{k}": x for k, x in raw.items()})
        row.update({f"ir_{k}": x for k, x in ir.items()})
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- NASA-only selection
def nasa_scores(df: pd.DataFrame, target: str, models=MODEL_NAMES) -> pd.DataFrame:
    rows = []
    for method in METHODS:
        X = method_matrix(df, method)
        d = pd.concat([df[["battery", "discharge_no", target]], X], axis=1)
        feats = list(X.columns)
        d = d[d[target].notna()].dropna(subset=feats)  # same rule as the pre-existing EV10 baseline: no imputed features
        for name in models:
            for validation, splits, scheme in [("LOBO", list(lobo_splits(d, BATTERIES)), "group"),
                                               ("temporal", [("all", *temporal_split(d, 0.7))], "forward")]:
                for held, tr, te in splits:
                    kw = fit_kwargs(name, d.loc[tr, "battery"], d.loc[tr, "discharge_no"], d.loc[tr, "discharge_no"])
                    pred, tm = fit_predict(make_model(name, scheme=scheme), d.loc[tr, feats], d.loc[tr, target], d.loc[te, feats], kw)
                    rows.append({"target": target, "method": method, "model": name, "validation": validation, "held_out": held,
                                 **scores(d.loc[te, target], pred), "fit_time_s": tm["fit_time_s"], "predict_time_s": tm["predict_time_s"]})
    return pd.DataFrame(rows)


def select(nasa_res: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    lobo = nasa_res[nasa_res["validation"] == "LOBO"].groupby(["method", "model"], sort=False)[["MAE", "RMSE", "R2", "fit_time_s"]].mean()
    temp = nasa_res[nasa_res["validation"] == "temporal"].set_index(["method", "model"])[["MAE", "RMSE", "R2", "fit_time_s"]]
    table = lobo.add_prefix("lobo_").join(temp.add_prefix("temporal_")).reset_index()
    best = table.loc[table["lobo_MAE"].idxmin()]
    per_method = table.loc[table.groupby("method", sort=False)["lobo_MAE"].idxmin(), ["method", "model", "lobo_MAE"]]
    return {"method": best["method"], "model": best["model"], "nasa_lobo_MAE": float(best["lobo_MAE"]),
            "per_method_representative": {r.method: r.model for r in per_method.itertuples()}}, table


def fit_full(df, method, model_name, target):
    X = method_matrix(df, method)
    d = pd.concat([df[["battery", "discharge_no", target]], X], axis=1)
    d = d[d[target].notna()].dropna(subset=list(X.columns))
    m = make_model(model_name, scheme="group")
    m.fit(d[list(X.columns)], d[target], **fit_kwargs(model_name, d["battery"], d["discharge_no"], d["discharge_no"]))
    return m, d


def predict_ev(model, ev: pd.DataFrame, method: str) -> np.ndarray:
    """Predictions use only EV features; labels are not an input (see tests)."""
    X = method_matrix(ev, method)
    out = np.full(len(ev), np.nan)
    ok = X.notna().all(axis=1).to_numpy()
    if ok.any():
        out[ok] = model.predict(X[ok])
    return out


# ---------------------------------------------------------------- statistics
def paired_bootstrap(err_a, err_b, n=N_BOOT, seed=0) -> dict:
    """CI of mean(|e_b|) - mean(|e_a|) over vehicles (negative = b better)."""
    a, b = np.abs(np.asarray(err_a, float)), np.abs(np.asarray(err_b, float))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, (n, a.size))
    d = b[idx].mean(1) - a[idx].mean(1)
    return {"mae_a": float(a.mean()), "mae_b": float(b.mean()), "diff": float(b.mean() - a.mean()),
            "ci95_low": float(np.percentile(d, 2.5)), "ci95_high": float(np.percentile(d, 97.5)),
            "improvement_pct": float((a.mean() - b.mean()) / a.mean() * 100), "share_boot_b_better": float((d < 0).mean())}


def ev_scores(y, pred) -> dict:
    s = scores(y, pred)
    s["spearman"] = float(spearmanr(y, pred)[0]) if np.ptp(pred) > 0 else np.nan
    return s


# ---------------------------------------------------------------- diagnostics (label-free)
def window_position(packs) -> pd.DataFrame:
    """Where the 3.90 / 4.00 V crossings fall: NASA as fraction of the charge delivered,
    EV10 as BMS SOC (%) interpolated within segments. Raw and IR-corrected voltage."""
    rows = []
    for b in BATTERIES:
        ch = [c for c in load_battery(find_mat_files()[b]) if c.type == "charge"]
        for stage, c in [("초기", ch[1]), ("중기", ch[len(ch) // 2]), ("후기", ch[-2])]:
            v, dq, i, r = nasa_charge_curve(c)
            frac = np.cumsum(dq) / dq.sum()
            for kind, vv in [("raw", v), ("ir", v - i * r)]:
                rows.append({"domain": "NASA", "unit": b, "stage": stage, "voltage": kind, "position_unit": "누적 충전 비율 %",
                             **{f"at_{x:.2f}V": float(frac[np.argmax(vv >= x)] * 100) if (vv >= x).any() else np.nan for x in (3.90, 4.00)}})
    for p in packs:
        v, dq, i, _ = ev10_curve(p)
        r, _ = ev10_resistance(p)
        soc = ev10_sample_soc(p)
        for kind, vv in [("raw", v), ("ir", v - i * r)]:
            rows.append({"domain": "EV10", "unit": f"veh{int(p['Veh'])}", "stage": "", "voltage": kind, "position_unit": "BMS SOC %",
                         **{f"at_{x:.2f}V": float(soc[np.argmax(vv >= x)]) if (vv >= x).any() else np.nan for x in (3.90, 4.00)}})
    return pd.DataFrame(rows)


def ocv_residual(packs) -> pd.DataFrame:
    """EV10 only: Vmean (raw / IR-corrected) minus the vehicle's own OCV(SOC) table, at
    charging samples inside the table's SOC range. NASA has no OCV table, so no counterpart."""
    rows = []
    for p in packs:
        v, dq, i, _ = ev10_curve(p)
        r, _ = ev10_resistance(p)
        soc = ev10_sample_soc(p) / 100
        s_tab, ocv = soc_ocv_table(p)
        m = (i > 1) & (soc >= s_tab.min()) & (soc <= s_tab.max())
        o = np.interp(soc[m], s_tab, ocv)
        rows.append({"veh": int(p["Veh"]), "ocv_points": s_tab.size, "soc_table_range": f"{s_tab.min():.2f}–{s_tab.max():.2f}",
                     "median_raw_minus_ocv_V": float(np.median(v[m] - o)),
                     "median_ir_minus_ocv_V": float(np.median(v[m] - i[m] * r - o)),
                     "median_ir_drop_V": float(np.median(i[m] * r))})
    return pd.DataFrame(rows)


def domain_shift(nasa: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Label-free: share of EV10 vehicles inside the NASA range of every feature, and nearest-
    neighbour distance in NASA-standardised feature space (EV->NASA vs held-out NASA battery->rest)."""
    rows = []
    for method in METHODS:
        Xn, Xe = method_matrix(nasa, method).dropna(), method_matrix(ev, method)
        Xe = Xe[ev["veh"].ne(5) & Xe.notna().all(axis=1)]
        mu, sd = Xn.mean(), Xn.std().replace(0, 1)
        zn, ze = ((Xn - mu) / sd).to_numpy(), ((Xe - mu) / sd).to_numpy()
        inside = ((Xe >= Xn.min()) & (Xe <= Xn.max())).all(axis=1)
        nn_ev = [np.min(np.linalg.norm(zn - z, axis=1)) for z in ze]
        bat = nasa.loc[Xn.index, "battery"].to_numpy()
        nn_nasa = [np.min(np.linalg.norm(zn[bat != bat[k]] - zn[k], axis=1)) for k in range(len(zn))]
        rows.append({"method": method, "n_ev": len(Xe), "ev_inside_nasa_range": int(inside.sum()),
                     "nn_dist_ev_to_nasa_median": float(np.median(nn_ev)),
                     "nn_dist_nasa_heldout_battery_median": float(np.median(nn_nasa))})
    return pd.DataFrame(rows)


def polarization(nasa: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for b, g in nasa.groupby("battery"):
        r = g["r_onset_ohm"].median()
        rows.append({"domain": "NASA", "unit": b, "R_ohm": r, "current_a": 1.5, "c_rate": 1.5 / RATED_CAPACITY_AH,
                     "ir_drop_v": 1.5 * r, "R_times_Crated_ohm_ah": r * RATED_CAPACITY_AH,
                     "R_source": "충전 시작 전압 점프 (같은 충전 Cycle, 표본 간격 약 2.5 s)"})
    for _, e in ev.iterrows():
        rows.append({"domain": "EV10", "unit": f"veh{int(e['veh'])}", "R_ohm": e["r_step_ohm"], "current_a": e["i_in_window_a"],
                     "c_rate": e["c_rate_in_window"], "ir_drop_v": e["r_step_ohm"] * e["i_in_window_a"],
                     "R_times_Crated_ohm_ah": e["r_step_ohm"] * e["Cn"],
                     "R_source": f"전류 계단 {int(e['n_current_steps'])}개 중앙값 (팩 전류 기준, 표본 간격 1 s)"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- figures
def fig_curves(packs, nasa_ir):
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharey=True)
    ch = [c for c in load_battery(find_mat_files()["B0005"]) if c.type == "charge"]
    for col, kind in enumerate(["raw", "ir"]):
        ax = axes[0, col]
        for c, color, lab in [(ch[1], SERIES[0], "초기"), (ch[len(ch) // 2], SERIES[1], "중기"), (ch[-2], SERIES[2], "후기")]:
            v, dq, i, r = nasa_charge_curve(c)
            ax.plot(np.cumsum(dq) / RATED_CAPACITY_AH, v if kind == "raw" else v - i * r, color=color, label=f"B0005 {lab}")
        ax.set_title(f"NASA 셀 ({'단자전압' if kind == 'raw' else 'IR 보정 V−I·R'}), 0.75 C")
        ax = axes[1, col]
        for p, color in zip([x for x in packs if int(x["Veh"]) in (1, 3, 9)], SERIES):
            v, dq, i, _ = ev10_curve(p)
            r, _ = ev10_resistance(p)
            ax.plot(np.cumsum(np.clip(dq, 0, None)) / p["Cn"], v if kind == "raw" else v - i * r, color=color,
                    label=f"차량 {int(p['Veh'])} (SOH {p['SOH']:.3f})")
        ax.set_title(f"EV10 팩 ({'셀 평균전압' if kind == 'raw' else 'IR 보정 Vmean−I·R'}), 약 0.3 C")
        ax.set_xlabel("누적 충전량 / 정격용량")
    for ax in axes.ravel():
        for (a, z), shade in zip([(3.90, 3.95), (3.95, 4.00), (4.00, 4.05)], ["#e1e0d9", "#ecebe5", "#e1e0d9"]):
            ax.axhspan(a, z, color=shade, zorder=0)
        ax.set_ylim(3.2, 4.25)
        ax.legend(fontsize=7, loc="lower right")
    for ax in axes[:, 0]:
        ax.set_ylabel("전압 (V)")
    fig.suptitle("충전 곡선: 원 전압 vs IR 보정 전압 (회색 띠: 공통 특징 구간 3.90–4.05 V)", fontsize=11)
    save(fig, FIG / "transfer_charge_curves.png")


def fig_metrics(comp: pd.DataFrame, baseline_const: float):
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))
    x = np.arange(len(comp))
    for ax, metric in zip(axes, ["MAE", "RMSE", "R2"]):
        colors = [SERIES[1] if f else SERIES[0] for f in comp["is_final"]]
        ax.bar(x, comp[f"ev_{metric}"], color=colors, width=0.6)
        if metric == "MAE":
            ax.axhline(baseline_const, color=INK, lw=1)
            ax.text(-0.45, baseline_const, "NASA 평균 상수", va="bottom", ha="left", fontsize=7, color=INK)
        short = {"LinearRegression": "LR", "RandomForest": "RF", "SVR_RBF": "SVR", "XGBoost": "XGB", "Stacking": "Stack"}
        ax.set_xticks(x, [f"{m}\n{short[mo]}" for m, mo in zip(comp["method"], comp["model"])], fontsize=8)
        ax.set_title(f"EV10 {metric}" + (" (높을수록 좋음)" if metric == "R2" else " (낮을수록 좋음)"))
    fig.suptitle("방법별 대표 모델(NASA LOBO 기준)의 EV10 외부 성능 · 주황 = NASA만으로 선정한 최종 파이프라인, 나머지 = 탐색", fontsize=10)
    save(fig, FIG / "transfer_metrics_comparison.png")


def fig_vehicles(veh: pd.DataFrame, final_label: str):
    fig, ax = plt.subplots(figsize=(8, 3.8))
    v = veh.sort_values("veh")
    x = np.arange(len(v))
    ax.scatter(x, v["soh_file"], marker="D", s=40, color=INK, label="실제 SOH 라벨 (충전 기반)", zorder=3)
    ax.scatter(x - 0.12, v["pred_A0"], s=24, color=SERIES[0], label="A0 기존 (XGB)")
    ax.scatter(x + 0.12, v["pred_final"], s=24, color=SERIES[1], label=f"최종 {final_label}")
    for xi, (a, b, y) in enumerate(zip(v["pred_A0"], v["pred_final"], v["soh_file"])):
        ax.plot([xi - 0.12, xi - 0.12], [a, y], color=SERIES[0], lw=0.6, alpha=0.6)
        ax.plot([xi + 0.12, xi + 0.12], [b, y], color=SERIES[1], lw=0.6, alpha=0.6)
    ax.set_xticks(x, [f"차량 {k}" for k in v["veh"]], rotation=30)
    ax.set_ylabel("SOH (정격용량 기준)")
    ax.set_title("EV10 차량별 실제 vs 예측 SOH (차량 5 제외)")
    ax.set_ylim(0.5, 1.06)
    ax.legend(fontsize=7, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
    ax.set_title("EV10 차량별 실제 vs 예측 SOH (차량 5 제외)", pad=26)
    save(fig, FIG / "transfer_vehicle_predictions.png")


def fig_feature_space(nasa: pd.DataFrame, ev: pd.DataFrame):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, pre, title in zip(axes, ["raw_", "ir_"], ["원 전압", "IR 보정 전압"]):
        for b, g in nasa.groupby("battery"):
            sc = ax.scatter(g[pre + "b390_395"], g[pre + "b395_400"], s=7, color=BATTERY_COLOR[b], label=f"NASA {b}", linewidths=0, alpha=0.8)
        e = ev[ev["veh"] != 5]
        ax.scatter(e[pre + "b390_395"], e[pre + "b395_400"], s=40, marker="D", color=INK, label="EV10 차량")
        for _, r in e.iterrows():
            ax.annotate(str(int(r["veh"])), (r[pre + "b390_395"], r[pre + "b395_400"]), xytext=(4, 2), textcoords="offset points", fontsize=7)
        ax.set_xlabel("Q[3.90,3.95) / 정격")
        ax.set_ylabel("Q[3.95,4.00) / 정격")
        ax.set_title(f"공통 특징 공간 · {title}")
    axes[0].legend(fontsize=7)
    save(fig, FIG / "transfer_feature_space.png")


# ---------------------------------------------------------------- main
def main():
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    nasa = nasa_transfer_table()
    nasa.to_csv(OUT / "nasa_transfer_features.csv", index=False)
    packs = load_ev10()
    ev = ev10_table(packs)
    ev.to_csv(OUT / "ev10_transfer_features.csv", index=False)

    # 1) NASA-only scoring and selection (no EV10 label touched before selection.json is written)
    t = time.perf_counter()
    nasa_res = nasa_scores(nasa, TARGET)
    nasa_res.to_csv(OUT / "nasa_internal_runs.csv", index=False)
    selection, nasa_table = select(nasa_res)
    nasa_table.to_csv(OUT / "nasa_internal_scores.csv", index=False)
    t_sel = time.perf_counter() - t
    write_json({"target": TARGET, "selection_rule": "NASA 4셀 leave-one-battery-out 평균 MAE 최소 (method × model)",
                "selection": selection, "methods": METHODS, "models": MODEL_NAMES, "hyperparams": HYPERPARAMS,
                "stacking_oof": "group (배터리 단위 leave-one-out, 감사 v2 방식 재사용)",
                "missing_features": "해당 방법의 특징이 하나라도 없는 NASA 행은 학습·검증에서 제외 (기존 EV10 Baseline과 같은 규칙, 대치 없음). 개발 실행(결측 유지)의 결과는 results_archive/transfer_dev_keepNaN",
                "ev10_role": "최종 외부 평가 전용. 라벨은 학습·선택·전압창·보정 상수에 사용하지 않음",
                "ev10_excluded": EXCLUDE_VEH, "nasa_rows": int(nasa[TARGET].notna().sum()),
                "nasa_selection_seconds": t_sel}, OUT / "selection.json")

    # 2) external evaluation (labels read only from here on)
    default = ev[~ev["veh"].isin(list(EXCLUDE_VEH))].copy()
    const = float(nasa[TARGET].mean())
    explore, preds = [], {}
    for method in METHODS:
        for name in MODEL_NAMES:
            m, _ = fit_full(nasa, method, name, TARGET)
            p = predict_ev(m, default, method)
            preds[(method, name)] = p
            ok = np.isfinite(p)
            explore.append({"method": method, "model": name, "n_vehicles": int(ok.sum()),
                            "selected_final": (method, name) == (selection["method"], selection["model"]),
                            "method_representative": selection["per_method_representative"][method] == name,
                            **{f"ev_{k}": v for k, v in ev_scores(default.loc[ok, "soh_file"], p[ok]).items()}})
    explore = pd.DataFrame(explore)
    nasa_lobo = nasa_table.set_index(["method", "model"])
    explore = explore.join(nasa_lobo[["lobo_MAE", "lobo_R2", "temporal_MAE", "temporal_R2", "lobo_fit_time_s"]], on=["method", "model"])
    explore.to_csv(OUT / "ev10_all_method_model_exploratory.csv", index=False)

    # references
    y = default["soh_file"].to_numpy()
    loo_mean = np.array([np.delete(y, k).mean() for k in range(y.size)])
    refs = pd.DataFrame([
        {"reference": "NASA 평균 SOH 상수 (EV 라벨 미사용)", **ev_scores(y, np.full(y.size, const))},
        {"reference": "EV10 다른 차량 라벨 평균 (LOO, EV 라벨 사용 · 참고)", **ev_scores(y, loo_mean)},
    ])
    refs.to_csv(OUT / "ev10_reference_baselines.csv", index=False)

    # 3) per-method comparison (representative = NASA-LOBO-best model of that method)
    rep = explore[explore["method_representative"]].copy()
    rep["is_final"] = rep["selected_final"]
    rep["role"] = np.where(rep["is_final"], "최종 선정 (NASA만)", "탐색 (사후 비교용)")
    rep.loc[rep["method"] == "A0", "role"] = np.where(rep.loc[rep["method"] == "A0", "is_final"], "최종 선정 (NASA만)", "기존 Baseline 재현")
    rep.to_csv(OUT / "normalization_comparison.csv", index=False)

    a0_model = selection["per_method_representative"]["A0"]
    e_a0 = preds[("A0", a0_model)] - y
    e_fin = preds[(selection["method"], selection["model"])] - y
    common = np.isfinite(e_a0) & np.isfinite(e_fin)
    boot = paired_bootstrap(e_a0[common], e_fin[common])
    boot.update({"a": f"A0/{a0_model}", "b": f"{selection['method']}/{selection['model']}", "n_vehicles": int(common.sum())})
    boot_const = paired_bootstrap(np.full(y.size, const) - y, e_fin)
    boot_const.update({"a": "NASA 평균 상수", "b": f"{selection['method']}/{selection['model']}", "n_vehicles": int(y.size)})
    pd.DataFrame([boot, boot_const]).to_csv(OUT / "improvement_bootstrap.csv", index=False)

    veh = default[["veh", "Cn", "soh_file", "soc_lo", "soc_hi"]].copy()
    veh["pred_A0"] = preds[("A0", a0_model)]
    veh["pred_final"] = preds[(selection["method"], selection["model"])]
    for method in METHODS:
        veh[f"pred_{method}_{selection['per_method_representative'][method]}"] = preds[(method, selection["per_method_representative"][method])]
    veh["err_A0"] = veh["pred_A0"] - veh["soh_file"]
    veh["err_final"] = veh["pred_final"] - veh["soh_file"]
    veh.to_csv(OUT / "ev10_vehicle_predictions.csv", index=False)

    # 4) label-definition analyses
    nasa_lab = nasa[["battery", "discharge_no", "soh_rated", "soh_charge_rated", "capacity_ah", "charge_total_ah"]].dropna().copy()
    nasa_lab["prev_capacity_ah"] = nasa.groupby("battery")["capacity_ah"].shift(1).loc[nasa_lab.index]
    lab = {"n": int(len(nasa_lab)),
           "mean_soh_charge_minus_soh_rated": float((nasa_lab["soh_charge_rated"] - nasa_lab["soh_rated"]).mean()),
           "mae_soh_charge_vs_soh_rated": float((nasa_lab["soh_charge_rated"] - nasa_lab["soh_rated"]).abs().mean()),
           "median_charge_over_prev_discharge": float((nasa_lab["charge_total_ah"] / nasa_lab["prev_capacity_ah"]).median()),
           "spearman_soh_charge_vs_soh_rated": float(spearmanr(nasa_lab["soh_charge_rated"], nasa_lab["soh_rated"])[0])}
    res2 = nasa_scores(nasa, "soh_charge_rated")
    sel2, table2 = select(res2)
    table2.to_csv(OUT / "nasa_internal_scores_charge_label.csv", index=False)
    m2, _ = fit_full(nasa, sel2["method"], sel2["model"], "soh_charge_rated")
    p2 = predict_ev(m2, default, sel2["method"])
    ok2 = np.isfinite(p2)
    lab_rows = [{"analysis": "주 분석: NASA 방전 기반 soh_rated", "selection": f"{selection['method']}/{selection['model']}",
                 **ev_scores(y[common], veh["pred_final"].to_numpy()[common])},
                {"analysis": "라벨 정의 일치: NASA 충전 기반 soh_charge_rated (NASA만으로 재선정)", "selection": f"{sel2['method']}/{sel2['model']}",
                 **ev_scores(y[ok2], p2[ok2])}]
    cover = (default["soc_hi"] - default["soc_lo"]) / 100
    y_full = y / cover.to_numpy()
    lab_rows.append({"analysis": "민감도: EV10 라벨을 기록 SOC 범위로 나눠 0–100 % 환산 (주 분석 예측 그대로)",
                     "selection": f"{selection['method']}/{selection['model']}",
                     **ev_scores(y_full[common], veh["pred_final"].to_numpy()[common])})
    pd.DataFrame(lab_rows).to_csv(OUT / "label_definition_analysis.csv", index=False)

    # 5) diagnostics
    wp = window_position(packs)
    wp.to_csv(OUT / "window_position.csv", index=False)
    ocv = ocv_residual(packs)
    ocv.to_csv(OUT / "ev10_ocv_residual.csv", index=False)
    pol = polarization(nasa, ev)
    pol.to_csv(OUT / "polarization_c_rate.csv", index=False)
    ds = domain_shift(nasa, ev)
    ds.to_csv(OUT / "domain_shift_label_free.csv", index=False)
    common_feat = pd.concat([
        nasa.groupby("battery").agg(**{f"{pre}{f}_median": (pre + f, "median") for pre in ("raw_", "ir_") for f in ALL_FEATS}).reset_index().rename(columns={"battery": "unit"}).assign(domain="NASA"),
        ev.assign(unit=lambda d: "veh" + d["veh"].astype(str))[["unit"] + [pre + f for pre in ("raw_", "ir_") for f in ALL_FEATS]]
          .rename(columns={pre + f: f"{pre}{f}_median" for pre in ("raw_", "ir_") for f in ALL_FEATS}).assign(domain="EV10")])
    common_feat.to_csv(OUT / "common_feature_comparison.csv", index=False)

    # 6) figures
    fig_curves(packs, nasa)
    fig_metrics(rep.reset_index(drop=True), refs.loc[0, "MAE"])
    fig_vehicles(veh, f"{selection['method']}/{selection['model']}")
    fig_feature_space(nasa, ev)

    timing = time.perf_counter() - t0
    write_json({"selection": selection, "selection_charge_label": sel2, "label_stats": lab, "bootstrap": [boot, boot_const],
                "nasa_const_soh_rated": const, "runtime_s": timing}, OUT / "transfer_summary.json")
    pd.set_option("display.width", 260, "display.max_columns", 40)
    print(json.dumps(selection, ensure_ascii=False))
    print(rep[["method", "model", "role", "n_vehicles", "ev_MAE", "ev_RMSE", "ev_R2", "ev_spearman", "lobo_MAE", "temporal_MAE"]].round(4).to_string(index=False))
    print(refs.round(4).to_string(index=False))
    print(pd.DataFrame([boot, boot_const]).round(4).to_string(index=False))
    print(pd.DataFrame(lab_rows).round(4).to_string(index=False), json.dumps(lab))
    print(pol.round(4).to_string(index=False))
    print(ocv.round(4).to_string(index=False))
    print(wp.round(1).to_string(index=False))
    print(ds.round(3).to_string(index=False))
    print(f"runtime {timing:.1f}s")


if __name__ == "__main__":
    main()
