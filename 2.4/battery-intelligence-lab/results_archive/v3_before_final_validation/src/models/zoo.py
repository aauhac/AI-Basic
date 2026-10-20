"""Model definitions. Hyperparameters are fixed in advance (no tuning on any test split).

Every single model is a Pipeline whose preprocessing (median imputation, standardisation) is
fit inside ``fit`` -> only on the training rows it receives. The target is standardised with
the training-set mean/std (TransformedTargetRegressor) so one SVR epsilon works for SOH and
RUL alike. XGBoost receives NaN natively (no imputer), the others get a median imputer.

Stacking (audit revision): sklearn's StackingRegressor with KFold(5, shuffle=False) built the
meta-learner's out-of-fold (OOF) predictions from base models trained on *later* cycles of the
same battery (time-order violation) and, in leave-one-battery-out, from base models that had
seen the same battery. ``OOFStackingRegressor`` instead builds the OOF predictions with a fold
plan that mirrors the evaluation scenario:
  - "forward": per battery, training rows are cut into time blocks; block j is predicted by
    base models trained only on rows whose label became available before block j started
    (per battery). Block 0 gets no OOF prediction and is not used to fit the meta-learner.
  - "group":   leave-one-battery-out inside the training set.
  - "random":  shuffled KFold, only for the random-split contrast (its own i.i.d. premise).
The final base models are refit on all training rows. Groups/order are passed to ``fit``.
"""
from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from xgboost import XGBRegressor

MODEL_NAMES = ["LinearRegression", "RandomForest", "SVR_RBF", "XGBoost", "Stacking"]
SINGLE_MODELS = MODEL_NAMES[:4]
META_ALPHAS = np.logspace(-3, 3, 13)

HYPERPARAMS = {
    "LinearRegression": {},
    "RandomForest": {"n_estimators": 300, "min_samples_leaf": 2, "max_features": 1.0},
    "SVR_RBF": {"C": 10.0, "epsilon": 0.05, "gamma": "scale"},
    "XGBoost": {"n_estimators": 400, "max_depth": 3, "learning_rate": 0.05, "subsample": 0.8,
                "colsample_bytree": 0.8, "tree_method": "hist"},
    "Stacking": {"base": SINGLE_MODELS, "meta": "RidgeCV(alphas=logspace(-3,3,13)) on standardised OOF predictions",
                 "oof_plan": "forward(5 time blocks per battery) | group(leave-one-battery-out) | random(KFold 5, shuffled)"},
}


def _base(name: str, seed: int):
    hp = HYPERPARAMS[name]
    if name == "LinearRegression":
        inner = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
                          ("model", LinearRegression())])
    elif name == "RandomForest":
        inner = Pipeline([("impute", SimpleImputer(strategy="median")),
                          ("model", RandomForestRegressor(random_state=seed, n_jobs=-1, **hp))])
    elif name == "SVR_RBF":
        inner = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
                          ("model", SVR(**hp))])
    elif name == "XGBoost":
        inner = Pipeline([("model", XGBRegressor(random_state=seed, n_jobs=4, **hp))])
    else:
        raise KeyError(name)
    return TransformedTargetRegressor(regressor=inner, transformer=StandardScaler())


def oof_plan(scheme: str, groups, order, label_time, n_blocks: int = 5, seed: int = 0):
    """List of (train_positions, predict_positions) for building OOF predictions."""
    groups, order, label_time = np.asarray(groups), np.asarray(order, float), np.asarray(label_time, float)
    n = groups.size
    uniq = np.unique(groups)
    if scheme == "group" and uniq.size >= 2:
        return [(np.flatnonzero(groups != g), np.flatnonzero(groups == g)) for g in uniq]
    if scheme == "random":
        return [(a, c) for a, c in KFold(n_blocks, shuffle=True, random_state=seed).split(np.zeros(n))]
    # forward (also the fallback for "group" with a single battery)
    sizes = [np.sum(groups == g) for g in uniq]
    k = int(min(n_blocks, max(2, min(sizes) // 2)))
    block = np.empty(n, int)
    start = {}
    for g in uniq:
        idx = np.flatnonzero(groups == g)
        rank = np.argsort(np.argsort(order[idx], kind="stable"), kind="stable")
        block[idx] = np.minimum(rank * k // idx.size, k - 1)
        start[g] = [order[idx][block[idx] == j].min() for j in range(k)]
    plan = []
    for j in range(1, k):
        pred = np.flatnonzero(block == j)
        thr = np.array([start[g][j] for g in groups])
        train = np.flatnonzero(label_time < thr)
        if train.size and pred.size:
            plan.append((train, pred))
    return plan


class OOFStackingRegressor(RegressorMixin, BaseEstimator):
    def __init__(self, scheme: str = "forward", n_blocks: int = 5, seed: int = 0):
        self.scheme = scheme
        self.n_blocks = n_blocks
        self.seed = seed

    def fit(self, X, y, groups=None, order=None, label_time=None):
        y = np.asarray(y, float)
        n = y.size
        groups = np.zeros(n) if groups is None else np.asarray(groups)
        order = np.arange(n) if order is None else np.asarray(order, float)
        label_time = order if label_time is None else np.asarray(label_time, float)
        take = (lambda idx: X.iloc[idx]) if hasattr(X, "iloc") else (lambda idx: X[idx])
        self.plan_ = oof_plan(self.scheme, groups, order, label_time, self.n_blocks, self.seed)
        oof = np.full((n, len(SINGLE_MODELS)), np.nan)
        for tr, pr in self.plan_:
            for j, name in enumerate(SINGLE_MODELS):
                oof[pr, j] = _base(name, self.seed).fit(take(tr), y[tr]).predict(take(pr))
        rows = np.all(np.isfinite(oof), axis=1)
        self.n_meta_rows_ = int(rows.sum())
        if self.n_meta_rows_ < 3:
            raise ValueError(f"only {self.n_meta_rows_} OOF rows for the meta-learner")
        self.mu_, self.sd_ = float(y.mean()), float(y.std() or 1.0)
        self.meta_ = RidgeCV(alphas=META_ALPHAS).fit((oof[rows] - self.mu_) / self.sd_, (y[rows] - self.mu_) / self.sd_)
        self.bases_ = [_base(name, self.seed).fit(X, y) for name in SINGLE_MODELS]
        return self

    def predict(self, X):
        P = np.column_stack([m.predict(X) for m in self.bases_])
        return self.meta_.predict((P - self.mu_) / self.sd_) * self.sd_ + self.mu_


def make_model(name: str, seed: int = 0, scheme: str = "forward"):
    if name == "Stacking":
        return OOFStackingRegressor(scheme=scheme, seed=seed)
    return _base(name, seed)


def fit_kwargs(name: str, groups=None, order=None, label_time=None) -> dict:
    """Extra fit arguments: only the stacking model needs battery/time information."""
    if name != "Stacking":
        return {}
    return {"groups": None if groups is None else np.asarray(groups),
            "order": None if order is None else np.asarray(order),
            "label_time": None if label_time is None else np.asarray(label_time)}
