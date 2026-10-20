"""Data splits. Rows are discharge cycles identified by (battery, discharge_no)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def random_split(df: pd.DataFrame, test_frac: float = 0.3, seed: int = 0):
    """Row-level shuffle across all batteries. Neighbouring cycles of the same cell end up on
    both sides, so this split overstates generalisation (kept only as a contrast)."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(df))
    n_test = int(round(len(df) * test_frac))
    return np.sort(df.index[idx[n_test:]]), np.sort(df.index[idx[:n_test]])


def split_point(n: int, train_frac: float) -> int:
    """Number of leading cycles that go to training."""
    return math.ceil(n * train_frac)


def temporal_split(df: pd.DataFrame, train_frac: float = 0.7):
    """Per battery: first ceil(70 %) of discharges -> train, the rest -> test."""
    tr, te = [], []
    for _, g in df.groupby("battery", sort=False):
        g = g.sort_values("discharge_no")
        k = split_point(len(g), train_frac)
        tr.append(g.index[:k])
        te.append(g.index[k:])
    return np.concatenate(tr), np.concatenate(te)


def small_data_split(df: pd.DataFrame, n_train: int, train_frac: float = 0.7):
    """Train on the first n_train discharges of each battery; test is the fixed temporal test
    set (last 30 %), so every n_train is scored on identical rows."""
    tr, te = [], []
    for _, g in df.groupby("battery", sort=False):
        g = g.sort_values("discharge_no")
        k = split_point(len(g), train_frac)
        if n_train > k:
            raise ValueError(f"n_train={n_train} exceeds pre-test cycles ({k})")
        tr.append(g.index[:n_train])
        te.append(g.index[k:])
    return np.concatenate(tr), np.concatenate(te)


def lobo_splits(df: pd.DataFrame, batteries=None):
    """Leave-one-battery-out: yields (held_out, train_idx, test_idx)."""
    for b in batteries or df["battery"].unique():
        yield b, df.index[df["battery"] != b].to_numpy(), df.index[df["battery"] == b].to_numpy()


def make_future_pairs(df: pd.DataFrame, horizon: int, feature_cols: list[str], target: str = "soh_init") -> pd.DataFrame:
    """Pair features observed at discharge k with the target observed at discharge k+horizon.

    Columns: battery, origin_no (k), target_no (k+h), features..., y, y_origin (target at k).
    Pairs exist only where discharge k+h was actually observed.
    """
    out = []
    for b, g in df.groupby("battery", sort=False):
        g = g.sort_values("discharge_no")
        by_no = g.set_index("discharge_no")[target]
        p = g[feature_cols].copy()
        p.insert(0, "battery", b)
        p["origin_no"] = g["discharge_no"].to_numpy()
        p["target_no"] = p["origin_no"] + horizon
        p["y"] = by_no.reindex(p["target_no"]).to_numpy()
        p["y_origin"] = g[target].to_numpy()
        out.append(p[p["y"].notna()])
    return pd.concat(out, ignore_index=True)


def temporal_split_pairs(pairs: pd.DataFrame, df: pd.DataFrame, train_frac: float = 0.7):
    """Per battery with split cycle s (last training discharge of temporal_split):
    train = pairs whose *target* is at or before s; test = pairs whose *origin* is after s.
    No training label comes from the test period."""
    tr, te = [], []
    for b, g in df.groupby("battery", sort=False):
        s = g.sort_values("discharge_no")["discharge_no"].iloc[split_point(len(g), train_frac) - 1]
        pb = pairs[pairs["battery"] == b]
        tr.append(pb.index[pb["target_no"] <= s])
        te.append(pb.index[pb["origin_no"] > s])
    return np.concatenate(tr), np.concatenate(te)
