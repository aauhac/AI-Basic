"""Small I/O helpers."""
from __future__ import annotations

import json
from pathlib import Path


def write_json(obj, path: Path) -> None:
    """UTF-8 JSON with the file closed deterministically (no ResourceWarning)."""
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
