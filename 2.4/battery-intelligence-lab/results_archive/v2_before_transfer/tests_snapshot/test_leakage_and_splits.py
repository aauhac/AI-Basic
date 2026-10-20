"""Leakage and split tests: no future information in features, no test rows in training,
preprocessing fit on training rows only."""
import numpy as np
import pandas as pd
import pytest

from src.data import nasa
from src.evaluation.splits import (lobo_splits, make_future_pairs, random_split, small_data_split,
                                   temporal_split, temporal_split_pairs)
from src.features.nasa_features import FEATURE_GROUPS, build_table, feature_list
from src.models.zoo import MODEL_NAMES, fit_kwargs, make_model

files = nasa.find_mat_files()
pytestmark = pytest.mark.skipif(not files, reason="NASA data not extracted")
ALL = feature_list(*FEATURE_GROUPS)


@pytest.fixture(scope="module")
def b0005():
    return nasa.load_battery(files["B0005"])


@pytest.fixture(scope="module")
def table():
    return pd.concat([build_table(b, nasa.load_battery(files[b])) for b in ("B0005", "B0018")], ignore_index=True)


def test_features_do_not_change_when_future_cycles_are_removed(b0005):
    """Prefix invariance: the row for discharge k is identical whether or not cycles after
    discharge k exist. Any use of future data would break this."""
    full = build_table("B0005", b0005)
    dis_pos = [i for i, c in enumerate(b0005) if c.type == "discharge"]
    for k in (5, 40, 100, 150):
        trunc = build_table("B0005", b0005[: dis_pos[k - 1] + 1])
        row_full = full.loc[full["discharge_no"] == k, ALL + ["soh_init", "capacity_ah"]].iloc[0]
        row_trunc = trunc.loc[trunc["discharge_no"] == k, ALL + ["soh_init", "capacity_ah"]].iloc[0]
        pd.testing.assert_series_equal(row_full, row_trunc, check_names=False)


def test_features_do_not_use_current_discharge(b0005):
    """Changing discharge k's measurements must not change discharge k's input features."""
    import copy
    cyc = copy.deepcopy(b0005)
    dis_pos = [i for i, c in enumerate(cyc) if c.type == "discharge"]
    k = 60
    for key in cyc[dis_pos[k - 1]].data:
        cyc[dis_pos[k - 1]].data[key] = cyc[dis_pos[k - 1]].data[key] * 0.5
    a, b = build_table("B0005", b0005), build_table("B0005", cyc)
    ra, rb = a.loc[a["discharge_no"] == k, ALL].iloc[0], b.loc[b["discharge_no"] == k, ALL].iloc[0]
    pd.testing.assert_series_equal(ra, rb)
    assert b.loc[b["discharge_no"] == k, "capacity_ah"].iloc[0] != a.loc[a["discharge_no"] == k, "capacity_ah"].iloc[0]


def test_history_features_are_lagged(table):
    for _, g in table.groupby("battery"):
        g = g.sort_values("discharge_no")
        np.testing.assert_allclose(g["soh_lag1"].iloc[1:], g["soh_init"].iloc[:-1])
        assert np.isnan(g["soh_lag1"].iloc[0])


def test_temporal_split_is_ordered_per_battery(table):
    tr, te = temporal_split(table, 0.7)
    assert set(tr).isdisjoint(te) and len(tr) + len(te) == len(table)
    for b, g in table.groupby("battery"):
        assert table.loc[np.intersect1d(tr, g.index), "discharge_no"].max() < table.loc[np.intersect1d(te, g.index), "discharge_no"].min()


def test_small_data_uses_fixed_test_and_first_cycles(table):
    _, te_full = temporal_split(table, 0.7)
    for n in (10, 30):
        tr, te = small_data_split(table, n, 0.7)
        assert np.array_equal(np.sort(te), np.sort(te_full))
        assert (table.loc[tr].groupby("battery")["discharge_no"].max() == n).all()


def test_random_split_disjoint(table):
    tr, te = random_split(table, 0.3, seed=1)
    assert set(tr).isdisjoint(te) and len(tr) + len(te) == len(table)


def test_lobo_holds_out_whole_battery(table):
    for b, tr, te in lobo_splits(table):
        assert (table.loc[te, "battery"] == b).all()
        assert (table.loc[tr, "battery"] != b).all()


@pytest.mark.parametrize("h", [10, 20])
def test_future_pairs_and_temporal_split(table, h):
    pairs = make_future_pairs(table, h, ALL)
    assert (pairs["target_no"] - pairs["origin_no"] == h).all()
    assert (pairs["discharge_no"] == pairs["origin_no"]).all()  # cycle feature = origin, not target
    for b, g in table.groupby("battery"):
        soh = g.set_index("discharge_no")["soh_init"]
        p = pairs[pairs["battery"] == b]
        np.testing.assert_allclose(p["y"], soh.loc[p["target_no"]].to_numpy())
    tr, te = temporal_split_pairs(pairs, table, 0.7)
    for b in table["battery"].unique():
        ptr, pte = pairs.loc[tr], pairs.loc[te]
        ptr, pte = ptr[ptr["battery"] == b], pte[pte["battery"] == b]
        assert ptr["target_no"].max() < pte["origin_no"].min()


@pytest.mark.parametrize("name", ["LinearRegression", "SVR_RBF"])
def test_preprocessing_fit_on_train_only(table, name):
    tr, te = temporal_split(table, 0.7)
    feats = feature_list("charge", "impedance", "cycle")
    m = make_model(name).fit(table.loc[tr, feats], table.loc[tr, "soh_init"])
    imp = m.regressor_.named_steps["impute"]
    np.testing.assert_allclose(imp.statistics_, table.loc[tr, feats].median().to_numpy())
    sc = m.regressor_.named_steps["scale"]
    filled = table.loc[tr, feats].fillna(table.loc[tr, feats].median())
    np.testing.assert_allclose(sc.mean_, filled.mean().to_numpy())
    np.testing.assert_allclose(m.transformer_.mean_[0], table.loc[tr, "soh_init"].mean())


def test_all_models_fit_and_predict(table):
    tr, te = temporal_split(table, 0.7)
    feats = feature_list("charge", "impedance", "cycle")
    for name in MODEL_NAMES:
        kw = fit_kwargs(name, table.loc[tr, "battery"], table.loc[tr, "discharge_no"], table.loc[tr, "discharge_no"])
        pred = make_model(name, scheme="forward").fit(table.loc[tr, feats], table.loc[tr, "soh_init"], **kw).predict(table.loc[te, feats])
        assert pred.shape == (len(te),) and np.isfinite(pred).all()
