#!/usr/bin/env python3
"""Create a new pipeline: python tools/new_pipeline.py <name> [--title "Sales warehouse"]

Copies templates/pipeline/ to pipelines/<name>/, fills in the name, then runs the dwh-init
installer, which pins the shared kernel (framework/dwh_core) and writes the manifest
(layout v2), the salt and the ./dwh wrapper. Nothing outside pipelines/<name>/ changes: CI
finds the new pipeline by itself.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import date

from _repo import FRAMEWORK, NAME_RX, PIPELINES, SKILLS, TEMPLATE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="lower-case letters, digits and hyphens, e.g. sales or nyc-taxi")
    ap.add_argument("--title", help="human title for the README (default: the name)")
    args = ap.parse_args()
    if not NAME_RX.match(args.name):
        print(f"refused: '{args.name}' — use lower-case letters, digits and hyphens (start with a letter)")
        return 2
    dest = PIPELINES / args.name
    if dest.exists():
        print(f"refused: {dest} already exists")
        return 2
    shutil.copytree(TEMPLATE, dest)
    title = args.title or args.name
    for f in dest.rglob("*"):
        if f.is_file() and f.suffix in (".md", ".yaml", ".yml"):
            text = f.read_text(encoding="utf-8")
            text = (text.replace("{{name}}", args.name).replace("{{title}}", title)
                    .replace("{{date}}", date.today().isoformat()))
            f.write_text(text, encoding="utf-8")
    r = subprocess.call([sys.executable, str(SKILLS / "dwh-init" / "scripts" / "install.py"),
                         "--project", str(dest), "--shared-kernel", str(FRAMEWORK), "--layout", "v2",
                         "--name", title])
    if r != 0:
        print("the installer reported a problem (see above); the folder was created")
        return r
    print(f"\ncreated pipelines/{args.name}/ — next:\n"
          f"  1. describe the request in pipelines/{args.name}/requirements/request.md\n"
          f"  2. put the source files in pipelines/{args.name}/data/raw/ (never committed)\n"
          f"  3. ask Claude to set up the warehouse for pipelines/{args.name} (dwh-init writes the workbook)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
