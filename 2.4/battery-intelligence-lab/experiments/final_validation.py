"""Final validation of the NASA -> EV transfer: charge-progress coordinates, resistance
estimates, feasibility of a progress-based method, and the final EV10 re-evaluation.
Outputs: results/final_validation/. No model or feature choice uses EV10 labels.

Usage: .venv/Scripts/python -m experiments.final_validation
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from experiments.transfer_experiments import (BATTERIES, EXCLUDE_VEH, METHODS, ev10_table, ev_scores, fit_full,
                                              nasa_transfer_table, paired_bootstrap, predict_ev)
from src.data.ev10 import load_ev10
from src.data.nasa import RATED_CAPACITY_AH, find_mat_files, load_battery
from src.features.transfer_features import ev10_curve, ev10_resistance, ev10_sample_soc, nasa_charge_curve
from src.models.zoo import MODEL_NAMES
from src.utils import write_json
from src.viz import INK, MUTED, SERIES, plt, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "final_validation"
TRANSFER = ROOT / "results" / "transfer"
MANDATORY = ["A0", "B1", "B2", "B3"]       # IR methods C1/C2 become reference-only (section 3)
CROSS_V = (3.90, 4.00)


# ---------------------------------------------------------------- charge progress (NASA)
def charge_progress(dq) -> np.ndarray:
    """Observed charge progress: cumulative Ah since the first recorded charging sample / total
    Ah of that record. A position *within the observed charge*, not an absolute SOC."""
    c = np.cumsum(np.clip(np.asarray(dq, float), 0, None))
    return c / c[-1] if c[-1] > 0 else np.full_like(c, np.nan)


def crossing(x, v, level) -> float:
    hit = np.flatnonzero(np.asarray(v) >= level)
    return float(np.asarray(x)[hit[0]]) if hit.size else np.nan


def nasa_charge_audit() -> pd.DataFrame:
    rows = []
    for b in BATTERIES:
        prev = None
        for c in load_battery(find_mat_files()[b]):
            if c.type == "discharge":
                prev = c
                continue
            if c.type != "charge":
                continue
            v, i, t = (np.asarray(c.data[k], float) for k in ("Voltage_measured", "Current_measured", "Time"))
            on = np.flatnonzero(i > 1.0)
            k = on[0] if on.size else -1
            vv, dq, ii, r_rev = nasa_charge_curve(c)
            row = {"battery": b, "cycle_index": c.index, "start_time": c.start_time,
                   "v_first": v[0], "i_first": i[0], "i_before_onset": i[k - 1] if k > 0 else np.nan,
                   "dt_before_onset_s": t[k] - t[k - 1] if k > 0 else np.nan,
                   "v_at_onset": v[k] if k >= 0 else np.nan, "i_at_onset": i[k] if k >= 0 else np.nan,
                   "v_max": float(np.max(v)), "i_last": i[-1], "duration_h": t[-1] / 3600,
                   "charge_ah": float(np.sum(dq)), "reached_4_2V": bool(np.max(v) >= 4.195),
                   "r_reversal_ohm": r_rev,
                   "r_rest_to_onset_ohm": (v[k] - v[0]) / (i[k] - i[0]) if k > 0 and i[k] - i[0] > 0.5 else np.nan}
            if prev is not None:
                pv, pt = np.asarray(prev.data["Voltage_measured"], float), np.asarray(prev.data["Time"], float)
                row.update({"prev_discharge_min_v": float(pv.min()), "prev_discharge_last_v": float(pv[-1]),
                            "prev_capacity_ah": float(prev.data["Capacity"][0]),
                            "rest_before_charge_s": (c.start_time - prev.start_time).total_seconds() - pt[-1]})
            if vv.size > 10:
                p = charge_progress(dq)
                row.update({f"progress_at_{x:.2f}V_raw": crossing(p, vv, x) for x in CROSS_V})
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- EV10 segments and coordinates
def ev10_segment_audit(packs) -> pd.DataFrame:
    rows = []
    for p in packs:
        prev_hi = None
        for k, (s, r) in enumerate(zip(p["data"]["Inf"], p["data"]["SOC"])):
            lo, hi = (float(x) for x in r.split("-"))
            rows.append({"veh": int(p["Veh"]), "segment": k, "soc_lo": lo, "soc_hi": hi, "samples": s["Q"].size,
                         "q_ah": float(s["Q"][-1]), "gap_to_previous_pct": None if prev_hi is None else lo - prev_hi,
                         "relation": "" if prev_hi is None else ("연속" if lo == prev_hi else ("겹침" if lo < prev_hi else "공백"))})
            prev_hi = hi
    return pd.DataFrame(rows)


def coordinates(packs, nasa_audit: pd.DataFrame, r_variants: dict) -> pd.DataFrame:
    """3.90/4.00 V crossing positions in each coordinate system that exists in a domain."""
    rows = []
    for b in BATTERIES:
        ch = [c for c in load_battery(find_mat_files()[b]) if c.type == "charge"]
        for stage, c in [("초기", ch[1]), ("중기", ch[len(ch) // 2]), ("후기", ch[-2])]:
            v, dq, i, r_rev = nasa_charge_curve(c)
            p, q = charge_progress(dq), np.cumsum(dq) / RATED_CAPACITY_AH
            for rname, r in [("raw", 0.0), *[(n, f(b, c, r_rev)) for n, f in r_variants["NASA"].items()]]:
                vv = v - i * r
                for x in CROSS_V:
                    rows.append({"domain": "NASA", "unit": b, "stage": stage, "voltage": rname, "level_V": x,
                                 "A_observed_progress_pct": crossing(p, vv, x) * 100,
                                 "C_Q_over_Crated_pct": crossing(q, vv, x) * 100, "B_absolute_soc_pct": np.nan})
    for pk in packs:
        v, dq, i, _ = ev10_curve(pk)
        p, q, soc = charge_progress(dq), np.cumsum(np.clip(dq, 0, None)) / pk["Cn"], ev10_sample_soc(pk)
        for rname, r in [("raw", 0.0), *[(n, f(pk)) for n, f in r_variants["EV10"].items()]]:
            vv = v - i * r
            for x in CROSS_V:
                rows.append({"domain": "EV10", "unit": f"veh{int(pk['Veh'])}", "stage": "", "voltage": rname, "level_V": x,
                             "A_observed_progress_pct": crossing(p, vv, x) * 100,
                             "C_Q_over_Crated_pct": crossing(q, vv, x) * 100, "B_absolute_soc_pct": crossing(soc, vv, x)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- resistance audit
def ev10_step_r(pack, lag: int, direction: str = "all") -> tuple[float, int]:
    """dVmean/dI over `lag` samples after a >=5 A step, only when the current stays within 1 A
    of its new value for those samples (charging current positive)."""
    rs = []
    for s in pack["data"]["Inf"]:
        ic, v = -s["I_load"], s["Vmean"]
        di = np.diff(ic)
        for j in np.flatnonzero(np.abs(di) >= 5):
            if direction == "up" and di[j] < 0 or direction == "down" and di[j] > 0:
                continue
            if j + lag < ic.size and np.all(np.abs(ic[j + 1:j + 1 + lag] - ic[j + 1]) < 1.0):
                rs.append((v[j + lag] - v[j]) / (ic[j + 1] - ic[j]))
    return (float(np.median(rs)) if rs else np.nan), len(rs)


def resistance_audit(packs, nasa_audit: pd.DataFrame) -> pd.DataFrame:
    feats = pd.read_csv(ROOT / "data" / "processed" / "nasa_features.csv")
    rows = []
    for b in BATTERIES:
        a = nasa_audit[nasa_audit["battery"] == b]
        f = feats[feats["battery"] == b]
        for name, val, note in [
            ("EIS Re (옴 성분)", f["imp_re"].median(), "주파수 영역 추정 전해질 저항"),
            ("EIS Re+Rct", (f["imp_re"] + f["imp_rct"]).median(), "옴 + 전하이동"),
            ("휴지→충전 시작 ΔV/ΔI", a["r_rest_to_onset_ohm"].median(), "첫 표본(I≈0)→충전 시작, 약 5 s, 사이에 방전 펄스 포함"),
            ("방전 펄스→충전 시작 ΔV/ΔI (기존 C1·C2)", a["r_reversal_ohm"].median(), "전류 방향 전환(−2~−4.5 A → +1.5 A), 약 2.7 s")]:
            rows.append({"domain": "NASA", "unit": b, "estimate": name, "R_ohm": val, "R_times_C_ohm_ah": val * RATED_CAPACITY_AH,
                         "ir_drop_at_charge_V": 1.5 * val, "note": note})
    ev = ev10_table(packs).set_index("veh")
    for pk in packs:
        veh = int(pk["Veh"])
        for name, (r, n) in [("1 s, 전체 계단 (기존 C1·C2)", ev10_resistance(pk)), ("1 s, 일정 전류 유지", ev10_step_r(pk, 1)),
                             ("2 s, 일정 전류 유지", ev10_step_r(pk, 2)), ("5 s, 일정 전류 유지", ev10_step_r(pk, 5)),
                             ("1 s, 증가 계단만", ev10_step_r(pk, 1, "up")), ("1 s, 감소 계단만", ev10_step_r(pk, 1, "down"))]:
            rows.append({"domain": "EV10", "unit": f"veh{veh}", "estimate": name, "R_ohm": r, "n_steps": n,
                         "R_times_C_ohm_ah": r * pk["Cn"], "ir_drop_at_charge_V": r * ev.loc[veh, "i_in_window_a"],
                         "note": "팩 전류 기준 평균 셀 전압"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- method B feasibility
def method_b_check(packs) -> pd.DataFrame:
    """A progress window needs the total observed charge (= EV10 label numerator) to place it.
    Charge inside a progress window [a, b] divided by Cn is (b - a) * sum(Q) / Cn = (b - a) * label."""
    rows = []
    for pk in packs:
        v, dq, i, _ = ev10_curve(pk)
        p = charge_progress(dq)
        d = np.clip(dq, 0, None)
        q_win = d[(p > 0.4) & (p <= 0.6)].sum() / pk["Cn"]
        rows.append({"veh": int(pk["Veh"]), "label_soh": pk["SOH"], "q_progress_40_60_over_Cn": q_win,
                     "q_over_0.2xlabel": q_win / (0.2 * pk["SOH"]), "total_q_over_Cn": d.sum() / pk["Cn"]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- final EV10 re-evaluation
def final_ev10(packs):
    sel = json.loads((TRANSFER / "selection.json").read_text(encoding="utf-8"))["selection"]
    scores = pd.read_csv(TRANSFER / "nasa_internal_scores.csv")
    mand = scores[scores["method"].isin(MANDATORY)]
    best = mand.loc[mand["lobo_MAE"].idxmin()]
    final = (best["method"], best["model"])
    # recomputed in memory like transfer_experiments: a CSV round trip changes the last float bit, which
    # SVR/Stacking solver tolerance turns into ~1e-4 MAE differences (measured, see report)
    nasa = nasa_transfer_table()
    ev = ev10_table(packs)
    default = ev[~ev["veh"].isin(list(EXCLUDE_VEH))].reset_index(drop=True)
    y = default["soh_file"].to_numpy()
    reps = {m: scores[scores["method"] == m].sort_values("lobo_MAE").iloc[0]["model"] for m in METHODS}
    preds, rows = {}, []
    for m in METHODS:
        for name in MODEL_NAMES:
            model, _ = fit_full(nasa, m, name, "soh_rated")
            preds[(m, name)] = predict_ev(model, default, m)
    a0 = preds[("A0", reps["A0"])]
    const = float(nasa["soh_rated"].mean())
    for (m, name), p in preds.items():
        role = ("최종 선정 (NASA만, 필수 방법 A0–B3)" if (m, name) == final else
                "기존 Baseline" if (m, name) == ("A0", reps["A0"]) else
                "참고: IR 보정 (근사)" if m in ("C1", "C2") else "탐색")
        b = paired_bootstrap(a0 - y, p - y)
        rows.append({"method": m, "model": name, "role": role, "method_representative": reps[m] == name,
                     **ev_scores(y, p), "bias_mean_error": float(np.mean(p - y)),
                     "mae_minus_A0": b["diff"], "ci95_low_vs_A0": b["ci95_low"], "ci95_high_vs_A0": b["ci95_high"],
                     "nasa_lobo_MAE": float(scores[(scores["method"] == m) & (scores["model"] == name)]["lobo_MAE"].iloc[0])})
    res = pd.DataFrame(rows)
    base = ev_scores(y, np.full(y.size, const))
    res = pd.concat([res, pd.DataFrame([{"method": "-", "model": "NASA 평균 SOH 상수", "role": "기준선 (EV 라벨 미사용)", **base,
                                         "bias_mean_error": float(np.mean(const - y))}])], ignore_index=True)
    veh = default[["veh", "soh_file"]].copy()
    for m in METHODS:
        veh[f"pred_{m}_{reps[m]}"] = preds[(m, reps[m])]
    veh["pred_final"] = preds[final]
    veh["err_final"] = veh["pred_final"] - veh["soh_file"]
    veh["err_A0"] = a0 - y
    return res, veh, {"final": list(final), "unchanged_vs_transfer_selection": [sel["method"], sel["model"]] == list(final),
                      "representatives": reps, "nasa_const": const}


def fig_progress(packs):
    fig, ax = plt.subplots(figsize=(8, 4.4))
    ch = [c for c in load_battery(find_mat_files()["B0005"]) if c.type == "charge"]
    for c, color, lab in [(ch[1], SERIES[0], "초기"), (ch[len(ch) // 2], SERIES[1], "중기"), (ch[-2], SERIES[2], "후기")]:
        v, dq, i, _ = nasa_charge_curve(c)
        ax.plot(charge_progress(dq) * 100, v, color=color, lw=1.4, label=f"NASA B0005 {lab} (단자전압)")
    for pk, color in zip([x for x in packs if int(x["Veh"]) in (1, 3, 9)], [SERIES[3], SERIES[4], SERIES[6]]):
        v, dq, i, _ = ev10_curve(pk)
        ax.plot(charge_progress(dq) * 100, v, color=color, lw=1.0, label=f"EV10 차량 {int(pk['Veh'])} (Vmean)")
    ax.axhspan(3.90, 4.00, color="#e1e0d9", zorder=0)
    ax.set_xlabel("관측 충전 진행률 (%) = 누적 충전량 / 해당 기록의 총 충전량")
    ax.set_ylabel("전압 (V)")
    ax.set_ylim(3.2, 4.25)
    ax.set_title("같은 좌표(관측 충전 진행률)에서 본 충전 곡선 · 회색 띠 3.90–4.00 V")
    ax.legend(fontsize=7, loc="lower right", ncol=2)
    save(fig, OUT / "figures" / "voltage_vs_observed_progress.png")


def main():
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    packs = load_ev10()
    na = nasa_charge_audit()
    na.to_csv(OUT / "nasa_charge_audit.csv", index=False)
    seg = ev10_segment_audit(packs)
    seg.to_csv(OUT / "ev10_segment_audit.csv", index=False)

    feats = pd.read_csv(ROOT / "data" / "processed" / "nasa_features.csv")
    re_med = feats.groupby("battery")["imp_re"].median().to_dict()
    r_variants = {"NASA": {"ir_EIS_Re": lambda b, c, r: re_med[b], "ir_reversal": lambda b, c, r: r},
                  "EV10": {"ir_1s": lambda pk: ev10_resistance(pk)[0], "ir_5s": lambda pk: ev10_step_r(pk, 5)[0]}}
    coords = coordinates(packs, na, r_variants)
    coords.to_csv(OUT / "coordinate_comparison.csv", index=False)
    res_audit = resistance_audit(packs, na)
    res_audit.to_csv(OUT / "resistance_audit.csv", index=False)
    mb = method_b_check(packs)
    mb.to_csv(OUT / "method_b_check.csv", index=False)

    res, veh, info = final_ev10(packs)
    res.to_csv(OUT / "final_ev10_comparison.csv", index=False)
    veh.to_csv(OUT / "final_ev10_vehicle_predictions.csv", index=False)
    fig_progress(packs)

    # summaries
    na_ok = na[na["reached_4_2V"] & (na["charge_ah"] >= 1.0)]
    cs = (coords[coords["voltage"] == "raw"].groupby(["domain", "level_V"])
          [["A_observed_progress_pct", "B_absolute_soc_pct", "C_Q_over_Crated_pct"]].agg(["min", "max"]))
    ev_def = coords[(coords["domain"] == "EV10") & (coords["unit"] != "veh5")]
    summary = {
        "nasa_charge": {"charges": int(len(na)), "valid_full_charges": int(len(na_ok)),
                        "median_rest_before_charge_s": na_ok.groupby("battery")["rest_before_charge_s"].median().round(1).to_dict(),
                        "median_i_before_onset_A": na_ok.groupby("battery")["i_before_onset"].median().round(3).to_dict(),
                        "median_prev_discharge_min_v": na_ok.groupby("battery")["prev_discharge_min_v"].median().round(3).to_dict(),
                        "median_charge_over_prev_capacity": float((na_ok["charge_ah"] / na_ok["prev_capacity_ah"]).median()),
                        "absolute_start_soc_known": False},
        "ev10_segments": seg["relation"].value_counts().to_dict(),
        "coordinate_ranges_raw": {f"{d}@{lv}": {c: [float(cs.loc[(d, lv), (c, 'min')]), float(cs.loc[(d, lv), (c, 'max')])]
                                                for c in ["A_observed_progress_pct", "B_absolute_soc_pct", "C_Q_over_Crated_pct"]}
                                  for d, lv in cs.index},
        "ev10_default_progress_minus_bms_soc_pp": float((ev_def["A_observed_progress_pct"] - ev_def["B_absolute_soc_pct"]).abs().max()),
        "method_b": {"q_over_0.2xlabel_range": [float(mb["q_over_0.2xlabel"].min()), float(mb["q_over_0.2xlabel"].max())],
                     "decision": "구현하지 않음: 진행률 좌표는 총 충전량(EV10 라벨 분자)으로 정의되어 특징이 라벨에 종속"},
        "ir_decision": "C1·C2는 필수 방법에서 제외, 근사 참고 실험으로 유지",
        "final_ev10": info, "runtime_s": time.perf_counter() - t0}
    write_json(summary, OUT / "final_validation_summary.json")
    pd.set_option("display.width", 260, "display.max_columns", 30)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    print(res_audit.round(5).to_string(index=False))
    print(coords.groupby(["domain", "voltage", "level_V"])[["A_observed_progress_pct", "B_absolute_soc_pct", "C_Q_over_Crated_pct"]].agg(["min", "max"]).round(1).to_string())
    print(mb.round(4).to_string(index=False))
    print(res[res["method_representative"].fillna(False).astype(bool) | (res["method"] == "-") | res["role"].str.startswith("최종")].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
