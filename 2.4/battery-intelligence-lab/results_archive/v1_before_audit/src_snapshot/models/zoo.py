"""Model definitions. Hyperparameters are fixed in advance (no tuning on any test split).

Every model is a Pipeline whose preprocessing (median imputation, standardisation) is fit
inside ``fit`` -> only on the training rows it receives. The target is standardised with
the training-set mean/std (TransformedTargetRegressor) so one SVR epsilon works for SOH
and RUL alike. XGBoost receives NaN natively (no imputer), the others get a median imputer.
"""
from __future__ import annotations

import numpy as np
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor, StackingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from xgboost import XGBRegressor

MODEL_NAMES = ["LinearRegression", "RandomForest", "SVR_RBF", "XGBoost", "Stacking"]
SINGLE_MODELS = MODEL_NAMES[:4]

HYPERPARAMS = {
    "LinearRegression": {},
    "RandomForest": {"n_estimators": 300, "min_samples_leaf": 2, "max_features": 1.0},
    "SVR_RBF": {"C": 10.0, "epsilon": 0.05, "gamma": "scale"},
    "XGBoost": {"n_estimators": 400, "max_depth": 3, "learning_rate": 0.05, "subsample": 0.8,
                "colsample_bytree": 0.8, "tree_method": "hist"},
    "Stacking": {"final_estimator": "RidgeCV(alphas=logspace(-3,3,13))", "cv": "KFold(5, shuffle=False)",
                 "passthrough": False},
}


def _base(name: str, seed: int):
    hp = HYPERPARAMS[name]
    if name == "LinearRegression":
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
                         ("model", LinearRegression())])
    if name == "RandomForest":
        return Pipeline([("impute", SimpleImputer(strategy="median")),
                         ("model", RandomForestRegressor(random_state=seed, n_jobs=-1, **hp))])
    if name == "SVR_RBF":
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
                         ("model", SVR(**hp))])
    if name == "XGBoost":
        return Pipeline([("model", XGBRegressor(random_state=seed, n_jobs=4, **hp))])
    raise KeyError(name)


def make_model(name: str, seed: int = 0):
    if name == "Stacking":
        inner = StackingRegressor(
            estimators=[(n, _base(n, seed)) for n in SINGLE_MODELS],
            final_estimator=RidgeCV(alphas=np.logspace(-3, 3, 13)),
            cv=KFold(5, shuffle=False), passthrough=False)
    else:
        inner = _base(name, seed)
    return TransformedTargetRegressor(regressor=inner, transformer=StandardScaler())
