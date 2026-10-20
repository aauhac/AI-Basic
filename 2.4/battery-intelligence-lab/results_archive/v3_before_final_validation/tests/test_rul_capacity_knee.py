"""RUL/EOL definitions, EV20 capacity calculation and knee test (EV10 dependency tests: test_audit.py)."""
import numpy as np
import pandas as pd
import pytest

from src.data import nasa
from src.data.ev20 import drop_exact_duplicates, session_capacity, split_sessions
from src.evaluation.knee import two_segment_fit
from src.evaluation.rul import add_rul, eol_cycle, extrapolate_rul
from src.features.nasa_features import build_table, window_charge


def test_eol_is_first_crossing_even_if_capacity_recovers():
    assert eol_cycle([1, 2, 3, 4, 5], [1.6, 1.45, 1.39, 1.42, 1.3], 1.4) == 3
    assert eol_cycle([1, 2, 3], [1.6, 1.5, 1.41], 1.4) is None


def test_rul_labels_and_censoring():
    df = pd.DataFrame({"battery": ["a"] * 5 + ["b"] * 3, "discharge_no": [1, 2, 3, 4, 5, 1, 2, 3],
                       "capacity_ah": [1.6, 1.5, 1.4, 1.3, 1.2, 1.8, 1.7, 1.6]})
    out, eols = add_rul(df, 1.4)
    assert eols == {"a": 3, "b": None}
    a = out[out["battery"] == "a"]
    assert a["rul"].tolist()[:3] == [2, 1, 0] and a["rul"].iloc[3:].isna().all()
    assert out.loc[out["battery"] == "b", "rul"].isna().all()  # no RUL label invented for a censored battery
    assert out.loc[out["battery"] == "b", "censored"].all()


@pytest.mark.skipif(not nasa.find_mat_files(), reason="NASA data not extracted")
def test_real_eol_cycles():
    files = nasa.find_mat_files()
    df = pd.concat([build_table(b, nasa.load_battery(files[b])) for b in ("B0005", "B0006", "B0007", "B0018")])
    _, eols = add_rul(df, 1.4)
    assert eols == {"B0005": 125, "B0006": 109, "B0007": None, "B0018": 97}


def test_extrapolation_uses_only_given_history():
    no = np.arange(1, 51)
    cap = 2.0 - 0.01 * no
    assert extrapolate_rul(no, cap, 1.4) == 10  # line reaches 1.4 Ah at cycle 60
    assert extrapolate_rul(no[:30], cap[:30], 1.4) == 30
    assert extrapolate_rul(no, np.full(50, 1.8), 1.4) == np.inf


def _session(minutes=60, current=-50.0, soc0=20.0, soc1=70.0, step_s=8):
    t = pd.date_range("2020-01-01", periods=int(minutes * 60 / step_s) + 1, freq=f"{step_s}s")
    n = len(t)
    return pd.DataFrame({"number": range(n), "record_time": t, "soc": np.linspace(soc0, soc1, n),
                         "pack_voltage": 350.0, "charge_current": current, "max_cell_voltage": 3.9,
                         "min_cell_voltage": 3.88, "max_temperature": 25, "min_temperature": 24,
                         "available_energy": 30.0, "available_capacity": 90.0})


def test_session_capacity_formula():
    s = session_capacity(_session())
    assert s["charge_ah"] == pytest.approx(50.0, rel=1e-6)  # 50 A x 1 h
    assert s["capacity_ah"] == pytest.approx(100.0, rel=1e-6)  # 50 Ah / 50 % SOC


def test_dedup_and_session_split():
    a, b = _session(30), _session(30)
    b["record_time"] += pd.Timedelta(hours=5)
    df = pd.concat([a, a.iloc[:10], b], ignore_index=True).sort_values("record_time", kind="stable")
    clean, log = drop_exact_duplicates(df)
    assert log["exact_duplicates_removed"] == 10 and len(clean) == len(a) + len(b)
    assert len(split_sessions(clean, 10.0, 100)) == 2


def test_knee_detects_synthetic_knee_and_not_a_line():
    x = np.arange(24, dtype=float)
    rng = np.random.default_rng(0)
    line = 130 - 0.5 * x + rng.normal(0, 0.3, x.size)
    assert not two_segment_fit(x, line)["candidate"]
    knee = np.where(x < 15, 130 - 0.3 * x, 130 - 0.3 * 15 - 2.0 * (x - 15)) + rng.normal(0, 0.3, x.size)
    r = two_segment_fit(x, knee)
    assert r["candidate"] and abs(r["break_x"] - 15) <= 1


def test_window_charge_requires_coverage():
    v = np.linspace(3.5, 4.2, 100)
    dq = np.full(100, 0.01)
    assert window_charge(v, dq, 3.9, 4.0) == pytest.approx(0.01 * np.sum((v >= 3.9) & (v < 4.0)))
    assert np.isnan(window_charge(v[v < 3.95], dq[v < 3.95], 3.9, 4.0))

