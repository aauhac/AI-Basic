"""Minimal loader smoke tests against the real raw files (skipped if a dataset is absent)."""
import numpy as np
import pytest

from src.data import ev10, ev20, nasa

nasa_files = nasa.find_mat_files()
ev20_files = ev20.vehicle_files()


@pytest.mark.skipif(not nasa_files, reason="NASA data not extracted")
def test_nasa_priority_cells_load():
    for bid in nasa.PRIORITY:
        cycles = nasa.load_battery(nasa_files[bid])
        types = {c.type for c in cycles}
        assert types == {"charge", "discharge", "impedance"}
        df = nasa.discharge_table(bid, cycles)
        assert len(df) > 100
        assert df["capacity_ah"].notna().all()
        assert df["capacity_ah"].between(1.0, 2.1).all()
        assert df["capacity_ah"].iloc[-1] < df["capacity_ah"].iloc[0]  # capacity fades


@pytest.mark.skipif(not nasa_files, reason="NASA data not extracted")
def test_nasa_b0005_known_counts():
    cycles = nasa.load_battery(nasa_files["B0005"])
    assert len(cycles) == 616
    assert sum(c.type == "discharge" for c in cycles) == 168


@pytest.mark.skipif(not ev10.EV10_MAT.exists(), reason="EV10 repo not cloned")
def test_ev10_structure_and_labels():
    packs = ev10.load_ev10()
    assert len(packs) == 10
    for p in packs:
        assert set(p) == {"Veh", "Type", "Cn", "Ncell", "SOH", "SOC_OCV", "data"}
        assert set(p["data"]) == {"Inf", "SOC"}
        assert len(p["data"]["Inf"]) == len(p["data"]["SOC"])
        for seg in p["data"]["Inf"]:
            assert set(seg) == {"I_load", "Q", "Vmax", "Vmean"}
            assert not any(np.isnan(v).any() for v in seg.values())
        assert 0.7 < p["SOH"] < 1.05


@pytest.mark.skipif(not ev20_files, reason="EV20 archives not extracted")
def test_ev20_vehicle1_loads_and_segments():
    assert sorted(ev20_files) == list(range(1, 21))
    df = ev20.load_vehicle(ev20_files[1])
    assert list(df.columns) == ev20.COLUMNS
    assert df["record_time"].is_monotonic_increasing
    sessions = ev20.split_sessions(df)
    assert len(sessions) > 50
    caps = [ev20.session_capacity(s)["capacity_ah"] for s in sessions]
    assert np.nanmedian(caps) > 0
