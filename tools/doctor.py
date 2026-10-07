#!/usr/bin/env python3
"""First step on a new machine: python tools/doctor.py [name ...]

Runs the environment doctor for each pipeline (all of them by default). It checks this Python and
its packages and writes the pipeline's `dwh` (Git Bash / macOS / Linux) and `dwh.cmd` (cmd /
PowerShell) wrappers, which are machine-specific and therefore not in git.
"""
from __future__ import annotations

import sys

from _repo import dwh, pipelines


def main() -> int:
    names = sys.argv[1:]
    found = [p for p in pipelines() if not names or p.name in names]
    if not found:
        print("no matching pipelines (pipelines/*/dwh-project.yaml)")
        return 1
    rc = 0
    for p in found:
        r = dwh(p, "doctor")
        print(f"== pipelines/{p.name}\n{r.stdout.rstrip()}")
        rc |= r.returncode
    print("\nnow: cd pipelines/<name> && ./dwh status   (Windows: dwh.cmd status)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
