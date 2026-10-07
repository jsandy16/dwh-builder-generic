#!/usr/bin/env python3
"""Record or verify which raw files a pipeline was built from.

    python tools/data_manifest.py <name>            # (re)write pipelines/<name>/data/manifest.yaml
    python tools/data_manifest.py <name> --check    # verify data/raw matches the manifest

Raw data never enters git. The manifest does: one entry per file under data/raw/ with its size,
sha256 and (for CSV/Parquet) row count, so anyone rebuilding can prove they hold the same files.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from _repo import PIPELINES


def _sha256(f: Path) -> str:
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(f: Path) -> int | None:
    if f.suffix.lower() == ".csv":
        with open(f, encoding="utf-8", errors="replace", newline="") as fh:
            return max(sum(1 for _ in csv.reader(fh)) - 1, 0)
    if f.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq
            return pq.ParquetFile(f).metadata.num_rows
        except Exception:
            return None
    return None


def scan(raw: Path) -> list[dict]:
    out = []
    for f in sorted(raw.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            out.append({"file": f.relative_to(raw).as_posix(), "bytes": f.stat().st_size, "sha256": _sha256(f),
                        "rows": _rows(f)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    p = PIPELINES / args.name
    raw, mf = p / "data" / "raw", p / "data" / "manifest.yaml"
    if not raw.is_dir():
        print(f"no {raw}")
        return 2
    files = scan(raw)
    if args.check:
        want = {e["file"]: e for e in (yaml.safe_load(mf.read_text(encoding="utf-8")) or {}).get("files", [])}
        have = {e["file"]: e for e in files}
        problems = [f"missing: {k}" for k in sorted(set(want) - set(have))]
        problems += [f"not in the manifest: {k}" for k in sorted(set(have) - set(want))]
        problems += [f"different content: {k}" for k in sorted(set(want) & set(have))
                     if want[k]["sha256"] != have[k]["sha256"]]
        print("\n".join(problems) or f"data/raw matches the manifest ({len(have)} files)")
        return 1 if problems else 0
    doc = {"pipeline": args.name,
           "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
           "note": "raw files are not in git; this lists exactly which files the build used",
           "files": files}
    mf.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"wrote {mf.relative_to(PIPELINES.parent)}: {len(files)} files, "
          f"{sum(e['bytes'] for e in files) // 1024 // 1024} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
