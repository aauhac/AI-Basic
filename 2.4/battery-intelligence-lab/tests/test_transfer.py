"""Transfer-experiment tests: feature definitions, IR correction, label-free prediction,
NASA-only selection, bootstrap statistics."""
import numpy as np
import pandas as pd
import pytest

from src.data import ev10, nasa
from src.features.transfer_features import (BIN_COLS, METHODS, curve_features, ev10_curve, ev10_resistance,
                                            nasa_charge_curve, step_resistance)


def _curve(n=20000):  # dense enough that bin-edge discretisation stays below 0.1 %
    q = np.linspace(0, 1.0, n)
    v = 3.6 + 0.6 * q  # linear voltage-charge curve, 0.06 Ah per 10 mV
    dq = np.diff(q, prepend=0.0)
    return v, dq, np.full(n, 1.5)


def test_bins_and_ratios_on_known_curve():
    v, dq, i = _curve()
    f = curve_features(v, dq, i, c_rated=2.0)
    for c in BIN_COLS:
        assert f[c] == pytest.approx(0.05 / 0.6 / 2.0, rel=2e-3)  # 50 mV of a 0.6 V/Ah slope, / C_rated
    assert f["r395_400"] == pytest.approx(1.0, rel=2e-3) and f["r400_405"] == pytest.approx(1.0, rel=2e-3)


def test_ratios_do_not_depend_on_capacity_scale():
    v, dq, i = _curve()
    a, b = curve_features(v, dq, i, 2.0), curve_features(v, dq * 50, i * 50, 100.0)
    assert a["r395_400"] == pytest.approx(b["r395_400"]) and a["b390_395"] == pytest.approx(b["b390_395"])


def test_ir_correction_equals_shifted_window():
    v, dq, i = _curve()
    r = 0.04  # 1.5 A * 0.04 Ohm = 60 mV
    corrected = curve_features(v, dq, i, 2.0, r)
    shifted = curve_features(v - 0.06, dq, i, 2.0)
    for c in BIN_COLS:
        assert corrected[c] == pytest.approx(shifted[c])


def test_step_resistance_recovers_ohmic_drop():
    rng = np.random.default_rng(0)
    i = np.repeat([10.0, 40.0, 25.0, 60.0], 50)
    v = 3.8 + 0.0005 * i + rng.normal(0, 1e-5, i.size)
    r, n = step_resistance([i], [v])
    assert n == 3 and r == pytest.approx(0.0005, rel=0.05)


nasa_ok = pytest.mark.skipif(not nasa.find_mat_files(), reason="NASA data not extracted")
ev10_ok = pytest.mark.skipif(not ev10.EV10_MAT.exists(), reason="EV10 repo not cloned")


@nasa_ok
def test_nasa_onset_resistance_is_measured_in_same_cycle():
    ch = [c for c in nasa.load_battery(nasa.find_mat_files()["B0005"]) if c.type == "charge"]
    rs = [nasa_charge_curve(c)[3] for c in ch[1:20]]
    assert np.nanmedian(rs) == pytest.approx(0.085, abs=0.01)


@ev10_ok
def test_ev10_resistance_and_features_ignore_the_label():
    p = ev10.load_ev10()[0]
    q = dict(p)
    q["SOH"], q["Cn"] = 0.5, p["Cn"]  # a different label must not change inputs
    assert ev10_resistance(p) == ev10_resistance(q)
    v, dq, i, _ = ev10_curve(p)
    v2, dq2, i2, _ = ev10_curve(q)
    assert np.array_equal(v, v2) and np.array_equal(dq, dq2)


@nasa_ok
@ev10_ok
def test_selection_uses_nasa_only_and_predictions_ignore_ev_labels():
    from experiments.transfer_experiments import ev10_table, fit_full, nasa_scores, nasa_transfer_table, predict_ev, select
    nasa_t = nasa_transfer_table()
    sub = nasa_t[nasa_t["discharge_no"] % 3 == 0]  # smaller table keeps the test fast
    res = nasa_scores(sub, "soh_rated", models=["LinearRegression"])
    sel, _ = select(res)
    assert sel["method"] in METHODS and set(res["held_out"]) >= {"B0005", "B0006", "B0007", "B0018"}
    ev = ev10_table(ev10.load_ev10())
    model, _ = fit_full(sub, sel["method"], "LinearRegression", "soh_rated")
    p1 = predict_ev(model, ev, sel["method"])
    shuffled = ev.assign(soh_file=np.random.default_rng(0).permutation(ev["soh_file"].to_numpy()))
    p2 = predict_ev(model, shuffled, sel["method"])
    np.testing.assert_array_equal(p1, p2)


def test_paired_bootstrap_sign_and_ci():
    from experiments.transfer_experiments import paired_bootstrap
    a = np.array([0.2, 0.25, 0.3, 0.22, 0.18])
    b = a - 0.1
    r = paired_bootstrap(a, b, n=2000)
    assert r["diff"] == pytest.approx(-0.1) and r["ci95_high"] < 0 and r["improvement_pct"] > 0
