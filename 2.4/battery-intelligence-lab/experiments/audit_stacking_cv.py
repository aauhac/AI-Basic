"""Diagnose how the out-of-fold (OOF) folds used to train a stacking meta-learner relate to
time order and battery identity. Compares the pre-audit splitter (KFold(5, shuffle=False) on
rows ordered battery -> discharge) with the post-audit OOF plans in src.models.zoo.

For every OOF-predicted row we ask:
  future_same_battery : the base models that produced its OOF prediction were trained on a
                        later cycle of the same battery (time-order violation)
  same_battery_seen   : those base models saw any cycle of the same battery (in a LOBO
                        setting the meta-learner then learns from easier-than-test predictions)
Writes results/audit/stacking_cv_diagnosis.csv.

Usage: .venv/Scripts/python -m experiments.audit_stacking_cv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from src.evaluation.splits import lobo_splits, temporal_split
from src.features.nasa_features import build_nasa_table
from src.models.zoo import oof_plan

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "audit"


def diagnose(train: pd.DataFrame, plan, setting: str, splitter: str) -> dict:
    b = train["battery"].to_numpy()
    no = train["discharge_no"].to_numpy()
    n_pred = fut = seen = 0
    for tr, pr in plan:
        for i in pr:
            n_pred += 1
            same = tr[b[tr] == b[i]]
            seen += same.size > 0
            fut += bool((no[same] > no[i]).any())
    return {"setting": setting, "splitter": splitter, "train_rows": len(train), "oof_rows": n_pred,
            "meta_rows_share": n_pred / len(train),
            "oof_rows_with_future_same_battery_in_base_training": fut,
            "share_future_violation": fut / n_pred if n_pred else np.nan,
            "oof_rows_with_same_battery_in_base_training": seen,
            "share_same_battery_seen": seen / n_pred if n_pred else np.nan}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df, _ = build_nasa_table()
    rows = []
    tr, _ = temporal_split(df, 0.7)
    t = df.loc[tr].reset_index(drop=True)
    old = [(a, c) for a, c in KFold(5, shuffle=False).split(t)]
    rows.append(diagnose(t, old, "시간순 학습(447행)", "기존 KFold(5, shuffle=False)"))
    new = oof_plan("forward", t["battery"].to_numpy(), t["discharge_no"].to_numpy(), t["discharge_no"].to_numpy())
    rows.append(diagnose(t, new, "시간순 학습(447행)", "수정 forward(배터리별 시간 블록, 확장 창)"))
    for b, trb, _ in lobo_splits(df, ["B0005", "B0006", "B0007", "B0018"]):
        t = df.loc[trb].reset_index(drop=True)
        old = [(a, c) for a, c in KFold(5, shuffle=False).split(t)]
        rows.append(diagnose(t, old, f"LOBO 학습({b} 제외)", "기존 KFold(5, shuffle=False)"))
        new = oof_plan("group", t["battery"].to_numpy(), t["discharge_no"].to_numpy(), t["discharge_no"].to_numpy())
        rows.append(diagnose(t, new, f"LOBO 학습({b} 제외)", "수정 group(배터리 단위 leave-one-out)"))
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "stacking_cv_diagnosis.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 20)
    print(res.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
