"""Audit tests: stacking OOF plans respect time/battery, model selection never sees test rows,
RUL failures are counted, and the EV10 feature/label dependency is what the report states."""
import copy

import numpy as np
import pandas as pd
import pytest

from src.data import ev10
from src.evaluation.rul import rul_summary
from src.evaluation.selection import inner_folds
from src.features.ev10_features import window_features
from src.models.zoo import OOFStackingRegressor, oof_plan


def _toy(n_per=30, batteries=("a", "b", "c")):
    rows = [{"battery": b, "discharge_no": k} for b in batteries for k in range(1, n_per + 1)]
    df = pd.DataFrame(rows)
    rng = np.random.default_rng(0)
    df["x1"] = rng.normal(size=len(df))
    df["x2"] = df["discharge_no"] / n_per + rng.normal(0, 0.05, len(df))
    df["y"] = 1 - 0.3 * df["x2"] + 0.01 * df["x1"]
    return df


@pytest.mark.parametrize("horizon", [0, 5])
def test_forward_oof_plan_never_trains_on_later_labels(horizon):
    df = _toy()
    order = df["discharge_no"].to_numpy()
    label_time = order + horizon  # future pairs: label known only at origin + h
    plan = oof_plan("forward", df["battery"], order, label_time)
    assert plan
    for tr, pr in plan:
        for b in df["battery"].unique():
            trb, prb = tr[df["battery"].to_numpy()[tr] == b], pr[df["battery"].to_numpy()[pr] == b]
            if len(trb) and len(prb):
                assert label_time[trb].max() < order[prb].min()


def test_forward_plan_leaves_first_block_out_of_meta_training():
    df = _toy()
    plan = oof_plan("forward", df["battery"], df["discharge_no"], df["discharge_no"])
    predicted = np.concatenate([pr for _, pr in plan])
    first = df.groupby("battery")["discharge_no"].transform("min") == df["discharge_no"]
    assert not np.isin(np.flatnonzero(first), predicted).any()


def test_group_oof_plan_holds_out_whole_battery():
    df = _toy()
    g = df["battery"].to_numpy()
    plan = oof_plan("group", g, df["discharge_no"], df["discharge_no"])
    assert len(plan) == 3
    for tr, pr in plan:
        assert np.unique(g[pr]).size == 1 and g[pr][0] not in set(g[tr])


def test_stacking_fits_with_groups_and_predicts():
    df = _toy()
    for scheme in ("forward", "group"):
        m = OOFStackingRegressor(scheme=scheme).fit(df[["x1", "x2"]], df["y"], groups=df["battery"],
                                                    order=df["discharge_no"], label_time=df["discharge_no"])
        assert m.n_meta_rows_ >= 3 and np.isfinite(m.predict(df[["x1", "x2"]])).all()


def test_inner_selection_folds_are_inside_training_and_ordered():
    df = _toy()
    (tr, va), = inner_folds(df, "forward")
    for b, g in df.groupby("battery"):
        assert df.loc[np.intersect1d(tr, g.index), "discharge_no"].max() < df.loc[np.intersect1d(va, g.index), "discharge_no"].min()
    pairs = df.assign(origin_no=df["discharge_no"], target_no=df["discharge_no"] + 5)
    (tr, va), = inner_folds(pairs, "forward", "origin_no", "target_no")
    for b, g in pairs.groupby("battery"):
        assert pairs.loc[np.intersect1d(tr, g.index), "target_no"].max() < pairs.loc[np.intersect1d(va, g.index), "origin_no"].min()
    for tr, va in inner_folds(df, "group"):
        assert set(df.loc[tr, "battery"]).isdisjoint(df.loc[va, "battery"])


def test_rul_summary_reports_failures():
    p = pd.DataFrame({"battery": "a", "origin_no": [20, 21, 22, 23] * 2,
                      "method": ["m1"] * 4 + ["m2"] * 4,
                      "rul_true": [3, 2, 1, 0] * 2,
                      "rul_pred": [3, np.inf, 1, np.inf, 4, 2, 1, 1]})
    r = rul_summary(p, {"a": 23}, {"a": 30}, penalty=100).set_index("method")
    assert r.loc["m1", "n_fail_no_crossing"] == 2 and r.loc["m1", "success_rate"] == 0.5
    assert r.loc["m1", "MAE_success_only"] == 0  # failures excluded here ...
    assert r.loc["m1", "MAE_fail_penalized"] == pytest.approx((0 + 98 + 0 + 100) / 4)  # ... and penalised here
    assert r.loc["m2", "n_common_origins"] == 2 and r.loc["m2", "MAE_common"] == pytest.approx(0.5)


ev10_present = pytest.mark.skipif(not ev10.EV10_MAT.exists(), reason="EV10 repo not cloned")


@ev10_present
def test_ev10_label_is_computed_from_the_same_charge_record():
    packs = ev10.load_ev10()
    same = [abs(p["SOH"] - sum(s["Q"][-1] for s in p["data"]["Inf"]) / p["Cn"]) < 1e-3 for p in packs]
    assert sum(same) == 9  # vehicle 8 differs by 0.0013


@ev10_present
def test_ev10_feature_is_partial_sum_of_label_numerator():
    for p in ev10.load_ev10():
        f = window_features(p, 3.90, 4.00)
        if np.isfinite(f["q_win_ah"]):
            assert 0 < f["q_win_ah"] < f["q_total_ah"]
            assert f["q_win_norm"] < f["q_total_ah"] / p["Cn"]


@ev10_present
def test_ev10_feature_only_uses_samples_inside_window():
    """Changing charge outside the voltage window changes the label numerator but not the feature."""
    p = ev10.load_ev10()[0]
    q = copy.deepcopy(p)
    for s in q["data"]["Inf"]:
        outside = (s["Vmean"] < 3.80) | (s["Vmean"] >= 4.05)
        dq = np.diff(s["Q"], prepend=0.0)
        dq[outside] *= 1.5
        s["Q"] = np.cumsum(dq)
    a, b = window_features(p, 3.90, 4.00), window_features(q, 3.90, 4.00)
    assert a["q_win_ah"] == pytest.approx(b["q_win_ah"])
    assert b["q_total_ah"] > a["q_total_ah"] * 1.05
