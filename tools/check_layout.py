#!/usr/bin/env python3
"""Check that every pipeline folder follows the contract: python tools/check_layout.py [name ...]

The contract (docs/pipeline-contract.md), checked per pipeline:
  P1 dwh-project.yaml says layout v2 and pins THIS repository's kernel version and key algorithm
  P2 README.md, requirements/ (with a file) and data/manifest.yaml exist
  P3 every spec file under bronze/specs/sources, silver/specs/entities, gold/specs/metrics holds
     exactly one top-level item, whose name gives the file name
  P4 no layout-v1 folders are left (config/, artefacts/, pipeline/, serving/, dead_letter/)
  P5 nothing that must stay out of git is tracked (data/raw/, .dwh/, wrappers, a kernel copy,
     intake/current/), and no tracked file is over 5 MB
  P6 workbooks only in intake/workbooks/; data-shaped files (.csv .parquet .duckdb) only in
     data/synthetic/ and gold/checks/
Exit 0 = all pipelines conform; 1 = a problem, listed with the fix.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from _repo import FRAMEWORK, REPO, git_tracked, key_algo, kernel_version, manifest, pipelines

sys.path.insert(0, str(FRAMEWORK))
from dwh_core.project import spec_file_stem  # noqa: E402  (the kernel's own item → file-name rule)

MAX_BYTES = 5 * 1024 * 1024
V1_FOLDERS = ("config", "artefacts", "pipeline", "serving", "dead_letter")
NOT_IN_GIT = ("data/raw/", ".dwh/", "dwh_core/", "intake/current/")
NOT_IN_GIT_FILES = ("dwh", "dwh.cmd")
SPEC_DIRS = ("bronze/specs/sources", "silver/specs/entities", "gold/specs/metrics")
DATA_SUFFIXES = (".csv", ".parquet", ".duckdb", ".tsv")
DATA_OK = ("data/synthetic/", "gold/checks/")


def check(p: Path) -> list[str]:
    errs: list[str] = []
    rel = lambda f: f.relative_to(p).as_posix()  # noqa: E731
    m = manifest(p)
    if str(m.get("layout", "v1")) != "v2":
        errs.append("P1 dwh-project.yaml: project.layout must be v2 (run `./dwh layout migrate`)")
    if str(m.get("dwh_core_version", "")) != kernel_version():
        errs.append(f"P1 pins dwh_core {m.get('dwh_core_version') or '(none)'}, the framework is {kernel_version()} "
                    "— upgrade the pin in its own pull request (CONTRIBUTING.md)")
    if str(m.get("key_algo", "")) != key_algo():
        errs.append(f"P1 key_algo {m.get('key_algo')!r} differs from the kernel's {key_algo()!r}")
    if not (p / "README.md").exists():
        errs.append("P2 README.md missing")
    req = p / "requirements"
    if not req.is_dir() or not any(f.is_file() and f.name != ".gitkeep" for f in req.rglob("*")):
        errs.append("P2 requirements/ is empty — add request.md (what was asked)")
    if not (p / "data" / "manifest.yaml").exists():
        errs.append("P2 data/manifest.yaml missing — run `python tools/data_manifest.py <name>`")
    for d in SPEC_DIRS:
        for f in sorted((p / d).glob("*.yaml")) if (p / d).is_dir() else []:
            try:
                data = yaml.load(f.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
            except yaml.YAMLError as e:
                errs.append(f"P3 {rel(f)}: not valid YAML ({str(e).splitlines()[0]})")
                continue
            keys = list(data) if isinstance(data, dict) else []
            if len(keys) != 1 or spec_file_stem(keys[0]) != f.stem:
                errs.append(f"P3 {rel(f)}: must hold exactly one top-level item, named after the file (has {keys})")
    for d in V1_FOLDERS:
        if (p / d).exists():
            errs.append(f"P4 {d}/ is a layout-v1 folder — run `./dwh layout migrate`")
    tracked = git_tracked(p)
    base = p.relative_to(REPO).as_posix() + "/"
    for t in tracked:
        local = t[len(base):] if t.startswith(base) else t
        if local.startswith(NOT_IN_GIT) or local in NOT_IN_GIT_FILES:
            errs.append(f"P5 {local} is tracked but must stay out of git (`git rm --cached {t}`)")
        f = REPO / t
        if f.is_file() and f.stat().st_size > MAX_BYTES:
            errs.append(f"P5 {local} is {f.stat().st_size // 1024 // 1024} MB — data and large files stay out of git")
        if local.endswith((".xlsx", ".xls")) and not local.startswith("intake/workbooks/"):
            errs.append(f"P6 {local}: workbooks belong in intake/workbooks/")
        if local.endswith(DATA_SUFFIXES) and not local.startswith(DATA_OK):
            errs.append(f"P6 {local}: data-shaped files only in {' or '.join(DATA_OK)}")
    return errs


def main() -> int:
    names = sys.argv[1:]
    found = [p for p in pipelines() if not names or p.name in names]
    if names and len(found) != len(names):
        print(f"unknown pipeline(s): {sorted(set(names) - {p.name for p in found})}")
        return 1
    bad = 0
    for p in found:
        errs = check(p)
        print(f"{'ok  ' if not errs else 'FAIL'} pipelines/{p.name}")
        for e in errs:
            print(f"     - {e}")
        bad += bool(errs)
    if not found:
        print("no pipelines found (pipelines/*/dwh-project.yaml)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
