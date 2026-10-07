#!/usr/bin/env python3
"""Package the skills for installing in Claude: python tools/package_skills.py [--out dist]

Writes dist/skills/<skill>/ (dwh-init gets the kernel from framework/dwh_core as kernel/dwh_core,
so the packaged skill works outside this repository) and dist/<skill>.skill (a zip of that
folder). The validation suite runs against dist/skills/.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

from _repo import KERNEL, REPO, SKILLS, kernel_version

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", ".ruff_cache", ".pytest_cache")


def build(out: Path) -> list[Path]:
    staging = out / "skills"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    made = []
    for skill in sorted(p for p in SKILLS.iterdir() if (p / "SKILL.md").exists()):
        dst = staging / skill.name
        shutil.copytree(skill, dst, ignore=IGNORE)
        if skill.name == "dwh-init":
            shutil.copytree(KERNEL, dst / "kernel" / "dwh_core", ignore=IGNORE)
        archive = out / f"{skill.name}.skill"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(dst.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(staging).as_posix())
        made.append(archive)
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "dist"))
    args = ap.parse_args()
    made = build(Path(args.out).resolve())
    print(f"dwh_core {kernel_version()} — packaged {len(made)} skills:")
    for m in made:
        print(f"  {m}  ({m.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
