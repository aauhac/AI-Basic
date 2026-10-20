"""NASA SOH / RUL experiments A-E, future-SOH and RUL. All outputs go to results/nasa/.

Usage: .venv/Scripts/python -m experiments.nasa_experiments
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.evaluation.metrics import fit_predict, scores
from src.evaluation.rul import EOL_AH, add_rul, extrapolate_rul
from src.evaluation.splits import (lobo_splits, make_future_pairs, random_split, small_data_split,
                                   split_point, temporal_split, temporal_split_pairs)
from src.features.nasa_features import FEATURE_GROUPS, build_nasa_table, feature_list
from src.models.zoo import HYPERPARAMS, MODEL_NAMES, SINGLE_MODELS, make_model
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
FEATURE_SETS = {
    "charge": ["charge"], "impedance": ["impedance"], "cycle": ["cycle"],
    "charge+impedance": ["charge", "impedance"],
    "charge+impedance+cycle (default)": ["charge", "impedance", "cycle"],
    "default+charge_ah": ["charge", "charge_ah", "impedance", "cycle"],
    "history": ["history"],
    "default+history": ["charge", "impedance", "cycle", "history"],
    "all": ["charge", "charge_ah", "impedance", "cycle", "history"],
}


def run_models(df, tr, te, features, target, tag: dict, models=MODEL_NAMES, seed=0, keep_pred=True):
    rows, preds = [], []
    Xtr, ytr, Xte, yte = df.loc[tr, features], df.loc[tr, target], df.loc[te, features], df.loc[te, target]
    for name in models:
        pred, timing = fit_predict(make_model(name, seed), Xtr, ytr, Xte)
        rows.append({**tag, "model": name, **scores(yte, pred), **timing})
        if keep_pred:
            preds.append(pd.DataFrame({**tag, "model": name, "battery": df.loc[te, "battery"].to_numpy(),
                                       "discharge_no": df.loc[te, "discharge_no"].to_numpy(),
                                       "y_true": yte.to_numpy(), "y_pred": pred}))
    return rows, preds


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
        r, p = run_models(df, tr, te, DEFAULT_FEATURES, TARGET, {"split": "random", "seed": s}, seed=s)
        rows += r + [persistence_row(df, te, TARGET, {"split": "random", "seed": s})]
        preds += p
    tr, te = temporal_split(df, 0.7)
    r, p = run_models(df, tr, te, DEFAULT_FEATURES, TARGET, {"split": "temporal", "seed": 0})
    rows += r + [persistence_row(df, te, TARGET, {"split": "temporal", "seed": 0})]
    preds += p
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "exp_A_split_runs.csv", index=False)
    summ = (res.groupby(["split", "model"], sort=False)
            .agg(MAE=("MAE", "mean"), MAE_std=("MAE", "std"), RMSE=("RMSE", "mean"), R2=("R2", "mean"),
                 fit_time_s=("fit_time_s", "mean"), predict_time_s=("predict_time_s", "mean"),
                 n_test=("n_test", "first"), runs=("MAE", "size")).reset_index())
    summ.to_csv(OUT / "exp_A_split_comparison.csv", index=False)
    pd.concat(preds).to_csv(OUT / "exp_A_predictions.csv", index=False)

    fig, ax = plt.subplots(figsize=(7, 3.4))
    models = [m for m in summ["model"].unique()]
    x = np.arange(len(models))
    for j, (split, color) in enumerate([("random", MODEL_COLOR["LinearRegression"]), ("temporal", MODEL_COLOR["RandomForest"])]):
        s = summ[summ["split"] == split].set_index("model").reindex(models)
        ax.bar(x + (j - 0.5) * 0.36, s["MAE"], 0.34, color=color, label=f"{split} split")
        ax.errorbar(x + (j - 0.5) * 0.36, s["MAE"], yerr=s["MAE_std"].fillna(0), fmt="none", ecolor=INK, lw=0.8)
    ax.set_xticks(x, models, rotation=15)
    ax.set_ylabel("MAE (SOH, 초기용량 기준)")
    ax.set_title("A. Random split vs 시간순 분할 (기본 특징)")
    ax.legend()
    save(fig, FIG / "exp_A_split_comparison.png")
    return summ


# ---------------------------------------------------------------- B. small data
def exp_b(df):
    rows = []
    sizes = SMALL_N + ["all_pre_test"]
    for n in sizes:
        tr, te = temporal_split(df, 0.7) if n == "all_pre_test" else small_data_split(df, n, 0.7)
        r, _ = run_models(df, tr, te, DEFAULT_FEATURES, TARGET, {"n_train_per_battery": n}, keep_pred=False)
        rows += r
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "exp_B_small_data.csv", index=False)
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    labels = [str(n) for n in sizes]
    for m in MODEL_NAMES:
        s = res[res["model"] == m]
        ax.plot(labels, s["MAE"], marker="o", ms=4, color=MODEL_COLOR[m], label=m)
    ax.set_xlabel("배터리당 학습 Cycle 수 (처음 N회 방전)")
    ax.set_ylabel("MAE (고정 테스트: 각 배터리 마지막 30 %)")
    ax.set_title("B. Small Data 실험")
    ax.legend(ncol=2)
    save(fig, FIG / "exp_B_small_data.png")
    return res


# ---------------------------------------------------------------- C. leave-one-battery-out
def exp_c(df, target=TARGET, features=DEFAULT_FEATURES, suffix=""):
    rows, preds = [], []
    for b, tr, te in lobo_splits(df, BATTERIES):
        r, p = run_models(df, tr, te, features, target, {"held_out": b})
        rows += r + [persistence_row(df, te, target, {"held_out": b})] if target == "soh_init" else r
        preds += p
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
        mae = res[(res["held_out"] == b) & (res["model"].isin(MODEL_NAMES))].set_index("model")["MAE"]
        ax.set_title(f"{b} (미학습) · 최저 MAE {mae.min():.3f} {mae.idxmin()}")
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


# ---------------------------------------------------------------- D. stacking vs single (with fair selection)
def _inner_select(df, tr, features, target, scheme):
    """Choose a single model using only training rows: temporal -> last 20 % of each battery's
    training cycles as validation; lobo -> inner leave-one-battery-out on the training batteries."""
    sub = df.loc[tr]
    val_mae = {m: [] for m in SINGLE_MODELS}
    if scheme == "temporal":
        itr, iva = temporal_split(sub, 0.8)
        folds = [(itr, iva)]
    else:
        folds = [(a, c) for _, a, c in lobo_splits(sub)]
    for a, c in folds:
        for m in SINGLE_MODELS:
            pred, _ = fit_predict(make_model(m), sub.loc[a, features], sub.loc[a, target], sub.loc[c, features])
            val_mae[m].append(scores(sub.loc[c, target], pred)["MAE"])
    mean = {m: float(np.mean(v)) for m, v in val_mae.items()}
    return min(mean, key=mean.get), mean


def exp_d(df, a_summ, b_res, c_res):
    rows = []
    t = a_summ[a_summ["split"] == "temporal"].set_index("model")
    tr, _ = temporal_split(df, 0.7)
    chosen, val = _inner_select(df, tr, DEFAULT_FEATURES, TARGET, "temporal")
    rows.append({"setting": "A-temporal", "stacking_MAE": t.loc["Stacking", "MAE"],
                 "best_single_posthoc": t.loc[SINGLE_MODELS, "MAE"].idxmin(),
                 "best_single_posthoc_MAE": t.loc[SINGLE_MODELS, "MAE"].min(),
                 "mean_single_MAE": t.loc[SINGLE_MODELS, "MAE"].mean(),
                 "selected_by_validation": chosen, "selected_test_MAE": t.loc[chosen, "MAE"],
                 "validation_MAE": json.dumps({k: round(v, 4) for k, v in val.items()})})
    c = c_res[c_res["model"].isin(MODEL_NAMES)].groupby("model")["MAE"].mean()
    sel = {}
    for b, trb, _ in lobo_splits(df, BATTERIES):
        sel[b] = _inner_select(df, trb, DEFAULT_FEATURES, TARGET, "lobo")[0]
    sel_mae = np.mean([c_res[(c_res["held_out"] == b) & (c_res["model"] == m)]["MAE"].iloc[0] for b, m in sel.items()])
    rows.append({"setting": "C-LOBO (4-fold mean)", "stacking_MAE": c["Stacking"],
                 "best_single_posthoc": c[SINGLE_MODELS].idxmin(), "best_single_posthoc_MAE": c[SINGLE_MODELS].min(),
                 "mean_single_MAE": c[SINGLE_MODELS].mean(), "selected_by_validation": json.dumps(sel),
                 "selected_test_MAE": sel_mae, "validation_MAE": ""})
    for n, g in b_res.groupby("n_train_per_battery", sort=False):
        g = g.set_index("model")
        rows.append({"setting": f"B-small n={n}", "stacking_MAE": g.loc["Stacking", "MAE"],
                     "best_single_posthoc": g.loc[SINGLE_MODELS, "MAE"].idxmin(),
                     "best_single_posthoc_MAE": g.loc[SINGLE_MODELS, "MAE"].min(),
                     "mean_single_MAE": g.loc[SINGLE_MODELS, "MAE"].mean()})
    res = pd.DataFrame(rows)
    res["stacking_minus_best_single"] = res["stacking_MAE"] - res["best_single_posthoc_MAE"]
    res.to_csv(OUT / "exp_D_stacking_vs_single.csv", index=False)
    return res


# ---------------------------------------------------------------- E. feature sets
def exp_e(df):
    rows = []
    for name, groups in FEATURE_SETS.items():
        feats = feature_list(*groups)
        tr, te = temporal_split(df, 0.7)
        r, _ = run_models(df, tr, te, feats, TARGET, {"feature_set": name, "validation": "temporal"}, keep_pred=False)
        rows += r
        for b, trb, teb in lobo_splits(df, BATTERIES):
            r, _ = run_models(df, trb, teb, feats, TARGET, {"feature_set": name, "validation": "LOBO", "held_out": b}, keep_pred=False)
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
        ax.set_title(f"E. 특징 조합 ({'시간순' if val == 'temporal' else 'LOBO 평균'})")
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
        schemes = [("temporal", *temporal_split_pairs(pairs, df, 0.7))]
        schemes += [("LOBO", pairs.index[pairs["battery"] != b], pairs.index[pairs["battery"] == b]) for b in BATTERIES]
        for k, (scheme, tr, te) in enumerate(schemes):
            held = BATTERIES[k - 1] if scheme == "LOBO" else "all"
            tag = {"horizon": h, "validation": scheme, "held_out": held}
            pair_df = pairs.rename(columns={"y": "target_y"})  # keeps discharge_no (= origin) as a feature
            r, p = run_models(pair_df, tr, te, ALL_FEATURES, "target_y", tag)
            for pp in p:
                pp["origin_no"] = pairs.loc[te, "origin_no"].to_numpy()
                pp["target_no"] = pairs.loc[te, "target_no"].to_numpy()
            rows += r
            preds += p
            for base, col in [("Persistence(SOH_k)", "y_origin"), ("LinearExtrap(last20)", "extrap")]:
                sub = pairs.loc[te]
                sub = sub[sub[col].notna()]
                rows.append({**tag, "model": base, **scores(sub["y"], sub[col]), "fit_time_s": 0.0, "predict_time_s": 0.0, "n_train": 0})
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
def exp_rul(df):
    df, eols = add_rul(df, EOL_AH)
    labeled = [b for b in BATTERIES if eols[b] is not None]
    rows, preds = [], []
    # (1) history-only line extrapolation
    for b in BATTERIES:
        g = df[df["battery"] == b].sort_values("discharge_no")
        no, cap = g["discharge_no"].to_numpy(), g["capacity_ah"].to_numpy()
        last = eols[b] if eols[b] is not None else no[-1]
        for k in range(20, last + 1):
            m = no <= k
            for method, w in [("LinearExtrap(all)", None), ("LinearExtrap(last30)", 30)]:
                preds.append({"battery": b, "origin_no": k, "method": method,
                              "rul_true": (eols[b] - k) if eols[b] is not None else np.nan,
                              "rul_pred": extrapolate_rul(no[m], cap[m], EOL_AH, window=w)})
    # (2) ML direct RUL regression, leave-one-labeled-battery-out (train on the other 2 labeled)
    lab = df[df["battery"].isin(labeled) & df["rul"].notna()]
    for b in labeled:
        tr, te = lab.index[lab["battery"] != b], lab.index[(lab["battery"] == b) & (lab["discharge_no"] >= 20)]
        for name in MODEL_NAMES:
            pred, timing = fit_predict(make_model(name), lab.loc[tr, ALL_FEATURES], lab.loc[tr, "rul"], lab.loc[te, ALL_FEATURES])
            for k, rt, rp in zip(lab.loc[te, "discharge_no"], lab.loc[te, "rul"], pred):
                preds.append({"battery": b, "origin_no": int(k), "method": f"ML-{name}", "rul_true": rt, "rul_pred": float(rp),
                              "fit_time_s": timing["fit_time_s"]})
    # (3) censored B0007: models trained on all labeled batteries, checked only against the bound
    for b in [x for x in BATTERIES if eols[x] is None]:
        te = df.index[(df["battery"] == b) & (df["discharge_no"] >= 20)]
        for name in MODEL_NAMES:
            pred, _ = fit_predict(make_model(name), lab[ALL_FEATURES], lab["rul"], df.loc[te, ALL_FEATURES])
            for k, rp in zip(df.loc[te, "discharge_no"], pred):
                preds.append({"battery": b, "origin_no": int(k), "method": f"ML-{name}", "rul_true": np.nan, "rul_pred": float(rp)})
    p = pd.DataFrame(preds)
    p["eol_true"] = p["battery"].map(lambda b: eols[b] if eols[b] is not None else np.nan)
    p["eol_pred"] = p["origin_no"] + p["rul_pred"]
    p.to_csv(OUT / "rul_predictions.csv", index=False)
    last_obs = df.groupby("battery")["discharge_no"].max().to_dict()
    for (b, method), g in p.groupby(["battery", "method"], sort=False):
        if eols[b] is not None:
            fin = g[np.isfinite(g["rul_pred"])]
            e = eols[b]
            at = {}
            for frac in (0.25, 0.5, 0.75):
                k = max(20, int(round(e * frac)))
                gk = g[g["origin_no"] == k]
                at[f"abs_err_at_{int(frac * 100)}pct_life"] = float(abs(gk["rul_pred"] - gk["rul_true"]).iloc[0]) if len(gk) else np.nan
            rows.append({"battery": b, "method": method, "status": "EOL observed", "eol_true": e,
                         "n_origins": len(g), "n_no_crossing": int((~np.isfinite(g["rul_pred"])).sum()),
                         **scores(fin["rul_true"], fin["rul_pred"]), **at})
        else:
            fin = g[np.isfinite(g["rul_pred"])]
            contradicted = int((fin["eol_pred"] <= last_obs[b]).sum())
            rows.append({"battery": b, "method": method, "status": f"censored (no EOL by #{last_obs[b]})",
                         "eol_true": np.nan, "n_origins": len(g), "n_no_crossing": int((~np.isfinite(g["rul_pred"])).sum()),
                         "pred_eol_le_last_observed": contradicted,
                         "share_contradicted": contradicted / len(g)})
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "rul_results.csv", index=False)
    json.dump({"eol_threshold_ah": EOL_AH, "eol_cycle": eols, "last_observed": last_obs},
              open(OUT / "rul_eol.json", "w"), indent=2)

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

    fig, axes = plt.subplots(1, 4, figsize=(14, 3.6))
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
        for method, color in show:
            gm = g[g["method"] == method]
            ax.plot(gm["origin_no"], gm["rul_pred"].clip(upper=250), color=color, lw=1.1, label=method)
        ax.set_ylim(-5, 250)
        ax.set_title(b + ("" if eols[b] is not None else " (EOL 미관측)"), fontsize=9)
        ax.set_xlabel("예측 시점 (방전 Cycle)")
    axes[0].set_ylabel("RUL (Cycle)")
    axes[0].legend(fontsize=7)
    fig.suptitle("RUL 예측: 실제 잔여 Cycle vs 예측", fontsize=11)
    save(fig, FIG / "rul_prediction.png")
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    timings = {}
    t0 = time.perf_counter()
    df, logs = build_nasa_table(BATTERIES)
    (ROOT / "data" / "processed").mkdir(parents=True, exist_ok=True)
    df.to_csv(ROOT / "data" / "processed" / "nasa_features.csv", index=False)
    feats = sorted({c for g in FEATURE_GROUPS.values() for c in g})
    missing = df.groupby("battery")[feats].apply(lambda x: x.isna().sum()).T
    missing.to_csv(OUT / "preprocessing_missing_by_feature.csv")
    json.dump({"rules": {
        "charge_samples": "비유한(NaN/inf) 샘플은 해당 충전 특징 계산에서만 제외 (원본 불변)",
        "charge_validity": "CC 시작(I>1.0A), 4.195V 도달, 총 충전량>=1.0Ah 중 하나라도 실패하면 해당 충전 특징 전체 NaN",
        "impedance_validity": "Re, Rct가 유한하고 (0,1) Ohm 범위일 때만 사용, 아니면 건너뛰고 직전 유효값 유지",
        "missing_features": "모델 내부 SimpleImputer(median)가 학습 데이터에서만 적합 (XGBoost는 NaN 직접 처리)",
        "capacity": "Capacity<=0 또는 NaN 방전 행 제거 (우선 셀에서는 0건)"},
        "counts_by_battery": logs, "rows_after": df.groupby("battery").size().to_dict()},
        open(OUT / "preprocessing_log.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    timings["features"] = time.perf_counter() - t0

    steps = [("A", lambda: exp_a(df)), ("B", lambda: exp_b(df)), ("C", lambda: exp_c(df))]
    out = {}
    for k, f in steps:
        t = time.perf_counter()
        out[k] = f()
        timings[f"exp_{k}"] = time.perf_counter() - t
        print(f"exp {k} done in {timings[f'exp_{k}']:.1f}s", flush=True)
    _scatter_actual_pred(pd.read_csv(OUT / "exp_C_lobo_predictions.csv"), "C. LOBO 실측 vs 예측 (모든 배터리)", FIG / "exp_C_lobo_scatter.png")
    t = time.perf_counter()
    out["D"] = exp_d(df, out["A"], out["B"], out["C"][0])
    timings["exp_D"] = time.perf_counter() - t
    # supplementary: rated-capacity SOH target
    t = time.perf_counter()
    sup = []
    tr, te = temporal_split(df, 0.7)
    r, _ = run_models(df, tr, te, DEFAULT_FEATURES, "soh_rated", {"validation": "temporal", "held_out": "all"}, keep_pred=False)
    sup += r
    sup += exp_c(df, target="soh_rated", suffix="_soh_rated")[0].assign(validation="LOBO").to_dict("records")
    pd.DataFrame(sup).to_csv(OUT / "supp_soh_rated_target.csv", index=False)
    timings["supp_soh_rated"] = time.perf_counter() - t
    for k, f in [("E", lambda: exp_e(df)), ("future", lambda: exp_future(df)), ("rul", lambda: exp_rul(df))]:
        t = time.perf_counter()
        out[k] = f()
        timings[f"exp_{k}"] = time.perf_counter() - t
        print(f"exp {k} done in {timings[f'exp_{k}']:.1f}s", flush=True)
    timings["total"] = time.perf_counter() - t0
    json.dump({"target": TARGET, "default_features": DEFAULT_FEATURES, "all_features": ALL_FEATURES,
               "feature_groups": FEATURE_GROUPS, "hyperparams": HYPERPARAMS, "random_seeds": RANDOM_SEEDS,
               "temporal_train_frac": 0.7, "small_n": SMALL_N, "horizons": HORIZONS, "eol_ah": EOL_AH,
               "tuning": "없음 (사전 고정 하이퍼파라미터)", "timings_s": timings},
              open(OUT / "run_config.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps(timings, indent=1))


if __name__ == "__main__":
    main()
