"""Final-validation tests: charge progress, no synthesised samples between EV10 segments,
causal NASA inputs, resistance sign/units, EV10-label invariance, unchanged NASA results,
and availability of the charge record a feature needs."""
import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data import ev10, nasa
from src.features.transfer_features import (ev10_curve, ev10_resistance, ev10_sample_soc, method_features,
                                            nasa_charge_curve)

ROOT = Path(__file__).resolve().parents[1]
nasa_ok = pytest.mark.skipif(not nasa.find_mat_files(), reason="NASA data not extracted")
ev10_ok = pytest.mark.skipif(not ev10.EV10_MAT.exists(), reason="EV10 repo not cloned")


def test_charge_progress_definition():
    from experiments.final_validation import charge_progress
    p = charge_progress([0.0, 0.1, 0.2, -0.05, 0.2])  # negative increments are not counted as charge
    np.testing.assert_allclose(p, [0, 0.2, 0.6, 0.6, 1.0])


@nasa_ok
def test_nasa_progress_is_monotone_and_ends_at_one():
    from experiments.final_validation import charge_progress
    ch = [c for c in nasa.load_battery(nasa.find_mat_files()["B0005"]) if c.type == "charge"]
    for c in ch[1:40:7]:
        p = charge_progress(nasa_charge_curve(c)[1])
        assert np.all(np.diff(p) >= 0) and p[-1] == pytest.approx(1.0)


@ev10_ok
def test_ev10_uses_only_recorded_samples_between_segments():
    for p in ev10.load_ev10():
        segs = p["data"]["Inf"]
        v, dq, i, seg = ev10_curve(p)
        assert v.size == sum(s["Q"].size - 1 for s in segs)  # nothing inserted across gaps or overlaps
        soc = ev10_sample_soc(p)
        for k, r in enumerate(p["data"]["SOC"]):
            lo, hi = (float(x) for x in r.split("-"))
            s = soc[seg == k]
            assert s.min() >= lo - 1e-9 and s.max() <= hi + 1e-9  # interpolation stays inside its own segment


@nasa_ok
def test_nasa_transfer_features_come_from_a_charge_that_ended_before_the_discharge():
    from experiments.transfer_experiments import nasa_transfer_table
    from src.features.transfer_features import curve_features
    cyc = nasa.load_battery(nasa.find_mat_files()["B0018"])
    table = nasa_transfer_table()
    t18 = table[table["battery"] == "B0018"].set_index("discharge_no")
    last, n, checked = None, 0, 0
    for c in cyc:
        if c.type == "charge":
            last = c
        elif c.type == "discharge":
            n += 1
            if last is not None and n % 10 == 0 and t18.loc[n, "charge_valid"] == True:  # noqa: E712
                end = last.start_time.timestamp() + float(last.data["Time"][-1])
                assert end <= c.start_time.timestamp()  # whole charge record exists before discharge n starts
                v, dq, i, _ = nasa_charge_curve(last)
                f = curve_features(v, dq, i, 2.0)
                assert t18.loc[n, "raw_b390_395"] == pytest.approx(f["b390_395"])
                checked += 1
            last = None
    assert checked >= 5


@nasa_ok
@ev10_ok
def test_resistance_sign_and_units():
    rs = [nasa_charge_curve(c)[3] for c in nasa.load_battery(nasa.find_mat_files()["B0006"]) if c.type == "charge"][1:30]
    assert 0.03 < np.nanmedian(rs) < 0.2  # ohm, single cell
    for p in ev10.load_ev10():
        r, n = ev10_resistance(p)
        assert n > 0 and 0 < r < 0.005  # ohm per pack current on mean cell voltage
    synth = {"data": {"Inf": [{"I_load": np.repeat([-20.0, -60.0, -30.0], 20),
                               "Vmean": 3.9 + 0.0005 * np.repeat([20.0, 60.0, 30.0], 20),
                               "Q": np.linspace(0, 1, 60)}], "SOC": ["40-50"]}}
    assert ev10_resistance(synth)[0] == pytest.approx(0.0005)  # charging current is negative in the file


@ev10_ok
def test_ev10_features_ignore_samples_outside_the_window():
    p = ev10.load_ev10()[0]
    q = copy.deepcopy(p)
    for s in q["data"]["Inf"]:
        d = np.diff(s["Q"], prepend=0.0)
        out = (s["Vmean"] < 3.85) | (s["Vmean"] >= 4.06)
        d[out] *= 3.0
        s["Q"] = np.cumsum(d)
    a, b = (method_features(*ev10_curve(x)[:3], x["Cn"], None, "B3") for x in (p, q))
    for k in a:
        assert a[k] == pytest.approx(b[k])


@nasa_ok
@ev10_ok
def test_final_selection_and_predictions_do_not_depend_on_ev10_labels():
    from experiments.final_validation import final_ev10
    packs = ev10.load_ev10()
    altered = copy.deepcopy(packs)
    rng = np.random.default_rng(1)
    for p in altered:
        p["SOH"] = float(rng.uniform(0.5, 1.1))
    r1, v1, i1 = final_ev10(packs)
    r2, v2, i2 = final_ev10(altered)
    assert i1["final"] == i2["final"]
    pred_cols = [c for c in v1.columns if c.startswith("pred_")]
    pd.testing.assert_frame_equal(v1[pred_cols], v2[pred_cols])


ARCHIVE = ROOT / "results_archive" / "v3_before_final_validation" / "results" / "nasa"


@pytest.mark.skipif(not ARCHIVE.exists(), reason="pre-validation archive missing")
@pytest.mark.parametrize("name", ["final_claims.csv", "exp_A_split_comparison.csv", "exp_B_small_data.csv",
                                  "exp_C_lobo.csv", "future_soh.csv", "rul_results.csv"])
def test_nasa_task_results_unchanged(name):
    keep = lambda d: d[[c for c in d.columns if not c.endswith("time_s")]]  # noqa: E731  (wall-clock timings vary)
    a, b = keep(pd.read_csv(ARCHIVE / name)), keep(pd.read_csv(ROOT / "results" / "nasa" / name))
    pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-12, atol=1e-12)
