"""Extract NASA PCoE battery .mat files from the official nested ZIP without modifying it.

The official archive contains six inner ZIPs. Each inner ZIP is read in memory and its
files are written to data/raw/nasa/<inner zip stem>/. A file whose SHA-256 was already
extracted from an earlier inner ZIP is not written again; it is recorded as a duplicate.

Usage: python -I src/data/extract_nasa.py <path to "5.+Battery+Data+Set.zip">
"""
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "nasa"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(zip_path: str) -> None:
    src = Path(zip_path).resolve()
    outer = zipfile.ZipFile(src)
    if outer.testzip() is not None:
        raise SystemExit("outer zip CRC failure")

    seen: dict[str, str] = {}  # sha256 -> relative path already written
    manifest = {"source_zip": src.name, "source_size": src.stat().st_size,
                "source_sha256": sha256(src.read_bytes()), "files": [], "duplicates": []}

    for info in outer.infolist():
        if not info.filename.endswith(".zip"):
            continue
        inner = zipfile.ZipFile(io.BytesIO(outer.read(info)))
        bad = inner.testzip()
        if bad is not None:
            raise SystemExit(f"CRC failure in {info.filename}: {bad}")
        stem = Path(info.filename).stem
        for member in inner.infolist():
            if member.is_dir():
                continue
            data = inner.read(member)
            digest = sha256(data)
            rel = f"{stem}/{Path(member.filename).name}"
            if digest in seen and member.filename.endswith(".mat"):
                manifest["duplicates"].append({"path": rel, "same_as": seen[digest], "sha256": digest})
                continue
            dest = OUT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                if sha256(dest.read_bytes()) != digest:
                    raise SystemExit(f"refusing to overwrite differing file {dest}")
            else:
                dest.write_bytes(data)
            seen.setdefault(digest, rel)
            manifest["files"].append({"path": rel, "size": len(data), "sha256": digest})

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    mats = [f for f in manifest["files"] if f["path"].endswith(".mat")]
    print(f"written: {len(manifest['files'])} files ({len(mats)} .mat), duplicates skipped: {len(manifest['duplicates'])}")
    for d in manifest["duplicates"]:
        print(f"  dup {d['path']} == {d['same_as']}")


if __name__ == "__main__":
    main(sys.argv[1])
