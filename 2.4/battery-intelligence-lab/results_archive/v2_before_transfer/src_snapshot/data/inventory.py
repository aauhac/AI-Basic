"""Write docs/file_inventory.md: every raw data file with size and SHA-256.

Usage: .venv/Scripts/python -m src.data.inventory
"""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ("NASA 원본 ZIP", ROOT.parent, ["5.+Battery+Data+Set.zip"]),
    ("NASA 추출본 (data/raw/nasa)", ROOT / "data" / "raw" / "nasa", ["**/*.mat", "**/*.txt"]),
    ("EV10 (external/Charging-test-data-of-in-service-electric-vehicles)",
     ROOT / "external" / "Charging-test-data-of-in-service-electric-vehicles", ["*"]),
    ("EV20 저장소 (external/battery-charging-data-of-on-road-electric-vehicles)",
     ROOT / "external" / "battery-charging-data-of-on-road-electric-vehicles", ["*"]),
    ("EV20 추출본 (data/raw/ev_20)", ROOT / "data" / "raw" / "ev_20", ["*.csv"]),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(repo: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%H %ci"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def main() -> None:
    lines = ["# 데이터 파일 목록", "", "`python -m src.data.inventory`로 생성. 크기는 byte 단위.", ""]
    for title, base, patterns in SOURCES:
        files = sorted({p for pat in patterns for p in base.glob(pat) if p.is_file()},
                       key=lambda p: (len(p.stem), str(p)))
        lines += [f"## {title}", ""]
        head = git_head(base) if (base / ".git").exists() else ""
        if head:
            lines += [f"Git commit: `{head}`", ""]
        if not files:
            lines += ["(파일 없음)", ""]
            continue
        lines += ["| 파일 | 크기 (bytes) | SHA-256 |", "|---|---:|---|"]
        total = 0
        for p in files:
            size = p.stat().st_size
            total += size
            lines.append(f"| `{p.relative_to(base).as_posix()}` | {size:,} | `{sha256(p)}` |")
        lines += ["", f"합계 {len(files)}개, {total:,} bytes ({total / 1024**2:,.1f} MB)", ""]
    out = ROOT / "docs" / "file_inventory.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
