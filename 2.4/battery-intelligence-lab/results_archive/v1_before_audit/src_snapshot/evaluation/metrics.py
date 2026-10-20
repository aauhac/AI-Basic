"""Metrics and a timed fit/predict helper."""
from __future__ import annotations

import time

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def scores(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    return {"n_test": int(y_true.size),
            "MAE": float(mean_absolute_error(y_true, y_pred)),
            "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "R2": float(r2_score(y_true, y_pred)) if y_true.size > 1 else np.nan}


def fit_predict(model, X_train, y_train, X_test):
    t0 = time.perf_counter()
    model.fit(X_train, y_train)
    t1 = time.perf_counter()
    pred = model.predict(X_test)
    t2 = time.perf_counter()
    return pred, {"fit_time_s": t1 - t0, "predict_time_s": t2 - t1, "n_train": int(len(y_train))}
