"""Loader for BatPackdata.mat (10 in-service EV packs, Deng et al., J. Energy Chem. 2024).

The file is MATLAB v7.3 (HDF5). It holds a 10x1 struct array ``BatPackdata`` with fields
Veh, Type, Cn, Ncell, SOH, SOC_OCV and data. ``data`` is a struct whose sub-fields are read
generically here, because the README's column list does not match the stored layout.
The original lives in external/ and is opened read-only.
"""
from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
EV10_MAT = ROOT / "external" / "Charging-test-data-of-in-service-electric-vehicles" / "BatPackdata.mat"


def _read(f: h5py.File, obj):
    """Convert a MATLAB v7.3 object (dataset or struct group) into Python values."""
    if isinstance(obj, h5py.Group):
        return {k: _read(f, obj[k]) for k in obj}
    cls = obj.attrs.get("MATLAB_class", b"")
    cls = cls.decode() if isinstance(cls, bytes) else cls
    if obj.attrs.get("MATLAB_empty", 0):
        return np.array([])
    val = obj[()]
    if cls == "char":
        return "".join(map(chr, np.asarray(val).ravel()))
    if obj.dtype == h5py.ref_dtype:
        refs = np.asarray(val)
        items = [_read(f, f[r]) for r in refs.ravel()]
        return items
    arr = np.asarray(val)
    # MATLAB stores column-major; a 1xN vector arrives as (N,1) or (1,N) -> flatten vectors
    return arr.ravel() if 1 in arr.shape else arr.T


def load_ev10(path: Path = EV10_MAT) -> list[dict]:
    with h5py.File(path, "r") as f:
        g = f["BatPackdata"]
        n = g["Veh"].shape[0] * g["Veh"].shape[1]
        packs = []
        for i in range(n):
            pack = {}
            for field in g:
                ref = g[field][()].ravel()[i]
                v = _read(f, f[ref])
                if isinstance(v, np.ndarray) and v.size == 1:
                    v = float(v.ravel()[0])
                pack[field] = v
            packs.append(pack)
    return packs
