"""Shared matplotlib style: recessive hairline grid, thin marks, fixed categorical order."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
BATTERY_COLOR = {"B0005": SERIES[0], "B0006": SERIES[1], "B0007": SERIES[2], "B0018": SERIES[3]}
MODEL_COLOR = {"LinearRegression": SERIES[0], "RandomForest": SERIES[1], "SVR_RBF": SERIES[2],
               "XGBoost": SERIES[3], "Stacking": SERIES[4]}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.titlecolor": INK, "axes.titlesize": 11,
    "axes.labelsize": 9, "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelsize": 8,
    "ytick.labelsize": 8, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "grid.linestyle": "-", "axes.axisbelow": True,"axes.spines.top": False, "axes.spines.right": False,
    "lines.linewidth": 1.6, "legend.frameon": False, "legend.fontsize": 8, "font.size": 9,
    "font.family": ["Malgun Gothic", "DejaVu Sans"], "axes.unicode_minus": False, "figure.dpi": 110,
    "mathtext.fontset": "dejavusans",  # log-axis tick labels use mathtext; Malgun Gothic lacks U+2212
})


def save(fig, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
