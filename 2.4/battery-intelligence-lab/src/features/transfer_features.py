"""Common charge-curve features for transferring NASA-trained SOH models to EV packs.

Only quantities measured in both domains are used: voltage during charging, charged Ah per
sample, charging current, and a resistance measured from the record itself.

Voltage signals: NASA = cell terminal voltage; EV10 = mean cell voltage (Vmean);
EV20 = pack voltage / 90 series cells (= mean cell voltage incl. pack interconnect drop).

Methods (fixed before any EV evaluation):
  A0  raw voltage,  Q[3.90,4.00) / C_rated                         (pre-audit baseline feature)
  B1  raw voltage,  Q in 3 bins of 50 mV over [3.90,4.05) / C_rated  (incremental-capacity profile)
  B2  raw voltage,  bin ratios Q[3.95,4.00)/Q[3.90,3.95), Q[4.00,4.05)/Q[3.90,3.95)  (C_rated-free)
  B3  raw voltage,  B1 + B2
  C1  IR-corrected voltage V - |I|*R,  B1 bins
  C2  IR-corrected voltage,  B1 + B2
R is measured from the same record (NASA: voltage jump at charge onset of that charge cycle;
EV: median dV/d|I| over current steps of that vehicle's record). The correction removes only
the fast (ohmic + ~1-3 s) polarisation; slower diffusion polarisation remains.
"""
from __future__ import annotations

import numpy as np

from src.features.nasa_features import window_charge

BINS = [(3.90, 3.95), (3.95, 4.00), (4.00, 4.05)]
BIN_COLS = ["b390_395", "b395_400", "b400_405"]
RATIO_COLS = ["r395_400", "r400_405"]
METHODS = {
    "A0": {"ir": False, "features": ["q390_400"], "desc": "원 전압, 3.90–4.00 V 창 충전량/정격 (기존)"},
    "B1": {"ir": False, "features": BIN_COLS, "desc": "원 전압, 50 mV 구간 3개 충전량/정격 (증분용량)"},
    "B2": {"ir": False, "features": RATIO_COLS, "desc": "원 전압, 구간 충전량 비율 (정격용량 무관)"},
    "B3": {"ir": False, "features": BIN_COLS + RATIO_COLS, "desc": "원 전압, B1+B2"},
    "C1": {"ir": True, "features": BIN_COLS, "desc": "IR 보정 전압(V−|I|R), 구간 충전량/정격"},
    "C2": {"ir": True, "features": BIN_COLS + RATIO_COLS, "desc": "IR 보정 전압, B1+B2"},
}
STEP_MIN_A = 5.0  # EV current steps used for resistance


def curve_features(v, dq, i_abs, c_rated: float, r: float | None = None) -> dict:
    """Window features of one charge curve. v [V], dq [Ah per sample], i_abs [A, >=0]."""
    v, dq, i_abs = (np.asarray(a, float) for a in (v, dq, i_abs))
    if r is not None:
        if not np.isfinite(r):
            return {k: np.nan for k in ["q390_400"] + BIN_COLS + RATIO_COLS}
        v = v - i_abs * r
    out = {"q390_400": window_charge(v, dq, 3.90, 4.00) / c_rated}
    b = [window_charge(v, dq, a, z) for a, z in BINS]
    out.update({c: x / c_rated for c, x in zip(BIN_COLS, b)})
    out["r395_400"] = b[1] / b[0] if b[0] > 0 else np.nan
    out["r400_405"] = b[2] / b[0] if b[0] > 0 else np.nan
    return out


def method_features(v, dq, i_abs, c_rated, r, method: str) -> dict:
    m = METHODS[method]
    f = curve_features(v, dq, i_abs, c_rated, r if m["ir"] else None)
    return {k: f[k] for k in m["features"]}


# ---------------------------------------------------------------- NASA
def nasa_charge_curve(cycle):
    """(v, dq, i_abs, r_onset) of a NASA charge cycle; only samples with charging current.
    r_onset = dV/dI between the last sample before the CC current switches on and the first
    sample with I > 1 A (measured in this same cycle)."""
    v, i, t = (np.asarray(cycle.data[k], float) for k in ("Voltage_measured", "Current_measured", "Time"))
    ok = np.isfinite(v) & np.isfinite(i) & np.isfinite(t)
    v, i, t = v[ok], i[ok], t[ok]
    dq = np.concatenate([[0.0], i[1:] * np.diff(t) / 3600])
    on = np.flatnonzero(i > 1.0)
    r = np.nan
    if on.size and on[0] > 0:
        k = on[0]
        di = i[k] - i[k - 1]
        if di > 0.5:
            r = (v[k] - v[k - 1]) / di
    m = i > 0
    return v[m], dq[m], i[m], r


# ---------------------------------------------------------------- EV10
def ev10_curve(pack):
    """(v=Vmean, dq, i_abs, segment_id) with dq = Q increment within a segment (charging only)."""
    vs, dqs, ii, seg = [], [], [], []
    for k, s in enumerate(pack["data"]["Inf"]):
        vs.append(s["Vmean"][1:])
        dqs.append(np.diff(s["Q"]))
        ii.append(-s["I_load"][1:])  # charging current is negative in the file
        seg.append(np.full(s["Q"].size - 1, k))
    v, dq, i, seg = (np.concatenate(a) for a in (vs, dqs, ii, seg))
    return v, dq, np.clip(i, 0, None), seg


def step_resistance(i_charge_list, v_list, min_step: float = STEP_MIN_A) -> tuple[float, int]:
    """Median dV/dI over consecutive samples whose current changes by >= min_step.
    Current is signed with charging positive (same convention as NASA). Inputs are
    per-segment/per-session arrays; no step is taken across their boundaries."""
    rs = []
    for i, v in zip(i_charge_list, v_list):
        di, dv = np.diff(np.asarray(i, float)), np.diff(np.asarray(v, float))
        m = np.abs(di) >= min_step
        rs.append(dv[m] / di[m])
    rs = np.concatenate(rs) if rs else np.array([])
    return (float(np.median(rs)) if rs.size else np.nan), int(rs.size)


def ev10_resistance(pack) -> tuple[float, int]:
    segs = pack["data"]["Inf"]
    return step_resistance([-s["I_load"] for s in segs], [s["Vmean"] for s in segs])


def soc_ocv_table(pack) -> tuple[np.ndarray, np.ndarray]:
    """EV10 SOC_OCV rows: (SOC fraction, cell OCV [V]), sorted by SOC."""
    t = np.asarray(pack["SOC_OCV"], float)
    o = np.argsort(t[:, 0])
    return t[o, 0], t[o, 1]


def ev10_sample_soc(pack) -> np.ndarray:
    """Per-sample SOC (%) interpolated linearly in charge within each segment between the
    segment's recorded SOC endpoints (BMS metadata, not the SOH label)."""
    out = []
    for s, rng in zip(pack["data"]["Inf"], pack["data"]["SOC"]):
        lo, hi = (float(x) for x in rng.split("-"))
        q = s["Q"]
        frac = (q - q[0]) / (q[-1] - q[0]) if q[-1] > q[0] else np.zeros_like(q)
        frac = np.clip(frac, 0.0, 1.0)  # Q is not monotonic where the current turns positive; stay inside the segment
        out.append((lo + (hi - lo) * frac)[1:])
    return np.concatenate(out)
