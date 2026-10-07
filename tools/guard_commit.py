#!/usr/bin/env python3
"""pre-commit guard: refuse files that must never be committed (raw data, local state, secrets).

Called by pre-commit with the staged file names. Refuses:
  * anything under a pipeline's data/raw/, .dwh/ or intake/current/, the dwh / dwh.cmd wrappers,
    a dwh_core copy inside a pipeline, a file named salt;
  * files over 5 MB anywhere;
  * text that looks like a credential (private keys, AWS keys, GitHub tokens, "password=" lines),
    unless that line carries the marker `guard: fake credential` (test fixtures only).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
BLOCKED = re.compile(r"^pipelines/[^/]+/(data/raw/|\.dwh/|intake/current/|dwh_core/|dwh$|dwh\.cmd$)")
SECRET = re.compile(r"(-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ghp_[0-9A-Za-z]{36}|"
                    r"github_pat_[0-9A-Za-z_]{40,}|(?i:password|passwd|secret_key)\s*[:=]\s*['\"]?[^\s'\"]{6,})")


def main(files: list[str]) -> int:
    bad = []
    for name in files:
        f = Path(name)
        posix = f.as_posix()
        if BLOCKED.search(posix) or f.name == "salt":
            bad.append(f"{posix}: data / local state — never committed")
            continue
        if f.is_file() and f.stat().st_size > MAX_BYTES:
            bad.append(f"{posix}: {f.stat().st_size // 1024 // 1024} MB — too large for git")
            continue
        if f.is_file() and f.suffix not in (".xlsx", ".png", ".parquet", ".zip", ".skill"):
            try:
                lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                lines = []
            if any(SECRET.search(ln) and "guard: fake credential" not in ln for ln in lines):
                bad.append(f"{posix}: looks like it contains a credential")
    for b in bad:
        print("refused:", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
