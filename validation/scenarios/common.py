"""Shared helpers for the validation scenarios: drive a project ONLY through its ./dwh wrapper,
exactly as the skills instruct the agent to."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
# folder holding dwh-init/, dwh-bronze/ … as packaged (dwh-init with kernel/): in the repository
# `python tools/run_validation.py` packages them and sets this; by hand: python tools/package_skills.py
SKILLS = Path(os.environ.get("DWH_SKILLS", HERE.parents[1] / "dist" / "skills"))
RUNS = Path(os.environ.get("DWH_RUNS", HERE.parent / "runs"))
PACK_SAMPLE = Path(os.environ.get("DWH_PACK_SAMPLE", HERE.parent / "fixtures" / "subscription_events_batch.csv"))
PACK_SILVER = Path(os.environ.get("DWH_PACK_SILVER", HERE.parent / "fixtures" / "subscription_events_clean.parquet"))
TMP = Path(os.environ.get("DWH_TMP_DIR", __import__("tempfile").gettempdir()))
WRAPPER = "dwh.cmd" if os.name == "nt" else "dwh"
INSTALL = SKILLS / "dwh-init" / "scripts" / "install.py"


LAYOUT = os.environ.get("DWH_TEST_LAYOUT", "v1")   # run the whole suite on layout v1 or v2
sys.path.insert(0, str(SKILLS / "dwh-init" / "kernel"))


class Fail(AssertionError):
    pass


def lay(root: Path):
    """The kernel's own map of where files live in this project (layout v1 or v2)."""
    from dwh_core.project import Layout
    return Layout(Path(root))


def loc(root: Path, key: str, **kw) -> Path:
    return lay(root).path(key, **kw)


def spec_file(root: Path, ns: str) -> Path:
    """The file holding a whole (non-split) namespace."""
    from dwh_core import project as P
    return Path(root) / (P._FILES_V2[ns] if lay(root).version == "v2" else P.SPEC_FILES[ns])


def spec(root: Path, ns: str):
    return lay(root).load_namespace(ns)


def provenance(root: Path) -> dict:
    out = {}
    for f in dict.fromkeys(lay(root).provenance_files().values()):
        if f.exists():
            out.update(yaml.safe_load(f.read_text()) or {})
    return out


def install(root: Path) -> Path:
    if root.exists():
        shutil.rmtree(root)
    r = subprocess.run([sys.executable, str(INSTALL), "--project", str(root), "--layout", LAYOUT],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise Fail(f"install failed: {r.stdout}\n{r.stderr}")
    return root


def env(extra: dict | None = None) -> dict:
    e = dict(os.environ)
    e.update({"DWH_FIXED_NOW": "2026-10-06T12:00:00+00:00", "DWH_RETRY_BASE": "0.01", "PYTHONUTF8": "1"})
    e.pop("DWH_PROJECT", None)
    e.update(extra or {})
    return e


def dwh(root: Path, *args, expect: int | None = 0, extra_env: dict | None = None, stdin: str | None = None):
    r = subprocess.run([str(root / WRAPPER), *args], cwd=root, capture_output=True, text=True,
                       env=env(extra_env), input=stdin)
    out = r.stdout + r.stderr
    if expect is not None and r.returncode != expect:
        raise Fail(f"`dwh {' '.join(args)}` exited {r.returncode}, expected {expect}:\n{out[-3000:]}")
    return r.returncode, out


def say(root: Path, path: str, value, by: str, quote: str | None = None, **kw):
    """Record an answer the way the agent does: verbatim value, attributed to the person who gave it."""
    if isinstance(value, (dict, list)):
        args = ["intake", "set", path, "--yaml", yaml.safe_dump(value, default_flow_style=True, sort_keys=False)]
    else:
        args = ["intake", "set", path, str(value)]
    if quote:
        args += ["--quote", quote]
    return dwh(root, *args, "--by", by, **kw)


def duck(root: Path, sql: str):
    import duckdb
    con = duckdb.connect(str(root / ".dwh" / "warehouse.duckdb"), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def results(root: Path, name: str) -> dict:
    return json.loads(lay(root).report(name, "json").read_text())


def check(cond: bool, msg: str, log: list):
    log.append(("PASS" if cond else "FAIL", msg))
    if not cond:
        raise Fail(msg)
