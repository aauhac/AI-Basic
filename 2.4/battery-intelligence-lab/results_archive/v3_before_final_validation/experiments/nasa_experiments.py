"""NASA SOH / RUL experiments A-E, future-SOH and RUL. All outputs go to results/nasa/.

Audit revision (v2):
  - Stacking builds its meta-learner's OOF predictions with a plan matched to the scenario
    (forward-in-time for temporal/small-data/future-temporal, leave-one-battery-out for LOBO).
  - Every scenario records a model chosen with training rows only (src.evaluation.selection);
    those choices form results/nasa/final_claims.csv. Tables with all models are descriptive.
  - RUL tables report crossing success/failure counts next to the MAE.

Usage: .venv/Scripts/python -m experiments.nasa_experiments
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.evaluation.metrics import fit_predict, scores
from src.evaluation.rul import EOL_AH, add_rul, extrapolate_rul, rul_summary
from src.evaluation.selection import select_model
from src.evaluation.splits import (lobo_splits, make_future_pairs, random_split, small_data_split,
                                   temporal_split, temporal_split_pairs)
from src.features.nasa_features import FEATURE_GROUPS, build_nasa_table, feature_list
from src.models.zoo import HYPERPARAMS, MODEL_NAMES, SINGLE_MODELS, fit_kwargs, make_model
from src.utils import write_json
from src.viz import BATTERY_COLOR, INK, MODEL_COLOR, MUTED, plt, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "nasa"
FIG = OUT / "figures"
BATTERIES = ["B0005", "B0006", "B0007", "B0018"]
DEFAULT_FEATURES = feature_list("charge", "impedance", "cycle")
ALL_FEATURES = feature_list("charge", "charge_ah", "impedance", "cycle", "history")
TARGET = "soh_init"
RANDOM_SEEDS = [0, 1, 2, 3, 4]
SMALL_N = [10, 20, 30, 50, 70, 90]
HORIZONS = [10, 20]
RUL_FAIL_PENALTY = 1000  # selection score: a "no crossing" answer counts as RUL 1000
FEATURE_SETS = {
    "charge": ["charge"], "impedance": ["impedance"], "cycle": ["cycle"],
    "charge+impedance": ["charge", "impedance"],
    "charge+impedance+cycle (default)": ["charge", "impedance", "cycle"],
    "default+charge_ah": ["charge", "charge_ah", "impedance", "cycle"],
    "history": ["history"],
    "default+history": ["charge", "impedance", "cycle", "history"],
    "all": ["charge", "charge_ah", "impedance", "cycle", "history"],
}
CLAIMS: list[dict] = []


def run_models(df, tr, te, features, target, tag: dict, scheme: str, models=MODEL_NAMES, seed=0, keep_pred=True,
               order_col="discharge_no", label_col=None):
    rows, preds = [], []
    Xtr, ytr, Xte, yte = df.loc[tr, features], df.loc[tr, target], df.loc[te, features], df.loc[te, target]
    for name in models:
        kw = fit_kwargs(name, df.loc[tr, "battery"], df.loc[tr, order_col], df.loc[tr, label_col or order_col])
        pred, timing = fit_predict(make_model(name, seed, scheme), Xtr, ytr, Xte, kw)
        rows.append({**tag, "model": name, "stacking_oof": scheme if name == "Stacking" else "", **scores(yte, pred), **timing})
        if keep_pred:
            preds.append(pd.DataFrame({**tag, "model": name, "battery": df.loc[te, "battery"].to_numpy(),
                                       "discharge_no": df.loc[te, "discharge_no"].to_numpy(),
                                       "y_true": yte.to_numpy(), "y_pred": pred}))
    return rows, preds


def claim(scenario, validation, held_out, df, tr, te, features, target, scheme, results_rows, ref=None,
          order_col="discharge_no", label_col=None):
    """Select with training rows only; record the selected model's already-computed test score."""
    chosen, val, n_folds = select_model(df.loc[tr], features, target, scheme, order_col=order_col, label_col=label_col)
    test = next(r for r in results_rows if r["model"] == chosen)
    CLAIMS.append({"scenario": scenario, "validation": validation, "held_out": held_out,
                   "selection": f"{'내부 LOBO' if scheme == 'group' else '학습 구간 뒤 20 % 검증'} ({n_folds} fold)",
                   "selected_model": chosen, "validation_MAE": json.dumps({k: round(v, 5) for k, v in val.items()}),
                   "test_MAE": test["MAE"], "test_RMSE": test["RMSE"], "test_R2": test["R2"], "n_test": test["n_test"],
                   **(ref or {})})
    return chosen


def persistence_row(df, te, target, tag):
    """Reference baseline: SOH(k) predicted by SOH(k-1). Scored on test rows that have a lag."""
    sub = df.loc[te]
    sub = sub[sub["soh_lag1"].notna()]
    return {**tag, "model": "Persistence(lag1)", **scores(sub[target], sub["soh_lag1"]),
            "fit_time_s": 0.0, "predict_time_s": 0.0, "n_train": 0}


# ---------------------------------------------------------------- A. random vs temporal
def exp_a(df):
    rows, preds = [], []
    for s in RANDOM_SEEDS:
        tr, te = random_split(df, 0.3, seed=s)
        r, p = run_models(df, tr, te, DEFAULT_FEATURES, TARGET, {"split": "random", "seed": s}, "random", seed=s)
        rows += r + [persistence_row(df, te, TARGET, {"split": "random", "seed": s})]
        preds += p
    tr, te = temporal_split(df, 0.7)
    r, p = run_models(df, tr, te, DEFAULT_FEATURES, TARGET, {"split": "temporal", "seed": 0}, "forward")
    pers = persistence_row(df, te, TARGET, {"split": "temporal", "seed": 0})
    rows += r + [pers]
    preds += p
    claim("현재 SOH (신호 특징)", "temporal", "all", df, tr, te, DEFAULT_FEATURES, TARGET, "forward", r,
          {"ref_persistence_MAE": pers["MAE"]})
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "exp_A_split_runs.csv", index=False)
    summ = (res.groupby(["split", "model"], sort=False)
            .agg(MAE=("MAE", "mean"), MAE_std=("MAE", "std"), RMSE=("RMSE", "mean"), R2=("R2", "mean"),
                 fit_time_s=("fit_time_s", "mean"), predict_time_s=("predict_time_s", "mean"),
                 n_test=("n_test", "first"), runs=("MAE", "size")).reset_index())
    summ.to_csv(OUT / "exp_A_split_comparison.csv", index=False)
    pd.concat(preds).to_csv(OUT / "exp_A_predictions.csv", index=False)

    fig, ax = plt.subplots(figsize=(7, 3.4))
    models = list(summ["model"].unique())
    x = np.arange(len(models))
    for j, (split, color) in enumerate([("random", MODEL_COLOR["LinearRegression"]), ("temporal", MODEL_COLOR["RandomForest"])]):
        s = summ[summ["split"] == split].set_index("model").reindex(models)
        ax.bar(x + (j - 0.5) * 0.36, s["MAE"], 0.34, color=color, label=f"{split} split")
        ax.errorbar(x + (j - 0.5) * 0.36, s["MAE"], yerr=s["MAE_std"].fillna(0), fmt="none", ecolor=INK, lw=0.8)
    ax.set_xticks(x, models, rotation=15)
    ax.set_ylabel("MAE (SOH, 초기용량 기준)")
    ax.set_title("A. Random split vs 시간순 분할 (기본 특징, 모든 후보 · 기술 통계)")
    ax.legend()
    save(fig, FIG / "exp_A_split_comparison.png")
    return summ


# ---------------------------------------------------------------- B. small data
def exp_b(df):
    rows = []
    sizes = SMALL_N + ["all_pre_test"]
    for n in sizes:
        tr, te = temporal_split(df, 0.7) if n == "all_pre_test" else small_data_split(df, n, 0.7)
        r, _ = run_models(df, tr, te, DEFAULT_FEATURES, TARGET, {"n_train_per_battery": n}, "forward", keep_pred=False)
        rows += r
        sel = claim(f"Small Data n={n}", "temporal", "all", df, tr, te, DEFAULT_FEATURES, TARGET, "forward", r)
        for row in r:
            row["selected_by_validation"] = row["model"] == sel
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "exp_B_small_data.csv", index=False)
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    labels = [str(n) for n in sizes]
    for m in MODEL_NAMES:
        s = res[res["model"] == m]
        ax.plot(labels, s["MAE"], marker="o", ms=4, color=MODEL_COLOR[m], label=m)
    sel = res[res["selected_by_validation"]]
    ax.scatter([str(n) for n in sel["n_train_per_battery"]], sel["MAE"], s=110, facecolors="none", edgecolors=INK,
               linewidths=1.2, label="학습 데이터로 선택된 모델", zorder=4)
    ax.set_xlabel("배터리당 학습 Cycle 수 (처음 N회 방전)")
    ax.set_ylabel("MAE (고정 테스트: 각 배터리 마지막 30 %)")
    ax.set_title("B. Small Data 실험")
    ax.legend(ncol=2, fontsize=7)
    save(fig, FIG / "exp_B_small_data.png")
    return res


# ---------------------------------------------------------------- C. leave-one-battery-out
def exp_c(df, target=TARGET, features=DEFAULT_FEATURES, suffix=""):
    rows, preds, chosen = [], [], {}
    for b, tr, te in lobo_splits(df, BATTERIES):
        r, p = run_models(df, tr, te, features, target, {"held_out": b}, "group")
        pers = persistence_row(df, te, target, {"held_out": b}) if target == "soh_init" else None
        rows += r + ([pers] if pers else [])
        preds += p
        if not suffix:
            chosen[b] = claim("현재 SOH (신호 특징)", "LOBO", b, df, tr, te, features, target, "group", r,
                              {"ref_persistence_MAE": pers["MAE"]})
    res = pd.DataFrame(rows)
    res.to_csv(OUT / f"exp_C_lobo{suffix}.csv", index=False)
    pred = pd.concat(preds)
    pred.to_csv(OUT / f"exp_C_lobo_predictions{suffix}.csv", index=False)
    if suffix:
        return res, pred
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.4), sharey=True)
    for ax, b in zip(axes.ravel(), BATTERIES):
        g = pred[(pred["battery"] == b) & (pred["model"] == "LinearRegression")]
        ax.plot(g["discharge_no"], g["y_true"], color=INK, lw=2, label="실측 SOH")
        for m in MODEL_NAMES:
            g = pred[(pred["battery"] == b) & (pred["model"] == m)]
            ax.plot(g["discharge_no"], g["y_pred"], color=MODEL_COLOR[m], lw=1.1, label=m)
        mae = res[(res["held_out"] == b) & (res["model"] == chosen[b])]["MAE"].iloc[0]
        ax.set_title(f"{b} (미학습) · 학습 데이터로 선택: {chosen[b]} (MAE {mae:.3f})")
        ax.set_xlabel("방전 Cycle")
        ax.set_ylabel("SOH (C/C₁)")
    axes[0, 0].legend(ncol=2, fontsize=7)
    fig.suptitle("C. Leave-One-Battery-Out: SOH 실측값 vs 예측값", fontsize=11)
    save(fig, FIG / "exp_C_lobo_soh_actual_vs_pred.png")
    return res, pred


def _scatter_actual_pred(pred, title, path):
    fig, axes = plt.subplots(1, len(MODEL_NAMES), figsize=(14, 3.2), sharex=True, sharey=True)
    for ax, m in zip(axes, MODEL_NAMES):
        g = pred[pred["model"] == m]
        for b in BATTERIES:
            gb = g[g["battery"] == b]
            ax.scatter(gb["y_true"], gb["y_pred"], s=9, color=BATTERY_COLOR[b], label=b, alpha=0.8, linewidths=0)
        lo, hi = pred[["y_true", "y_pred"]].min().min(), pred[["y_true", "y_pred"]].max().max()
        ax.plot([lo, hi], [lo, hi], color=MUTED, lw=1)
        ax.set_title(m, fontsize=9)
        ax.set_xlabel("실측 SOH")
    axes[0].set_ylabel("예측 SOH")
    axes[0].legend(fontsize=7)
    fig.suptitle(title, fontsize=11)
    save(fig, path)


# ---------------------------------------------------------------- D. stacking vs single
def exp_d(a_summ, b_res, c_res):
    """Stacking vs (i) the single model chosen with training data only and (ii) the post-hoc
    best single model (test-selected, descriptive only - never a performance claim)."""
    claims = pd.DataFrame(CLAIMS)
    rows = []

    def single_selected(scenario, validation):
        """Single model chosen on training data when Stacking is excluded from the candidates."""
        c = claims[(claims["scenario"] == scenario) & (claims["validation"] == validation)]
        out = []
        for _, r in c.iterrows():
            v = {k: val for k, val in json.loads(r["validation_MAE"]).items() if k in SINGLE_MODELS}
            out.append((r["held_out"], min(v, key=v.get)))
        return out

    t = a_summ[a_summ["split"] == "temporal"].set_index("model")
    sel = single_selected("현재 SOH (신호 특징)", "temporal")[0][1]
    rows.append({"setting": "A-temporal", "stacking_MAE": t.loc["Stacking", "MAE"],
                 "single_selected_by_validation": sel, "single_selected_test_MAE": t.loc[sel, "MAE"],
                 "mean_single_MAE": t.loc[SINGLE_MODELS, "MAE"].mean(),
                 "posthoc_best_single (descriptive)": t.loc[SINGLE_MODELS, "MAE"].idxmin(),
                 "posthoc_best_single_MAE (descriptive)": t.loc[SINGLE_MODELS, "MAE"].min()})
    c = c_res[c_res["model"].isin(MODEL_NAMES)]
    sel = dict(single_selected("현재 SOH (신호 특징)", "LOBO"))
    cm = c.groupby("model")["MAE"].mean()
    rows.append({"setting": "C-LOBO (4-fold mean)", "stacking_MAE": cm["Stacking"],
                 "single_selected_by_validation": json.dumps(sel),
                 "single_selected_test_MAE": np.mean([c[(c["held_out"] == b) & (c["model"] == m)]["MAE"].iloc[0] for b, m in sel.items()]),
                 "mean_single_MAE": cm[SINGLE_MODELS].mean(),
                 "posthoc_best_single (descriptive)": cm[SINGLE_MODELS].idxmin(),
                 "posthoc_best_single_MAE (descriptive)": cm[SINGLE_MODELS].min()})
    for n, g in b_res.groupby("n_train_per_battery", sort=False):
        g = g.set_index("model")
        sel = single_selected(f"Small Data n={n}", "temporal")[0][1]
        rows.append({"setting": f"B-small n={n}", "stacking_MAE": g.loc["Stacking", "MAE"],
                     "single_selected_by_validation": sel, "single_selected_test_MAE": g.loc[sel, "MAE"],
                     "mean_single_MAE": g.loc[SINGLE_MODELS, "MAE"].mean(),
                     "posthoc_best_single (descriptive)": g.loc[SINGLE_MODELS, "MAE"].idxmin(),
                     "posthoc_best_single_MAE (descriptive)": g.loc[SINGLE_MODELS, "MAE"].min()})
    res = pd.DataFrame(rows)
    res["stacking_minus_selected_single"] = res["stacking_MAE"] - res["single_selected_test_MAE"]
    res.to_csv(OUT / "exp_D_stacking_vs_single.csv", index=False)
    return res


# ---------------------------------------------------------------- E. feature sets (descriptive)
def exp_e(df):
    rows = []
    for name, groups in FEATURE_SETS.items():
        feats = feature_list(*groups)
        tr, te = temporal_split(df, 0.7)
        r, _ = run_models(df, tr, te, feats, TARGET, {"feature_set": name, "validation": "temporal"}, "forward", keep_pred=False)
        rows += r
        for b, trb, teb in lobo_splits(df, BATTERIES):
            r, _ = run_models(df, trb, teb, feats, TARGET, {"feature_set": name, "validation": "LOBO", "held_out": b}, "group", keep_pred=False)
            rows += r
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "exp_E_feature_sets_runs.csv", index=False)
    summ = res.groupby(["validation", "feature_set", "model"], sort=False)[["MAE", "RMSE", "R2"]].mean().reset_index()
    summ["n_features"] = summ["feature_set"].map(lambda s: len(feature_list(*FEATURE_SETS[s])))
    summ.to_csv(OUT / "exp_E_feature_sets.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
    sets = list(FEATURE_SETS)
    for ax, val in zip(axes, ["temporal", "LOBO"]):
        for k, m in enumerate(MODEL_NAMES):
            s = summ[(summ["validation"] == val) & (summ["model"] == m)].set_index("feature_set").reindex(sets)
            ax.scatter(s["MAE"], np.arange(len(sets)) + (k - 2) * 0.12, s=22, color=MODEL_COLOR[m], label=m, linewidths=0)
        ax.set_yticks(np.arange(len(sets)), sets)
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:g}"))
        ax.xaxis.set_minor_formatter(plt.FuncFormatter(lambda v, _: f"{v:g}" if round(v / 10 ** np.floor(np.log10(v))) in (2, 5) else ""))
        ax.set_xlabel("MAE (로그 눈금)")
        ax.set_title(f"E. 특징 조합 ({'시간순' if val == 'temporal' else 'LOBO 평균'}) · 기술 통계")
    axes[0].invert_yaxis()
    axes[1].legend(fontsize=7)
    save(fig, FIG / "exp_E_feature_sets.png")
    return summ


# ---------------------------------------------------------------- future SOH
def _history_extrapolation(df, pairs, horizon, window=20):
    out = np.full(len(pairs), np.nan)
    for b, g in df.groupby("battery"):
        g = g.sort_values("discharge_no")
        no, soh = g["discharge_no"].to_numpy(), g["soh_init"].to_numpy()
        for i in pairs.index[pairs["battery"] == b]:
            k = pairs.at[i, "origin_no"]
            m = no <= k
            x, y = no[m][-window:], soh[m][-window:]
            if x.size >= 3:
                s, c = np.polyfit(x, y, 1)
                out[pairs.index.get_loc(i)] = s * (k + horizon) + c
    return out


def exp_future(df):
    rows, preds = [], []
    for h in HORIZONS:
        pairs = make_future_pairs(df, h, ALL_FEATURES, TARGET)
        pairs["extrap"] = _history_extrapolation(df, pairs, h)
        pair_df = pairs.rename(columns={"y": "target_y"})  # keeps discharge_no (= origin) as a feature
        schemes = [("temporal", "forward", "all", *temporal_split_pairs(pairs, df, 0.7))]
        schemes += [("LOBO", "group", b, pairs.index[pairs["battery"] != b], pairs.index[pairs["battery"] == b]) for b in BATTERIES]
        for validation, scheme, held, tr, te in schemes:
            tag = {"horizon": h, "validation": validation, "held_out": held}
            r, p = run_models(pair_df, tr, te, ALL_FEATURES, "target_y", tag, scheme, order_col="origin_no", label_col="target_no")
            for pp in p:
                pp["origin_no"] = pairs.loc[te, "origin_no"].to_numpy()
                pp["target_no"] = pairs.loc[te, "target_no"].to_numpy()
            rows += r
            preds += p
            ref = {}
            for base, col in [("Persistence(SOH_k)", "y_origin"), ("LinearExtrap(last20)", "extrap")]:
                sub = pairs.loc[te]
                sub = sub[sub[col].notna()]
                row = {**tag, "model": base, **scores(sub["y"], sub[col]), "fit_time_s": 0.0, "predict_time_s": 0.0, "n_train": 0}
                rows.append(row)
                ref[f"ref_{base}_MAE"] = row["MAE"]
            claim(f"미래 SOH +{h}", validation, held, pair_df, tr, te, ALL_FEATURES, "target_y", scheme, r, ref,
                  order_col="origin_no", label_col="target_no")
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "future_soh_runs.csv", index=False)
    summ = res.groupby(["horizon", "validation", "model"], sort=False)[["MAE", "RMSE", "R2", "n_test"]].agg(
        {"MAE": "mean", "RMSE": "mean", "R2": "mean", "n_test": "sum"}).reset_index()
    summ.to_csv(OUT / "future_soh.csv", index=False)
    pred = pd.concat(preds)
    pred.to_csv(OUT / "future_soh_predictions.csv", index=False)
    fig, axes = plt.subplots(len(HORIZONS), 4, figsize=(13, 5.8), sharey=True)
    for i, h in enumerate(HORIZONS):
        for j, b in enumerate(BATTERIES):
            ax = axes[i, j]
            g0 = df[df["battery"] == b]
            ax.plot(g0["discharge_no"], g0["soh_init"], color=INK, lw=2, label="실측 SOH")
            for m in ["LinearRegression", "XGBoost", "Stacking"]:
                g = pred[(pred["horizon"] == h) & (pred["validation"] == "LOBO") & (pred["battery"] == b) & (pred["model"] == m)]
                ax.plot(g["target_no"], g["y_pred"], color=MODEL_COLOR[m], lw=1.1, label=m)
            ax.set_title(f"{b} · +{h} Cycle (LOBO)", fontsize=9)
            if i == len(HORIZONS) - 1:
                ax.set_xlabel("예측 대상 방전 Cycle")
        axes[i, 0].set_ylabel("SOH")
    axes[0, 0].legend(fontsize=7)
    fig.suptitle("미래 SOH 예측 (k 시점 정보 → k+h Cycle SOH), 미학습 배터리", fontsize=11)
    save(fig, FIG / "future_soh_lobo.png")
    return summ


# ---------------------------------------------------------------- RUL
EXTRAP_METHODS = {"LinearExtrap(all)": None, "LinearExtrap(last30)": 30}


def _extrap_preds(df, b, eol, start=20):
    g = df[df["battery"] == b].sort_values("discharge_no")
    no, cap = g["discharge_no"].to_numpy(), g["capacity_ah"].to_numpy()
    last = eol if eol is not None else no[-1]
    out = []
    for k in range(start, last + 1):
        m = no <= k
        for method, w in EXTRAP_METHODS.items():
            out.append({"battery": b, "origin_no": k, "method": method,
                        "rul_true": (eol - k) if eol is not None else np.nan,
                        "rul_pred": extrapolate_rul(no[m], cap[m], EOL_AH, window=w)})
    return out


def _rul_select(lab, train_batteries, eols):
    """Pick a RUL method using only the training batteries: each ML candidate is trained on
    one training battery and scored on the other (both directions); extrapolation methods are
    scored directly on the training batteries. 'No crossing' counts as RUL_FAIL_PENALTY."""
    score = {}
    for name in MODEL_NAMES:
        maes = []
        for v in train_batteries:
            a = lab[(lab["battery"].isin(train_batteries)) & (lab["battery"] != v)]
            c = lab[(lab["battery"] == v) & (lab["discharge_no"] >= 20)]
            kw = fit_kwargs(name, a["battery"], a["discharge_no"], a["discharge_no"])
            pred, _ = fit_predict(make_model(name, scheme="group"), a[ALL_FEATURES], a["rul"], c[ALL_FEATURES], kw)
            maes.append(scores(c["rul"], pred)["MAE"])
        score[f"ML-{name}"] = float(np.mean(maes))
    for method in EXTRAP_METHODS:
        p = pd.DataFrame([r for v in train_batteries for r in _extrap_preds(lab, v, eols[v]) if r["method"] == method])
        rp = np.where(np.isfinite(p["rul_pred"]), p["rul_pred"], RUL_FAIL_PENALTY)
        score[method] = float(np.mean(np.abs(rp - p["rul_true"])))
    return min(score, key=score.get), score


def exp_rul(df):
    df, eols = add_rul(df, EOL_AH)
    labeled = [b for b in BATTERIES if eols[b] is not None]
    preds = []
    for b in BATTERIES:
        preds += _extrap_preds(df, b, eols[b])
    lab = df[df["battery"].isin(labeled) & df["rul"].notna()]
    for b in labeled:  # ML: train on the other labeled batteries
        tr, te = lab.index[lab["battery"] != b], lab.index[(lab["battery"] == b) & (lab["discharge_no"] >= 20)]
        for name in MODEL_NAMES:
            kw = fit_kwargs(name, lab.loc[tr, "battery"], lab.loc[tr, "discharge_no"], lab.loc[tr, "discharge_no"])
            pred, timing = fit_predict(make_model(name, scheme="group"), lab.loc[tr, ALL_FEATURES], lab.loc[tr, "rul"], lab.loc[te, ALL_FEATURES], kw)
            for k, rt, rp in zip(lab.loc[te, "discharge_no"], lab.loc[te, "rul"], pred):
                preds.append({"battery": b, "origin_no": int(k), "method": f"ML-{name}", "rul_true": rt, "rul_pred": float(rp),
                              "fit_time_s": timing["fit_time_s"]})
    for b in [x for x in BATTERIES if eols[x] is None]:  # censored: trained on all labeled, checked against the bound
        te = df.index[(df["battery"] == b) & (df["discharge_no"] >= 20)]
        for name in MODEL_NAMES:
            kw = fit_kwargs(name, lab["battery"], lab["discharge_no"], lab["discharge_no"])
            pred, _ = fit_predict(make_model(name, scheme="group"), lab[ALL_FEATURES], lab["rul"], df.loc[te, ALL_FEATURES], kw)
            for k, rp in zip(df.loc[te, "discharge_no"], pred):
                preds.append({"battery": b, "origin_no": int(k), "method": f"ML-{name}", "rul_true": np.nan, "rul_pred": float(rp)})
    p = pd.DataFrame(preds)
    p["eol_true"] = p["battery"].map(lambda b: eols[b] if eols[b] is not None else np.nan)
    p["eol_pred"] = p["origin_no"] + p["rul_pred"]
    p.to_csv(OUT / "rul_predictions.csv", index=False)
    last_obs = df.groupby("battery")["discharge_no"].max().to_dict()
    res = rul_summary(p, eols, last_obs)
    res.to_csv(OUT / "rul_results.csv", index=False)
    # training-only method selection per held-out labeled battery
    for b in labeled:
        train_b = [x for x in labeled if x != b]
        chosen, score = _rul_select(lab, train_b, eols)
        r = res[(res["battery"] == b) & (res["method"] == chosen)].iloc[0]
        CLAIMS.append({"scenario": "RUL (1.4 Ah)", "validation": "labeled-LOBO", "held_out": b,
                       "selection": f"학습 배터리 {'/'.join(train_b)} 간 교차 검증 (교차 실패=RUL {RUL_FAIL_PENALTY})",
                       "selected_model": chosen, "validation_MAE": json.dumps({k: round(v, 2) for k, v in score.items()}),
                       "test_MAE": r["MAE_success_only"], "test_RMSE": r["RMSE_success_only"], "test_R2": np.nan,
                       "n_test": r["n_origins"], "success_rate": r["success_rate"], "n_fail_no_crossing": r["n_fail_no_crossing"],
                       "test_MAE_fail_penalized": r["MAE_fail_penalized"]})
    write_json({"eol_threshold_ah": EOL_AH, "eol_cycle": eols, "last_observed": last_obs}, OUT / "rul_eol.json")

    fig, ax = plt.subplots(figsize=(7, 3.8))
    for b in BATTERIES:
        g = df[df["battery"] == b]
        ax.plot(g["discharge_no"], g["capacity_ah"], color=BATTERY_COLOR[b], label=b)
        if eols[b] is not None:
            ax.scatter([eols[b]], [g.loc[g["discharge_no"] == eols[b], "capacity_ah"].iloc[0]], s=40,
                       color=BATTERY_COLOR[b], edgecolors="white", linewidths=1.5, zorder=3)
            ax.annotate(f"EOL #{eols[b]}", (eols[b], EOL_AH), textcoords="offset points", xytext=(-10, -14), fontsize=7, color=INK)
    ax.axhline(EOL_AH, color=MUTED, lw=1)
    ax.text(2, EOL_AH + 0.01, "EOL 1.4 Ah", fontsize=7, color=MUTED)
    ax.set_xlabel("방전 Cycle")
    ax.set_ylabel("방전 용량 (Ah)")
    ax.set_title("방전 용량과 EOL(1.4 Ah) 도달 시점 · B0007은 미도달(중도절단)")
    ax.legend()
    save(fig, FIG / "rul_capacity_eol.png")

    fig, axes = plt.subplots(1, 4, figsize=(14, 3.8))
    show = [("LinearExtrap(all)", MODEL_COLOR["LinearRegression"]), ("LinearExtrap(last30)", MODEL_COLOR["RandomForest"]),
            ("ML-XGBoost", MODEL_COLOR["XGBoost"]), ("ML-Stacking", MODEL_COLOR["Stacking"])]
    for ax, b in zip(axes, BATTERIES):
        g = p[p["battery"] == b]
        if eols[b] is not None:
            gt = g[g["method"] == "LinearExtrap(all)"]
            ax.plot(gt["origin_no"], gt["rul_true"], color=INK, lw=2, label="실제 RUL")
        else:
            ks = np.arange(20, last_obs[b] + 1)
            ax.fill_between(ks, last_obs[b] - ks, 250, color="#e1e0d9", label="관측과 일치하는 RUL 범위")
        notes = []
        for method, color in show:
            gm = g[g["method"] == method]
            fin = np.isfinite(gm["rul_pred"])
            ax.plot(gm["origin_no"], gm["rul_pred"].where(fin).clip(upper=250), color=color, lw=1.1, label=method)
            if (~fin).any():
                ax.scatter(gm.loc[~fin, "origin_no"], np.full((~fin).sum(), 248), marker="x", s=14, color=color, linewidths=1)
                notes.append(f"{method}: 교차 실패 {(~fin).sum()}/{len(gm)} (×)")
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.set_ylim(min(-10, float(np.nanmin(g["rul_pred"].where(np.isfinite(g["rul_pred"])))) - 5), 255)  # keep negative RUL predictions visible
        ax.set_title(b + ("" if eols[b] is not None else " (EOL 미관측)"), fontsize=9)
        ax.set_xlabel("예측 시점 (방전 Cycle)")
        if notes:
            ax.text(0.02, 0.02, "\n".join(notes), transform=ax.transAxes, fontsize=6.5, color=INK, va="bottom")
    axes[0].set_ylabel("RUL (Cycle, 250에서 잘림)")
    axes[0].legend(fontsize=7, loc="upper right")
    fig.suptitle("RUL 예측: 실제 잔여 Cycle vs 예측 (× = 1000 Cycle 안에 EOL 교차 없음)", fontsize=11)
    save(fig, FIG / "rul_prediction.png")
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    CLAIMS.clear()
    timings = {}
    t0 = time.perf_counter()
    df, logs = build_nasa_table(BATTERIES)
    (ROOT / "data" / "processed").mkdir(parents=True, exist_ok=True)
    df.to_csv(ROOT / "data" / "processed" / "nasa_features.csv", index=False)
    feats = sorted({c for g in FEATURE_GROUPS.values() for c in g})
    df.groupby("battery")[feats].apply(lambda x: x.isna().sum()).T.to_csv(OUT / "preprocessing_missing_by_feature.csv")
    write_json({"rules": {
        "charge_samples": "비유한(NaN/inf) 샘플은 해당 충전 특징 계산에서만 제외 (원본 불변)",
        "charge_validity": "CC 시작(I>1.0A), 4.195V 도달, 총 충전량>=1.0Ah 중 하나라도 실패하면 해당 충전 특징 전체 NaN",
        "impedance_validity": "Re, Rct가 유한하고 (0,1) Ohm 범위일 때만 사용, 아니면 건너뛰고 직전 유효값 유지",
        "missing_features": "모델 내부 SimpleImputer(median)가 학습 데이터에서만 적합 (XGBoost는 NaN 직접 처리)",
        "capacity": "Capacity<=0 또는 NaN 방전 행 제거 (우선 셀에서는 0건)"},
        "counts_by_battery": logs, "rows_after": df.groupby("battery").size().to_dict()}, OUT / "preprocessing_log.json")
    timings["features"] = time.perf_counter() - t0
    out = {}
    for k, f in [("A", lambda: exp_a(df)), ("B", lambda: exp_b(df)), ("C", lambda: exp_c(df))]:
        t = time.perf_counter()
        out[k] = f()
        timings[f"exp_{k}"] = time.perf_counter() - t
        print(f"exp {k} done in {timings[f'exp_{k}']:.1f}s", flush=True)
    _scatter_actual_pred(pd.read_csv(OUT / "exp_C_lobo_predictions.csv"), "C. LOBO 실측 vs 예측 (모든 배터리)", FIG / "exp_C_lobo_scatter.png")
    t = time.perf_counter()
    out["D"] = exp_d(out["A"], out["B"], out["C"][0])
    timings["exp_D"] = time.perf_counter() - t
    t = time.perf_counter()
    sup = []
    tr, te = temporal_split(df, 0.7)
    r, _ = run_models(df, tr, te, DEFAULT_FEATURES, "soh_rated", {"validation": "temporal", "held_out": "all"}, "forward", keep_pred=False)
    sup += r
    sup += exp_c(df, target="soh_rated", suffix="_soh_rated")[0].assign(validation="LOBO").to_dict("records")
    pd.DataFrame(sup).to_csv(OUT / "supp_soh_rated_target.csv", index=False)
    timings["supp_soh_rated"] = time.perf_counter() - t
    for k, f in [("E", lambda: exp_e(df)), ("future", lambda: exp_future(df)), ("rul", lambda: exp_rul(df))]:
        t = time.perf_counter()
        out[k] = f()
        timings[f"exp_{k}"] = time.perf_counter() - t
        print(f"exp {k} done in {timings[f'exp_{k}']:.1f}s", flush=True)
    claims = pd.DataFrame(CLAIMS)
    claims.to_csv(OUT / "final_claims.csv", index=False)
    agg = claims.groupby(["scenario", "validation"], sort=False).agg(
        test_MAE_mean=("test_MAE", "mean"), folds=("test_MAE", "size"),
        selected=("selected_model", lambda s: ", ".join(s))).reset_index()
    agg.to_csv(OUT / "final_claims_summary.csv", index=False)
    timings["total"] = time.perf_counter() - t0
    write_json({"version": "v2 (audit)", "target": TARGET, "default_features": DEFAULT_FEATURES, "all_features": ALL_FEATURES,
               "feature_groups": FEATURE_GROUPS, "hyperparams": HYPERPARAMS, "random_seeds": RANDOM_SEEDS,
               "temporal_train_frac": 0.7, "small_n": SMALL_N, "horizons": HORIZONS, "eol_ah": EOL_AH,
               "tuning": "없음 (사전 고정 하이퍼파라미터)",
               "model_selection": "학습 데이터 내부 검증만 사용 (final_claims.csv). 모든 후보 표는 기술 통계",
               "timings_s": timings}, OUT / "run_config.json")
    print(json.dumps(timings, indent=1))


if __name__ == "__main__":
    main()
