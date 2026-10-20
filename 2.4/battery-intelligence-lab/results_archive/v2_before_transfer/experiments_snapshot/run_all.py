"""Run every experiment and the test suite; record wall-clock time and outcome of each step.

Usage: .venv/Scripts/python -m experiments.run_all
Writes results/runtime.json and results/tests/pytest_output.txt (+ junit.xml).
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    ("audit_stacking_cv", [sys.executable, "-u", "-m", "experiments.audit_stacking_cv"]),
    ("nasa_experiments", [sys.executable, "-u", "-m", "experiments.nasa_experiments"]),
    ("ev20_analysis", [sys.executable, "-u", "-m", "experiments.ev20_analysis"]),
    ("ev10_external", [sys.executable, "-u", "-m", "experiments.ev10_external"]),
    ("compare_versions", [sys.executable, "-u", "-m", "experiments.compare_versions"]),
    ("pytest", [sys.executable, "-m", "pytest", "-q", "tests", "--junitxml", "results/tests/junit.xml"]),
]


def main():
    (ROOT / "results" / "logs").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "tests").mkdir(parents=True, exist_ok=True)
    record = {"started": datetime.now().isoformat(timespec="seconds"), "python": sys.version.split()[0],
              "platform": platform.platform(), "processor": platform.processor(), "steps": {}}
    t_all = time.perf_counter()
    for name, cmd in STEPS:
        t0 = time.perf_counter()
        log = ROOT / ("results/tests/pytest_output.txt" if name == "pytest" else f"results/logs/{name}.log")
        with open(log, "w", encoding="utf-8") as f:
            rc = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT).returncode
        record["steps"][name] = {"seconds": round(time.perf_counter() - t0, 1), "returncode": rc, "log": str(log.relative_to(ROOT))}
        print(f"{name}: rc={rc} {record['steps'][name]['seconds']} s", flush=True)
    record["total_seconds"] = round(time.perf_counter() - t_all, 1)
    (ROOT / "results" / "runtime.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=1))


if __name__ == "__main__":
    main()
