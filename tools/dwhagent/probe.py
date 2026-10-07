#!/usr/bin/env python3
"""Counts-only diagnostics for the dwh agent (it may not read the warehouse or the raw files).

    python ../../tools/dwhagent/probe.py <pipeline> tables
    python ../../tools/dwhagent/probe.py <pipeline> dead-letters
    python ../../tools/dwhagent/probe.py <pipeline> what-if --set <answer path>=<value> [--set …] --build silver|gold

`what-if` copies the pipeline (with its warehouse) to a temporary folder, records the changed
answers THERE ONLY, builds the layer and prints the result and the dead-letter counts. Nothing in
the real pipeline changes: use it to test a proposal before putting it to the owner.
Output is table names, entity / batch / rule names and counts — never row values.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _con(pipeline: Path):
    import duckdb
    db = pipeline / ".dwh" / "warehouse.duckdb"
    if not db.exists():
        raise SystemExit("nothing built yet (no warehouse)")
    return duckdb.connect(str(db), read_only=True)


def tables(pipeline: Path) -> None:
    con = _con(pipeline)
    names = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name SIMILAR TO '(bronze|silver|gold)_.*' "
        "ORDER BY 1").fetchall()]
    for n in names:
        cnt = con.execute('SELECT COUNT(*) FROM "' + n.replace('"', '""') + '"').fetchone()[0]
        print(f"{n}: {cnt:,} rows")


def dead_letters(pipeline: Path) -> None:
    con = _con(pipeline)
    if con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'silver_dead_letter'").fetchone()[0]:
        rows = con.execute("SELECT entity, batch_id, reason, COUNT(*) FROM silver_dead_letter "
                           "GROUP BY 1, 2, 3 ORDER BY 1, 2, 4 DESC").fetchall()
        print("silver dead letters (entity | batch | reason | rows):")
        for e, b, r, n in rows:
            print(f"  {e} | {b} | {r} | {n:,}")
        if not rows:
            print("  none")
    rej = pipeline / ".dwh" / "dead_letter" / "rejected_files.csv"
    if rej.exists():
        import csv
        print("files rejected by bronze (source | batch | reason | detail):")
        for r in csv.DictReader(open(rej, encoding="utf-8")):
            print(f"  {r['source']} | {r['batch']} | {r['reason']} | {r['detail'][:120]}")


def _owner_of(pipeline: Path, path: str) -> str:
    sys.path.insert(0, str(REPO / "framework"))
    from dwh_core import catalogue as K
    from dwh_core.project import Project
    f, _ = K.find_field(path)
    role = (getattr(f, "owner", "") or "DE").upper()
    people = Project(pipeline).load_namespace("people") or {}
    for pid, rec in people.items():
        if isinstance(rec, dict) and role in [str(r).upper() for r in (rec.get("roles") or [])]:
            return pid
    return next(iter(people), "")


def what_if(pipeline: Path, sets: list[str], layer: str) -> int:
    with tempfile.TemporaryDirectory(prefix="dwh-what-if-") as tmp:
        copy = Path(tmp) / pipeline.name
        shutil.copytree(pipeline, copy, ignore=shutil.ignore_patterns("dwh", "dwh.cmd", "__pycache__"))
        env = {**os.environ, "PYTHONPATH": str(REPO / "framework"), "DWH_PROJECT": str(copy), "PYTHONUTF8": "1"}
        run = lambda *a: subprocess.run([sys.executable, "-m", "dwh_core", *a], cwd=copy, env=env,  # noqa: E731
                                        capture_output=True, text=True)
        for s in sets:
            path, _, value = s.partition("=")
            args = ["intake", "set", path]
            args += ["--yaml", value] if value[:1] in "[{" else [value]
            r = run(*args, "--by", _owner_of(copy, path))
            if r.returncode != 0:
                print(f"could not apply {path} in the scratch copy: {(r.stdout + r.stderr).strip()[-300:]}")
                return 2
        if layer == "silver":
            for e in _entities(copy):
                run("intake", "readback", e)
            for e in _entities(copy):
                run("intake", "set", f"silver.entities.{e}.readback_confirmed", "yes", "--by",
                    _owner_of(copy, f"silver.entities.{e}.readback_confirmed"))
        r = run("build", layer, *(["--rebuild"] if layer == "silver" else []))
        print(f"what-if ({', '.join(sets)}): `dwh build {layer}` exited {r.returncode}"
              + (" (scratch copy only; its rule read-backs were auto-confirmed to let the build run)"
                 if layer == "silver" else ""))
        print(_digest(r.stdout + r.stderr))
        if r.returncode == 0:
            dead_letters(copy)
        else:
            print("(nothing was rebuilt in the scratch copy, so there are no new dead-letter counts)")
        return 0


def _digest(text: str, limit: int = 60) -> str:
    """Engine output without the long 'Not applicable (recorded)' lists, the important part first."""
    keep, skipping = [], False
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("**") or line.startswith("#"):
            skipping = "not applicable" in line.lower()
            if skipping:
                continue
        if not skipping:
            keep.append(line)
    if len(keep) > limit:
        keep = keep[: limit - 10] + [f"… {len(keep) - limit} lines left out …"] + keep[-10:]
    return "\n".join(keep)


def _entities(pipeline: Path) -> list[str]:
    d = pipeline / "silver" / "specs" / "entities"
    return sorted(f.stem for f in d.glob("*.yaml")) if d.is_dir() else []


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    pipeline = REPO / "pipelines" / sys.argv[1]
    if not (pipeline / "dwh-project.yaml").exists():
        print(f"no pipeline {sys.argv[1]}")
        return 2
    cmd = sys.argv[2]
    if cmd == "tables":
        tables(pipeline)
        return 0
    if cmd == "dead-letters":
        dead_letters(pipeline)
        return 0
    if cmd == "what-if":
        rest = sys.argv[3:]
        sets = [rest[i + 1] for i, a in enumerate(rest) if a == "--set" and i + 1 < len(rest)]
        layer = rest[rest.index("--build") + 1] if "--build" in rest else "silver"
        if not sets or layer not in ("silver", "gold"):
            print("what-if needs --set <path>=<value> and --build silver|gold")
            return 2
        return what_if(pipeline, sets, layer)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
