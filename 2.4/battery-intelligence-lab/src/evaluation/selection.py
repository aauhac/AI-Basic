"""Model selection that uses training rows only.

The final performance claim of every scenario is the *test* score of the model chosen here.
Inner validation mirrors the outer scenario:
  - "forward": per battery, inner-train = rows whose label time <= the 80 % point of the
    training cycles, inner-validation = rows whose origin is after it (same rule as the outer
    temporal split, also correct for future pairs whose label time is origin + h).
  - "group":   leave-one-battery-out among the training batteries.
Ties are broken by the fixed candidate order.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.evaluation.metrics import fit_predict, scores
from src.evaluation.splits import split_point
from src.models.zoo import MODEL_NAMES, fit_kwargs, make_model


def inner_folds(train: pd.DataFrame, scheme: str, order_col: str = "discharge_no", label_col: str | None = None,
                frac: float = 0.8):
    label_col = label_col or order_col
    if scheme == "group" and train["battery"].nunique() >= 2:
        return [(train.index[train["battery"] != b], train.index[train["battery"] == b]) for b in train["battery"].unique()]
    tr, va = [], []
    for _, g in train.groupby("battery", sort=False):
        origins = np.sort(g[order_col].unique())
        s = origins[split_point(origins.size, frac) - 1]
        tr.append(g.index[g[label_col] <= s])
        va.append(g.index[g[order_col] > s])
    return [(np.concatenate(tr), np.concatenate(va))]


def select_model(train: pd.DataFrame, features: list[str], target: str, scheme: str,
                 candidates=MODEL_NAMES, order_col: str = "discharge_no", label_col: str | None = None):
    folds = inner_folds(train, scheme, order_col, label_col)
    val = {}
    for name in candidates:
        maes = []
        for a, c in folds:
            if len(a) == 0 or len(c) == 0:
                continue
            ta = train.loc[a]
            kw = fit_kwargs(name, ta["battery"], ta[order_col], ta[label_col or order_col])
            pred, _ = fit_predict(make_model(name, scheme=scheme), ta[features], ta[target], train.loc[c, features], kw)
            maes.append(scores(train.loc[c, target], pred)["MAE"])
        val[name] = float(np.mean(maes)) if maes else np.inf
    best = min(val, key=val.get)
    return best, val, len(folds)
