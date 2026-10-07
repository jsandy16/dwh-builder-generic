#!/usr/bin/env python3
"""CI check of every pipeline: python tools/check_pipelines.py [name ...]

For each pipeline (pipelines/*/dwh-project.yaml):
  1. the folder contract (tools/check_layout.py);
  2. the intake gates A of every layer (all answers present and valid; the data-dependent gate B
     runs at build time): answers not given yet are reported, not failed; a wrong or tampered
     answer, a refusal or a crash fails;
  3. generated code matches the specs: the code is re-rendered in a scratch copy and compared
     byte for byte with what is committed (a hand edit, or specs changed without `dwh generate`,
     fails here).
Raw data is not needed: nothing here reads data/raw or the warehouse.
"""
from __future__ import annotations

import filecmp
import json
import shutil
import sys
import tempfile
from pathlib import Path

import check_layout
from _repo import dwh, pipelines

LAYERS = ("bronze", "silver", "gold", "serve")
SKILLS = ("project", "bronze", "silver", "gold", "serve")
# gate problems that mean "not answered yet" — a pipeline in intake; anything else is a wrong answer
WAITING = ("missing", "pending", "inferred value awaiting confirmation", "drafted by the assistant",
           "needs at least")
SKIP = shutil.ignore_patterns(".dwh", "raw", "dwh", "dwh.cmd", "__pycache__", "current")


def _files(root: Path) -> dict[str, Path]:
    out = {}
    for lay in LAYERS:
        g = root / lay / "generated"
        for f in sorted(g.rglob("*")) if g.is_dir() else []:
            if f.is_file() and "__pycache__" not in f.parts and f.name != ".gitkeep":
                out[f.relative_to(root).as_posix()] = f
    return out


def drift(p: Path) -> list[str]:
    with tempfile.TemporaryDirectory(prefix=f"dwh-ci-{p.name}-") as tmp:
        copy = Path(tmp) / p.name
        shutil.copytree(p, copy, ignore=SKIP)
        r = dwh(copy, "generate")
        if r.returncode != 0:
            return [f"`dwh generate` failed: {(r.stdout + r.stderr).strip()[-600:]}"]
        mine, theirs = _files(copy), _files(p)
        errs = [f"{k}: committed but not rendered by the specs (delete it)" for k in sorted(set(theirs) - set(mine))]
        errs += [f"{k}: rendered by the specs but not committed (run `./dwh generate`)" for k in sorted(set(mine) - set(theirs))]
        errs += [f"{k}: differs from what the specs render (hand edit, or specs changed without `./dwh generate`)"
                 for k in sorted(set(mine) & set(theirs)) if not filecmp.cmp(mine[k], theirs[k], shallow=False)]
        return errs


def main() -> int:
    names = sys.argv[1:]
    found = [p for p in pipelines() if not names or p.name in names]
    failed = 0
    for p in found:
        print(f"== pipelines/{p.name}")
        errs = check_layout.check(p)
        for e in errs:
            print(f"   FAIL contract: {e}")
        waiting, invalid = [], []
        for skill in SKILLS:   # gate A: every answer present and valid (gate B needs loaded data: build time)
            r = dwh(p, "intake", "check", skill, "--gate", "A", "--json")
            if r.returncode == 0:
                continue
            try:
                errors = json.loads(r.stdout)["errors"]
            except (ValueError, KeyError, TypeError):   # refused before checking (pin, layout) or crashed
                invalid.append(f"{skill}: exit {r.returncode}: {(r.stdout + r.stderr).strip()[-400:]}")
                continue
            for e in errors:
                (waiting if e["problem"].startswith(WAITING) else invalid).append(
                    f"{skill}: `{e['path']}` {e['problem']}")
        gates_ok = not waiting and not invalid
        errs += [f"intake: {i}" for i in invalid]
        for i in invalid[:20]:
            print(f"   FAIL intake {i}")
        if waiting and not invalid:
            print(f"   note intake gates: {len(waiting)} answer(s) still to come (e.g. {waiting[0]})")
        elif gates_ok:
            print("   ok   intake gates (A): every answer every layer needs is recorded and valid")
        if gates_ok:
            d = drift(p)
            errs += d
            for e in d:
                print(f"   FAIL generated: {e}")
            if not d:
                print("   ok   generated code matches the specs")
        else:
            print("   skip generated-code check (the specs are not complete yet)")
        failed += bool(errs)
    print(f"\n{len(found) - failed}/{len(found)} pipeline(s) passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
