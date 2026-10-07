"""Runtime building blocks: DuckDB engine, lease lock, ledger, keys, verification results.

Kept in one module so the layer engines import a single, small surface.
"""
from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from . import config as C
from .project import Project, audit, now_iso


# ================================================================ SQL quoting helpers
def qi(name: str) -> str:
    """Quote an identifier taken from data or specs (header names may contain anything)."""
    return '"' + str(name).replace('"', '""') + '"'


def ql(value) -> str:
    """Quote a string literal (paths, ids) for statements that cannot take bound parameters."""
    return "'" + str(value).replace("'", "''") + "'"


def qpath(path) -> str:
    return ql(Path(path).as_posix())


# ================================================================ engine
def connect(project: Project, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(project.warehouse), read_only=read_only)
    tz = (C.get_path(project.document(), "policies.timezone.reporting") or "UTC").strip()
    from zoneinfo import ZoneInfo
    ZoneInfo(tz)  # validated: the value is interpolated below
    con.execute(f"SET TimeZone='{tz}'")
    threads = os.environ.get("DWH_THREADS")
    if threads:
        con.execute(f"SET threads={int(threads)}")
    tmp = project.state / "tmp"
    tmp.mkdir(exist_ok=True)
    con.execute(f"SET temp_directory={qpath(tmp)}")
    mem = os.environ.get("DWH_MEMORY_LIMIT")
    if mem and C.as_int(mem.rstrip("GBMgbm") or "0") >= 0:
        con.execute(f"SET memory_limit='{mem}'")
    con.execute("SET preserve_insertion_order=true")
    return con


def table_exists(con, name: str) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [name]).fetchone()[0] > 0


def run_id() -> str:
    return os.environ.get("DWH_RUN_ID") or time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"-{os.getpid()}"


# ================================================================ lease lock
class LockHeld(RuntimeError):
    pass


STALE_SECONDS = 15 * 60


_ACTIVE: list = []


def heartbeat() -> None:
    """Long builds call this between batches so a live run is never mistaken for a stale one."""
    if _ACTIVE:
        try:
            _ACTIVE[-1].heartbeat()
        except Exception:
            pass


def _pid_alive(pid: int) -> bool:
    """Is a process with this id running on this machine? (POSIX signal 0 / Windows OpenProcess)"""
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Lease:
    """Exclusive lease on the warehouse. Never delete the lock or the WAL by hand."""

    def __init__(self, project: Project, skill: str):
        self.project, self.skill = project, skill
        self.path = project.state / "lock.json"
        self.rid = run_id()

    def _payload(self) -> dict:
        return {"pid": os.getpid(), "host": socket.gethostname(), "skill": self.skill,
                "run_id": self.rid, "started": now_iso(), "heartbeat": time.time()}

    def _stale(self, held: dict) -> bool:
        if time.time() - float(held.get("heartbeat", 0)) > STALE_SECONDS:
            return True
        if held.get("host") == socket.gethostname():
            try:
                return not _pid_alive(int(held["pid"]))
            except (KeyError, ValueError):
                return True
        return False

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._payload(), fh)
                audit(self.project, "lock.acquire", skill=self.skill, run_id=self.rid)
                _ACTIVE.append(self)
                return self
            except FileExistsError:
                try:
                    held = json.loads(self.path.read_text(encoding="utf-8") or "{}")
                except (json.JSONDecodeError, OSError):
                    held = {}
                if held and not self._stale(held):
                    raise LockHeld(
                        f"{held.get('skill')} run {held.get('run_id')} (pid {held.get('pid')}) holds the "
                        f"warehouse since {held.get('started')}. Wait for it to finish; do not delete "
                        f"the lock or the database WAL.")
                audit(self.project, "lock.stale_recovered", previous=held)
                self.path.unlink(missing_ok=True)
        raise LockHeld("could not acquire the warehouse lease")

    def heartbeat(self) -> None:
        if self.path.exists():
            held = json.loads(self.path.read_text(encoding="utf-8"))
            if held.get("pid") == os.getpid():
                held["heartbeat"] = time.time()
                C.atomic_write_text(self.path, json.dumps(held))

    def __exit__(self, *exc):
        if self in _ACTIVE:
            _ACTIVE.remove(self)
        try:
            held = json.loads(self.path.read_text(encoding="utf-8"))
            if held.get("pid") == os.getpid() and held.get("run_id") == self.rid:
                self.path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        audit(self.project, "lock.release", skill=self.skill, run_id=self.rid)
        return False


# ================================================================ ledger
def ledger_path(project: Project, layer: str) -> Path:
    return project.state / "ledger" / f"{layer}.json"


def ledger(project: Project, layer: str) -> dict:
    return C.read_json(ledger_path(project, layer), {}) or {}


def ledger_write(project: Project, layer: str, data: dict) -> None:
    """Called only after the batch's transaction has COMMITTED."""
    C.atomic_write_json(ledger_path(project, layer), data)


# ================================================================ keys
def canon_sql(col: str, typ: str) -> str:
    """Canonical text of a key column (key_algo v1). Never change it in place: bump KEY_ALGO."""
    t = typ.upper()
    q = f'"{col}"'
    if t.startswith(("VARCHAR", "TEXT", "STRING", "CHAR")):
        return f"trim({q})"
    if t.startswith("TIMESTAMP"):
        return f"strftime({q}, '%Y-%m-%dT%H:%M:%S.%f')"
    if t == "DATE":
        return f"strftime({q}, '%Y-%m-%d')"
    return f"CAST({q} AS VARCHAR)"


def key_sql(cols: list[tuple[str, str]]) -> str:
    """md5 of a JSON struct of canonicalised values: delimiter-free and NULL-safe."""
    parts = ", ".join(f"k{i} := {canon_sql(c, t)}" for i, (c, t) in enumerate(cols))
    return f"md5(to_json(struct_pack({parts})))"


# ================================================================ verification
class VerificationError(RuntimeError):
    """Raised explicitly — never `assert`, which `python -O` strips."""


@dataclass
class Check:
    id: str
    name: str
    passed: bool
    expected: Any
    actual: Any
    evaluated: int | None = None
    detail: str = ""
    fatal: bool = True


@dataclass
class Results:
    layer: str
    scope: str
    checks: list[Check] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    def check(self, cid: str, name: str, passed: bool, expected: Any, actual: Any,
              evaluated: int | None = None, detail: str = "", fatal: bool = True) -> bool:
        # non-vacuous: a check that looked at zero rows proves nothing
        if evaluated is not None and evaluated == 0:
            passed, detail = False, (detail + " · evaluated 0 rows (vacuous)").strip(" ·")
        self.checks.append(Check(cid, name, bool(passed), expected, actual, evaluated, detail, fatal))
        return bool(passed)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed and c.fatal]

    def raise_if_failed(self) -> None:
        if self.failures:
            lines = [f"{c.id} {c.name}: expected {c.expected}, got {c.actual}"
                     + (f" ({c.detail})" if c.detail else "") for c in self.failures]
            raise VerificationError(f"{self.layer} verification failed for {self.scope}:\n  " + "\n  ".join(lines))

    def to_dict(self) -> dict:
        return {"layer": self.layer, "scope": self.scope, "facts": self.facts,
                "checks": [vars(c) for c in self.checks],
                "passed": not self.failures}

    def write(self, project: Project, name: str, title: str, intro: str = "") -> Path:
        """Artefact rendered FROM the results JSON (never hand-written text)."""
        data = self.to_dict()
        jpath = project.layout.report(name, "json")
        C.atomic_write_json(jpath, data)
        rows = "\n".join(
            f"| {c.id} | {c.name} | {'PASS' if c.passed else ('FAIL' if c.fatal else 'WARN')} | "
            f"{_cell(c.expected)} | {_cell(c.actual)} | {'' if c.evaluated is None else c.evaluated} | {_cell(c.detail)} |"
            for c in self.checks)
        facts = "\n".join(f"| {k} | {_cell(v)} |" for k, v in self.facts.items())
        text = (f"# {title}\n\n*Generated by dwh_core from `{project.rel(jpath)}` — "
                f"do not edit by hand.*\n\n{intro}\n\n"
                + (f"| Fact | Value |\n|---|---|\n{facts}\n\n" if facts else "")
                + "| ID | Check | Result | Expected | Actual | Rows evaluated | Detail |\n"
                  "|---|---|---|---|---|---|---|\n" + rows + "\n")
        from . import egress
        mpath = project.layout.report(name, "md")
        egress.assert_clean(text, where=project.rel(mpath))
        C.atomic_write_text(mpath, text)
        return mpath


def _cell(v: Any) -> str:
    s = json.dumps(v, default=str) if isinstance(v, (dict, list)) else str(v)
    return s.replace("|", "\\|").replace("\n", " ")[:200]
