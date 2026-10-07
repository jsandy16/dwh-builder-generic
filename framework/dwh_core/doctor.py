"""Environment doctor: catches the Windows/PATH problems before they cost an afternoon.

Checks the interpreter (not the Microsoft Store stub), the Python version, pinned packages and
DuckDB time-zone support, then writes `dwh` / `dwh.cmd` wrappers that call the ABSOLUTE
interpreter path, so `python3` aliases, missing `make` and `streamlit` not on PATH stop mattering.
"""
from __future__ import annotations

import importlib
import json
import os
import platform
import sys
from pathlib import Path

REQUIRED = {"duckdb": "1.1", "pandas": "2.0", "pyarrow": "14.0", "yaml": "6.0", "openpyxl": "3.1"}  # openpyxl: intake workbook
OPTIONAL = {"streamlit": "1.30", "plotly": "5.18"}


def _ver(v: str) -> tuple:
    out = []
    for p in v.split(".")[:3]:
        num = "".join(ch for ch in p if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def checks() -> list[tuple[str, bool, str]]:
    res = []
    exe = sys.executable or ""
    res.append(("interpreter is a real Python (not the Microsoft Store stub)",
                "windowsapps" not in exe.lower(), exe))
    res.append(("Python >= 3.10", sys.version_info >= (3, 10), platform.python_version()))
    for mod, minv in {**REQUIRED, **OPTIONAL}.items():
        try:
            m = importlib.import_module(mod)
            v = getattr(m, "__version__", "0")
            res.append((f"{mod} >= {minv}" + (" (optional: dashboard)" if mod in OPTIONAL else ""),
                        _ver(v) >= _ver(minv) or mod in OPTIONAL and _ver(v) >= _ver(minv), v))
        except ImportError:
            res.append((f"{mod} >= {minv}" + (" (optional: dashboard)" if mod in OPTIONAL else ""),
                        mod in OPTIONAL and False, "not installed"))
    try:
        import duckdb
        c = duckdb.connect()
        c.execute("SET TimeZone='America/New_York'")
        res.append(("DuckDB named time zones", True, "ok"))
    except Exception as e:
        res.append(("DuckDB named time zones", False, str(e)[:80]))
    res.append(("UTF-8 mode for file writes", os.environ.get("PYTHONUTF8") == "1" or sys.flags.utf8_mode
                or (sys.getfilesystemencoding() or "").lower() == "utf-8",
                f"fs={sys.getfilesystemencoding()} utf8_mode={sys.flags.utf8_mode}"))
    return res


def write_wrappers(root: Path) -> list[Path]:
    exe = sys.executable
    kernel_home = Path(__file__).resolve().parent.parent   # the folder holding dwh_core (project or shared)
    sh = root / "dwh"
    sh.write_text("#!/usr/bin/env bash\n# written by `dwh doctor`: absolute interpreter, no PATH guessing\n"
                  "export PYTHONUTF8=1\n"
                  f'export PYTHONPATH="{kernel_home.as_posix()}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
                  f'exec "{Path(exe).as_posix()}" -m dwh_core "$@"\n', encoding="utf-8", newline="\n")
    try:
        sh.chmod(0o755)
    except OSError:
        pass
    cmd = root / "dwh.cmd"
    cmd.write_text("@echo off\r\nrem written by `dwh doctor`: absolute interpreter, no PATH guessing\r\n"
                   "set PYTHONUTF8=1\r\n"
                   f'set "PYTHONPATH={kernel_home}"\r\n'
                   f'"{exe}" -m dwh_core %*\r\n', encoding="utf-8", newline="")
    return [sh, cmd]


def run(project, write: bool = True) -> int:
    res = checks()
    required_failed = [n for n, ok, _ in res if not ok and "optional" not in n]
    for name, ok, detail in res:
        mark = "ok  " if ok else ("WARN" if "optional" in name else "FAIL")
        print(f"[{mark}] {name}: {detail}")
    if project is not None and write:
        paths = write_wrappers(project.root)
        env = {"interpreter": sys.executable, "python": platform.python_version(),
               "platform": platform.platform(), "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in res]}
        (project.state / "env.json").write_text(json.dumps(env, indent=2), encoding="utf-8")
        print("wrappers:", ", ".join(p.name for p in paths),
              "— use ./dwh (Git Bash/macOS/Linux) or dwh.cmd (cmd/PowerShell)")
    if any("WindowsApps" in d for _, _, d in res):
        print("\nFix: install Python from python.org (tick 'Add python.exe to PATH') and turn off\n"
              "Settings > Apps > Advanced app settings > App execution aliases for python.exe/python3.exe.")
    return 0 if not required_failed else 1
