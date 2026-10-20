"""EV20 on-road charging analysis. Outputs: results/ev20/ and data/processed/ev20_sessions_clean.csv.

The capacity here is an *estimate*: integrated charge / BMS SOC change. It is not a
measured SOH; ratios to the 145 Ah nominal are reported as "capacity ratio", not SOH.

Usage: .venv/Scripts/python -m experiments.ev20_analysis
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.data.ev20 import NOMINAL_CAPACITY_AH, drop_exact_duplicates, load_vehicle, session_capacity, split_sessions, vehicle_files
from src.evaluation.knee import two_segment_fit
from src.utils import write_json
from src.viz import INK, MUTED, SERIES, plt, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "ev20"
FIG = OUT / "figures"
MIN_ROWS_CAPACITY = 100        # from capacity_extract.py
MIN_DELTA_SOC = 30.0           # SOC step is 0.4 %, so >=30 % keeps quantisation error ~1 %
CAP_RANGE = (0.5 * NOMINAL_CAPACITY_AH, 1.1 * NOMINAL_CAPACITY_AH)
MIN_SESSIONS_PER_MONTH = 5
WINTER = {12, 1, 2}
FEATURES = ["t_max_mean", "t_min_mean", "temp_spread", "c_rate", "soc_start", "delta_soc", "duration_min"]


def process_vehicle(vid: int, path: Path) -> tuple[pd.DataFrame, dict]:
    raw = load_vehicle(path)
    df, dedup = drop_exact_duplicates(raw)
    sess = split_sessions(df, gap_s=10.0, min_rows=2)
    s = pd.DataFrame([session_capacity(x) for x in sess])
    s.insert(0, "vehicle", vid)
    s["throughput_cum_ah"] = s["throughput_ah"].cumsum() - s["throughput_ah"]  # charge before this session
    s["efc_before"] = s["throughput_cum_ah"] / NOMINAL_CAPACITY_AH
    t0 = df["record_time"].min()
    s["elapsed_days"] = (s["start"] - t0).dt.total_seconds() / 86400
    s["month"] = s["start"].dt.to_period("M").dt.to_timestamp()
    s["temp_spread"] = s["t_max_mean"] - s["t_min_mean"]
    s["c_rate"] = -s["mean_current"] / NOMINAL_CAPACITY_AH
    log = {"vehicle": vid, **dedup, "sessions_all(min_rows=2)": len(s)}
    steps = [
        ("rows>=100", s["rows"] >= MIN_ROWS_CAPACITY),
        ("SOC 규칙(+2 % 점프, -0.1 % 하락 없음)", ~s["soc_jump_gt2"] & ~s["soc_drop_lt_neg0_1"]),
        ("ΔSOC>=30 %", s["delta_soc"] >= MIN_DELTA_SOC),
        ("양(+) 전류 샘플 없음", s["current_pos"] == 0),
        ("용량 계산 가능(NaN 아님)", s["capacity_ah"].notna()),
        (f"용량 {CAP_RANGE[0]:.1f}~{CAP_RANGE[1]:.1f} Ah", s["capacity_ah"].between(*CAP_RANGE)),
    ]
    keep = pd.Series(True, index=s.index)
    for name, m in steps:
        keep &= m
        log[f"after: {name}"] = int(keep.sum())
    s["clean"] = keep
    return s, log


def monthly(sessions: pd.DataFrame) -> pd.DataFrame:
    c = sessions[sessions["clean"]]
    g = c.groupby(["vehicle", "month"])
    m = g.agg(n_sessions=("capacity_ah", "size"), cap_median=("capacity_ah", "median"),
              cap_q25=("capacity_ah", lambda x: x.quantile(0.25)), cap_q75=("capacity_ah", lambda x: x.quantile(0.75)),
              temp_mean=("t_max_mean", "mean"), c_rate_mean=("c_rate", "mean"),
              efc_end=("efc_before", "max"), elapsed_days=("elapsed_days", "median")).reset_index()
    m = m[m["n_sessions"] >= MIN_SESSIONS_PER_MONTH].copy()
    first = m.groupby("vehicle")["month"].transform("min")
    m["elapsed_month"] = (m["month"].dt.year - first.dt.year) * 12 + (m["month"].dt.month - first.dt.month)
    return m


def trends(m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for v, g in m.groupby("vehicle"):
        x, y, temp, efc = g["elapsed_month"].to_numpy(float), g["cap_median"].to_numpy(), g["temp_mean"].to_numpy(), g["efc_end"].to_numpy()
        s, c = np.polyfit(x, y, 1)
        r2 = 1 - np.sum((y - (s * x + c)) ** 2) / np.sum((y - y.mean()) ** 2)
        X = np.column_stack([np.ones_like(x), x, temp])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        s_efc = np.polyfit(efc, y, 1)[0]
        rows.append({"vehicle": v, "months": len(g), "slope_ah_per_month": s, "r2_linear": r2,
                     "slope_ah_per_month_temp_adjusted": beta[1], "temp_coef_ah_per_degC": beta[2],
                     "slope_ah_per_100efc": s_efc * 100, "efc_total": efc.max(),
                     "fade_pct_per_year_vs_start": -s * 12 / c * 100})
    return pd.DataFrame(rows)


def first_last(sessions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for v, g in sessions[sessions["clean"]].groupby("vehicle"):
        a = g[g["start"] < g["start"].min() + pd.Timedelta(days=90)]
        b = g[g["start"] > g["start"].max() - pd.Timedelta(days=90)]
        rows.append({"vehicle": v, "first3m_n": len(a), "first3m_median_ah": a["capacity_ah"].median(),
                     "first3m_iqr_ah": a["capacity_ah"].quantile(.75) - a["capacity_ah"].quantile(.25),
                     "first3m_temp_mean": a["t_max_mean"].mean(), "first3m_period": f"{a['start'].min():%Y-%m}~{a['start'].max():%Y-%m}",
                     "last3m_n": len(b), "last3m_median_ah": b["capacity_ah"].median(),
                     "last3m_iqr_ah": b["capacity_ah"].quantile(.75) - b["capacity_ah"].quantile(.25),
                     "last3m_temp_mean": b["t_max_mean"].mean(), "last3m_period": f"{b['start'].min():%Y-%m}~{b['start'].max():%Y-%m}"})
    r = pd.DataFrame(rows)
    r["change_ah"] = r["last3m_median_ah"] - r["first3m_median_ah"]
    r["change_pct"] = r["change_ah"] / r["first3m_median_ah"] * 100
    r["last3m_ratio_to_nominal"] = r["last3m_median_ah"] / NOMINAL_CAPACITY_AH
    return r


def feature_corr(sessions: pd.DataFrame) -> pd.DataFrame:
    c = sessions[sessions["clean"]].copy()
    c["resid"] = c["capacity_ah"] - c.groupby(["vehicle", "month"])["capacity_ah"].transform("median")
    rows = []
    for f in FEATURES:
        rho_raw = spearmanr(c[f], c["capacity_ah"], nan_policy="omit")
        rho_res = spearmanr(c[f], c["resid"], nan_policy="omit")
        per_v = [spearmanr(g[f], g["resid"], nan_policy="omit")[0] for _, g in c.groupby("vehicle")]
        rows.append({"feature": f, "spearman_vs_capacity": rho_raw[0], "p_capacity": rho_raw[1],
                     "spearman_vs_within_month_residual": rho_res[0], "p_residual": rho_res[1],
                     "per_vehicle_residual_rho_median": float(np.nanmedian(per_v)),
                     "per_vehicle_same_sign": int(np.sum(np.sign(per_v) == np.sign(rho_res[0]))), "n_sessions": len(c)})
    return pd.DataFrame(rows)


def knees(m: pd.DataFrame, tr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for v, g in m.groupby("vehicle"):
        g = g.sort_values("elapsed_month")
        x, y = g["elapsed_month"].to_numpy(float), g["cap_median"].to_numpy()
        beta = tr.set_index("vehicle").at[v, "temp_coef_ah_per_degC"]
        y_adj = y - beta * (g["temp_mean"].to_numpy() - g["temp_mean"].mean())
        raw, adj = two_segment_fit(x, y), two_segment_fit(x, y_adj)
        bm = None
        if raw.get("break_x") is not None:
            bm = g.loc[g["elapsed_month"] == raw["break_x"], "month"].iloc[0]
        if not raw["candidate"] or not adj["candidate"]:
            verdict = "미검출"
        elif bm.month in WINTER or (bm + pd.offsets.MonthBegin(1)).month in WINTER:
            verdict = "판단 불가(겨울 경계 · 계절 교란 가능)"
        else:
            verdict = "검출"
        rows.append({"vehicle": v, "verdict": verdict, "months": len(g),
                     "break_month_raw": None if bm is None else f"{bm:%Y-%m}",
                     "delta_bic_raw": raw.get("delta_bic"), "slope_before_raw": raw.get("slope_before"),
                     "slope_after_raw": raw.get("slope_after"), "candidate_raw": raw["candidate"],
                     "delta_bic_temp_adj": adj.get("delta_bic"), "candidate_temp_adj": adj["candidate"],
                     "reason_raw": raw.get("reason", ""), "reason_temp_adj": adj.get("reason", ""),
                     "_fit": raw})
    return pd.DataFrame(rows)


def plots(sessions, m, fl, kn, corr):
    c = sessions[sessions["clean"]]
    fig, axes = plt.subplots(4, 5, figsize=(16, 11), sharex=True, sharey=True)
    for ax, (v, g) in zip(axes.ravel(), c.groupby("vehicle")):
        ax.scatter(g["start"], g["capacity_ah"], s=2, color=SERIES[0], alpha=0.25, linewidths=0)
        mm = m[m["vehicle"] == v]
        ax.plot(mm["month"] + pd.Timedelta(days=15), mm["cap_median"], color=INK, lw=1.6)
        ax.axhline(NOMINAL_CAPACITY_AH, color=MUTED, lw=0.8)
        ax.set_title(f"#{v}", fontsize=9)
        ax.set_ylim(95, 150)
        ax.tick_params(axis="x", rotation=45)
    for ax in axes[:, 0]:
        ax.set_ylabel("추정 용량 (Ah)")
    fig.suptitle("EV20 차량별 추정 용량 (점: 충전 세션, 선: 월 중앙값, 회색선: 공칭 145 Ah) — SOC 기반 추정치, 실측 SOH 아님", fontsize=11)
    save(fig, FIG / "ev20_capacity_by_vehicle.png")

    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8), sharey=True)
    for v, g in m.groupby("vehicle"):
        axes[0].plot(g["elapsed_month"], g["cap_median"], color=SERIES[0], lw=0.8, alpha=0.45)
        axes[1].plot(g["efc_end"], g["cap_median"], color=SERIES[0], lw=0.8, alpha=0.45)
    med = m.groupby("elapsed_month")["cap_median"].median()
    axes[0].plot(med.index, med.values, color=INK, lw=2.2, label="20대 중앙값")
    axes[0].set_xlabel("관측 경과 개월")
    axes[1].set_xlabel("누적 등가 완전충전 횟수 (누적 충전 Ah / 145)")
    axes[0].set_ylabel("월 중앙 추정 용량 (Ah)")
    axes[0].legend()
    axes[0].set_title("경과시간에 따른 추정 용량")
    axes[1].set_title("누적 충전량에 따른 추정 용량")
    save(fig, FIG / "ev20_capacity_vs_time_and_throughput.png")

    fig, ax = plt.subplots(figsize=(8, 4))
    y = np.arange(len(fl))
    ax.hlines(y, fl["last3m_median_ah"], fl["first3m_median_ah"], color="#c3c2b7", lw=2)
    ax.scatter(fl["first3m_median_ah"], y, color=SERIES[0], s=30, label="첫 3개월 중앙값", zorder=3)
    ax.scatter(fl["last3m_median_ah"], y, color=SERIES[1], s=30, label="마지막 3개월 중앙값", zorder=3)
    ax.set_yticks(y, [f"#{v}" for v in fl["vehicle"]])
    ax.invert_yaxis()
    ax.set_xlabel("추정 용량 (Ah)")
    ax.set_title("초기 3개월 vs 마지막 3개월")
    ax.legend(loc="lower left")
    save(fig, FIG / "ev20_first_vs_last_3m.png")

    resid = []
    tr = m.copy()
    for v, g in tr.groupby("vehicle"):
        s, c0 = np.polyfit(g["elapsed_month"], g["cap_median"], 1)
        resid.append(g["cap_median"] - (s * g["elapsed_month"] + c0))
    tr["detrended"] = pd.concat(resid)
    tr["cal_month"] = tr["month"].dt.month
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    by = tr.groupby("cal_month")
    axes[0].bar(by["detrended"].median().index, by["detrended"].median().values, color=SERIES[0], width=0.6)
    axes[0].axhline(0, color=MUTED, lw=0.8)
    axes[0].set_xlabel("달력 월")
    axes[0].set_ylabel("선형 추세 제거 후 잔차 (Ah)")
    axes[0].set_title("계절성: 월별 추정 용량 잔차 (20대 중앙값)")
    axes[1].bar(by["temp_mean"].mean().index, by["temp_mean"].mean().values, color=SERIES[1], width=0.6)
    axes[1].set_xlabel("달력 월")
    axes[1].set_ylabel("충전 중 팩 최고온도 평균 (℃)")
    axes[1].set_title("월별 충전 중 팩 온도")
    for ax in axes:
        ax.set_xticks(range(1, 13))
    save(fig, FIG / "ev20_seasonality.png")

    fig, axes = plt.subplots(4, 5, figsize=(16, 11), sharey=True)
    for ax, (_, r) in zip(axes.ravel(), kn.iterrows()):
        g = m[m["vehicle"] == r["vehicle"]].sort_values("elapsed_month")
        x = g["elapsed_month"].to_numpy(float)
        ax.scatter(x, g["cap_median"], s=10, color=SERIES[0], linewidths=0)
        f = r["_fit"]
        if "slope_line" in f:
            ax.plot(x, f["intercept_line"] + f["slope_line"] * x, color=MUTED, lw=1)
            c2 = f["coef_two_segment"]
            ax.plot(x, c2[0] + c2[1] * x + c2[2] * np.clip(x - f["break_x"], 0, None), color=SERIES[1], lw=1.2)
        ax.set_title(f"#{r['vehicle']} · {r['verdict'][:8]} · ΔBIC {r['delta_bic_raw']:.1f}", fontsize=8)
    for ax in axes[-1]:
        ax.set_xlabel("관측 경과 개월")
    for ax in axes[:, 0]:
        ax.set_ylabel("월 중앙 추정 용량 (Ah)")
    fig.suptitle("Knee 탐색: 단일 직선(회색) vs 2구간 직선(주황), 월 중앙 추정 용량", fontsize=11)
    save(fig, FIG / "ev20_knee_search.png")

    fig, ax = plt.subplots(figsize=(7, 3.4))
    yy = np.arange(len(corr))
    ax.barh(yy - 0.18, corr["spearman_vs_capacity"], 0.34, color=SERIES[0], label="추정 용량과의 상관")
    ax.barh(yy + 0.18, corr["spearman_vs_within_month_residual"], 0.34, color=SERIES[1], label="월 중앙값 대비 잔차와의 상관")
    ax.set_yticks(yy, corr["feature"])
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.invert_yaxis()
    ax.set_xlabel("Spearman ρ (세션 단위)")
    ax.set_title("충전 세션 특징과 추정 용량의 관계")
    ax.legend(fontsize=7)
    save(fig, FIG / "ev20_session_feature_corr.png")


def main():
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    frames, logs = [], []
    for vid, path in vehicle_files().items():
        s, log = process_vehicle(vid, path)
        frames.append(s)
        logs.append(log)
        print(f"#{vid}: {log}", flush=True)
    t_load = time.perf_counter() - t0
    sessions = pd.concat(frames, ignore_index=True)
    sessions.to_csv(ROOT / "data" / "processed" / "ev20_sessions_clean.csv", index=False)
    pd.DataFrame(logs).to_csv(OUT / "ev20_filter_log.csv", index=False)
    m = monthly(sessions)
    m.to_csv(OUT / "ev20_monthly.csv", index=False)
    tr = trends(m)
    tr.to_csv(OUT / "ev20_vehicle_trend.csv", index=False)
    fl = first_last(sessions)
    fl.to_csv(OUT / "ev20_first_last_3m.csv", index=False)
    corr = feature_corr(sessions)
    corr.to_csv(OUT / "ev20_session_feature_corr.csv", index=False)
    kn = knees(m, tr)
    kn.drop(columns="_fit").to_csv(OUT / "ev20_knee.csv", index=False)
    plots(sessions, m, fl, kn, corr)
    timings = {"load_and_sessionize_s": t_load, "total_s": time.perf_counter() - t0}
    write_json({"rules": {"dedup": "모든 측정 컬럼이 같은 행만 제거", "session_gap_s": 10, "min_rows_capacity": MIN_ROWS_CAPACITY,
                         "min_delta_soc": MIN_DELTA_SOC, "capacity_range_ah": CAP_RANGE,
                         "min_sessions_per_month": MIN_SESSIONS_PER_MONTH, "knee": "ΔBIC>=10, 기울기 2배 가속, 원자료·온도보정 모두 후보, 겨울 경계 제외"},
               "timings_s": timings}, OUT / "ev20_run_config.json")
    print(json.dumps(timings))


if __name__ == "__main__":
    main()
