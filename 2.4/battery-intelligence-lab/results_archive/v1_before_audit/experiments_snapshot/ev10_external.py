"""External evaluation of NASA-trained models on the 10 EV packs (BatPackdata.mat).

Common feature: Ah charged while the voltage is inside a narrow window, divided by the rated
capacity (NASA: terminal voltage at 1.5 A CC, 2.0 Ah; EV10: mean cell voltage, Cn). Target:
NASA soh_rated (= C/2.0 Ah, rated basis like EV10's SOH = sum Q / Cn).

Usage: .venv/Scripts/python -m experiments.ev10_external
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
from src.features.ev10_features import charge_weighted_c_rate, window_features
from src.features.nasa_features import TRANSFER_WINDOWS, window_col
from src.models.zoo import MODEL_NAMES, make_model
from src.viz import BATTERY_COLOR, INK, MODEL_COLOR, MUTED, SERIES, plt, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "ev10"
FIG = OUT / "figures"
README_SOH = {1: 0.9430, 2: 0.9385, 3: 0.7891, 4: 0.8777, 5: 0.8221, 6: 0.9287, 7: 0.9698, 8: 0.9081, 9: 1.0171, 10: 0.9908}
README_CN = {5: 174.0}
EXCLUDED_DEFAULT = {5: "README(Cn 174 Ah, SOH 82.21 %)와 파일(Cn 147 Ah, SOH 97.31 %) 라벨 불일치"}
NASA_C_RATE = 1.5 / RATED_CAPACITY_AH


def ev10_table(packs) -> pd.DataFrame:
    rows = []
    for p in packs:
        veh = int(p["Veh"])
        base = {"veh": veh, "Cn_file": p["Cn"], "Ncell": p["Ncell"], "soh_file": p["SOH"], "soh_readme": README_SOH[veh],
                "c_rate_charge_weighted": charge_weighted_c_rate(p), "voltage_type": "셀 평균전압(Vmean)"}
        for v1, v2 in TRANSFER_WINDOWS:
            f = window_features(p, v1, v2)
            tag = f"{int(v1 * 100)}_{int(v2 * 100)}"
            base.update({f"{k}_{tag}": val for k, val in f.items() if k not in ("v_min", "v_max")})
            base["v_min"], base["v_max"] = f["v_min"], f["v_max"]
        rows.append(base)
    df = pd.DataFrame(rows)
    # vehicle 5 under the README rating: same charge, different denominator
    return df


def nasa_table() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / "processed" / "nasa_features.csv")
    for v1, v2 in TRANSFER_WINDOWS:
        df[f"x_{int(v1 * 100)}_{int(v2 * 100)}"] = df[window_col(v1, v2)] / RATED_CAPACITY_AH
    return df


def evaluate(nasa, ev, tag):
    xcol = f"x_{tag}"
    tr = nasa[nasa[xcol].notna()]
    rows, preds = [], {}
    ev = ev.copy()
    ev["x"] = ev[f"q_win_norm_{tag}"]
    lo, hi = tr[xcol].min(), tr[xcol].max()
    ev["x_inside_nasa_range"] = ev["x"].between(lo, hi)
    cases = {
        "default (veh5 제외)": ev[(ev["veh"] != 5) & ev["x"].notna()].assign(y=lambda d: d["soh_file"]),
        "veh5 포함 · 파일 라벨": ev[ev["x"].notna()].assign(y=lambda d: d["soh_file"]),
        "veh5 포함 · README 라벨": ev[ev["x"].notna()].assign(
            y=lambda d: np.where(d["veh"] == 5, README_SOH[5], d["soh_file"]),
            x=lambda d: np.where(d["veh"] == 5, d["q_win_ah_" + tag] / README_CN[5], d["x"])),
    }
    if not np.isfinite(ev.loc[ev["veh"] == 5, "x"]).any():
        # vehicle 5 never reaches the window's upper voltage -> its feature does not exist;
        # the "include veh5" cases would just repeat the default case
        cases = {k: v for k, v in cases.items() if k.startswith("default")}
    for name in MODEL_NAMES:
        model = make_model(name)
        _, timing = fit_predict(model, tr[[xcol]], tr["soh_rated"], tr[[xcol]].iloc[:1])
        for case, d in cases.items():
            if len(d) < 2:
                continue
            pred = model.predict(d[["x"]].rename(columns={"x": xcol}))
            preds[(case, name)] = pd.DataFrame({"veh": d["veh"], "y": d["y"], "x": d["x"], "pred": pred})
            rho = spearmanr(d["y"], pred)[0] if np.ptp(pred) > 0 else np.nan
            rows.append({"window": tag, "case": case, "model": name, **scores(d["y"], pred), "spearman": rho,
                         "n_vehicles": len(d), "n_outside_nasa_range": int((~d["x"].between(lo, hi)).sum()),
                         "fit_time_s": timing["fit_time_s"]})
    for case, d in cases.items():
        if len(d) < 2:
            continue
        rows.append({"window": tag, "case": case, "model": "Baseline: NASA 평균 SOH", **scores(d["y"], np.full(len(d), tr["soh_rated"].mean())),
                     "n_vehicles": len(d)})
        # EV-only leave-one-vehicle-out linear fit on the same feature (no NASA): is the feature informative in-domain?
        loo = []
        for i in range(len(d)):
            m = np.arange(len(d)) != i
            s, c = np.polyfit(d["x"].to_numpy()[m], d["y"].to_numpy()[m], 1)
            loo.append(s * d["x"].to_numpy()[i] + c)
        rows.append({"window": tag, "case": case, "model": "EV10 내부 LOO 선형회귀 (참고)", **scores(d["y"], loo),
                     "spearman": spearmanr(d["y"], d["x"])[0], "n_vehicles": len(d)})
    return pd.DataFrame(rows), preds, (lo, hi)


def plot_curves(packs):
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    cyc = load_battery(find_mat_files()["B0005"])
    charges = [c for c in cyc if c.type == "charge" and c.data["Time"].size > 1000]
    for c, color, lab in [(charges[1], SERIES[0], "초기"), (charges[len(charges) // 2], SERIES[1], "중기"), (charges[-2], SERIES[2], "후기")]:
        i, t, v = c.data["Current_measured"], c.data["Time"], c.data["Voltage_measured"]
        q = np.concatenate([[0], np.cumsum(np.clip(i[1:], 0, None) * np.diff(t) / 3600)]) / RATED_CAPACITY_AH
        axes[0].plot(q, v, color=color, label=f"B0005 {lab} 충전")
    axes[0].set_title("NASA 셀: 단자전압, 1.5 A(0.75 C) CC-CV")
    axes[0].set_xlabel("누적 충전량 / 정격 2.0 Ah")
    axes[0].set_ylabel("전압 (V)")
    for p, color in zip([x for x in packs if int(x["Veh"]) in (1, 3, 9)], SERIES):
        q = 0.0
        xs, ys = [], []
        for s in p["data"]["Inf"]:
            xs.append((q + s["Q"]) / p["Cn"])
            ys.append(s["Vmean"])
            q += s["Q"][-1]
        axes[1].plot(np.concatenate(xs), np.concatenate(ys), color=color, label=f"차량 {int(p['Veh'])} (SOH {p['SOH']:.3f})")
    axes[1].set_title("EV10 팩: 셀 평균전압, 약 0.3 C 충전")
    axes[1].set_xlabel("누적 충전량 / 정격 Cn")
    for ax in axes:
        for v1, v2 in TRANSFER_WINDOWS[:1]:
            ax.axhspan(v1, v2, color="#e1e0d9", zorder=0)
        ax.legend(fontsize=7)
    fig.suptitle("충전 곡선 비교 (회색 띠: 공통 특징 전압창 3.90–4.00 V)", fontsize=11)
    save(fig, FIG / "ev10_vs_nasa_charge_curves.png")


def plot_feature(nasa, ev):
    fig, axes = plt.subplots(1, len(TRANSFER_WINDOWS), figsize=(11, 4), sharey=True)
    for ax, (v1, v2) in zip(axes, TRANSFER_WINDOWS):
        tag = f"{int(v1 * 100)}_{int(v2 * 100)}"
        for b, g in nasa.groupby("battery"):
            ax.scatter(g[f"x_{tag}"], g["soh_rated"], s=8, color=BATTERY_COLOR[b], label=f"NASA {b}", linewidths=0, alpha=0.8)
        e = ev[ev[f"q_win_norm_{tag}"].notna()]
        ax.scatter(e[f"q_win_norm_{tag}"], e["soh_file"], s=36, color=INK, marker="D", label="EV10 차량 (파일 라벨)")
        for _, r in e.iterrows():
            ax.annotate(str(r["veh"]), (r[f"q_win_norm_{tag}"], r["soh_file"]), xytext=(4, 2), textcoords="offset points", fontsize=7)
        ax.set_title(f"{v1:.2f}–{v2:.2f} V 전압창")
        ax.set_xlabel("전압창 충전량 / 정격용량")
    axes[0].set_ylabel("SOH (정격용량 기준)")
    axes[0].legend(fontsize=7)
    fig.suptitle("공통 특징의 분포: NASA 셀과 EV10 팩은 같은 SOH에서 특징값이 다른 영역에 놓인다", fontsize=11)
    save(fig, FIG / "ev10_feature_domain_gap.png")


def plot_pred(preds, tag):
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    case = "default (veh5 제외)"
    base = preds[(case, MODEL_NAMES[0])]
    x = np.arange(len(base))
    ax.scatter(x, base["y"], color=INK, marker="D", s=36, label="실제 SOH (파일)", zorder=3)
    for k, m in enumerate(MODEL_NAMES):
        p = preds[(case, m)]
        ax.scatter(x + (k - 2) * 0.1, p["pred"], color=MODEL_COLOR[m], s=16, label=m, linewidths=0)
    ax.set_xticks(x, [f"차량 {v}" for v in base["veh"]], rotation=30)
    ax.set_ylabel("SOH")
    ax.set_title(f"NASA 학습 모델의 EV10 직접 적용 ({tag.replace('_', '–')} 창, veh5 제외)")
    ax.legend(ncol=3, fontsize=7)
    save(fig, FIG / f"ev10_external_predictions_{tag}.png")


def main():
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    packs = load_ev10()
    ev = ev10_table(packs)
    ev.to_csv(OUT / "ev10_features.csv", index=False)
    nasa = nasa_table()
    results, ranges = [], {}
    for v1, v2 in TRANSFER_WINDOWS:
        tag = f"{int(v1 * 100)}_{int(v2 * 100)}"
        res, preds, rng = evaluate(nasa, ev, tag)
        results.append(res)
        ranges[tag] = rng
        pd.concat([d.assign(case=c, model=m) for (c, m), d in preds.items()]).to_csv(OUT / f"ev10_predictions_{tag}.csv", index=False)
        plot_pred(preds, tag)
    res = pd.concat(results, ignore_index=True)
    res.to_csv(OUT / "ev10_external_eval.csv", index=False)
    plot_curves(packs)
    plot_feature(nasa, ev)
    comparison = pd.DataFrame([
        {"항목": "측정 대상", "NASA": "단일 셀 (정격 2.0 Ah, 화학계 README 미기재)", "EV10": f"팩 {int(ev['Ncell'].min())}~{int(ev['Ncell'].max())}직렬, Cn {ev['Cn_file'].min():.0f}~{ev['Cn_file'].max():.0f} Ah"},
        {"항목": "전압 신호", "NASA": "셀 단자전압", "EV10": "셀 평균전압 Vmean (최대전압 Vmax 별도)"},
        {"항목": "충전 C-rate", "NASA": f"{NASA_C_RATE:.2f} C (1.5 A CC)", "EV10": f"충전량 가중 {ev['c_rate_charge_weighted'].min():.2f}~{ev['c_rate_charge_weighted'].max():.2f} C"},
        {"항목": "SOH 정의", "NASA": "방전 용량 / 2.0 Ah (soh_rated)", "EV10": "전 구간 충전량 합 / Cn"},
        {"항목": "라벨 수", "NASA": f"{len(nasa)} (4셀 방전 Cycle)", "EV10": "10 (차량당 1개)"},
        {"항목": "온도", "NASA": "있음", "EV10": "없음"},
    ])
    comparison.to_csv(OUT / "ev10_nasa_comparison.csv", index=False)
    veh5 = ev[ev["veh"] == 5].iloc[0]
    json.dump({"windows": TRANSFER_WINDOWS, "nasa_feature_range": ranges, "excluded_default": EXCLUDED_DEFAULT,
               "veh5_window_coverage": f"Vmean 최대 {veh5['v_max']:.3f} V < 창 상한 → 두 전압창 모두 특징 없음, 포함 시나리오 평가 불가",
               "target_nasa": "soh_rated", "runtime_s": time.perf_counter() - t0},
              open(OUT / "ev10_run_config.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(ev.to_string(index=False))
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
