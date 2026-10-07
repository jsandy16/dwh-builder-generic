#!/usr/bin/env python3
"""Run the end-to-end validation suite: python tools/run_validation.py [--layout v1|v2|both]

Packages the skills exactly as they ship (tools/package_skills.py), then runs validation/validate.py
against them with the scratch projects in a temporary folder OUTSIDE the repository (inside it,
the installer would detect the repository and switch to the shared kernel). Writes
validation/REPORT.md (v1) and validation/REPORT-layout-v2.md (v2). About 10 minutes per layout.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from _repo import REPO
from package_skills import build


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layout", default="both", choices=["v1", "v2", "both"])
    args = ap.parse_args()
    layouts = ["v1", "v2"] if args.layout == "both" else [args.layout]
    with tempfile.TemporaryDirectory(prefix="dwh-validation-") as tmp:
        tmp = Path(tmp)
        build(tmp / "dist")
        rc = 0
        for lay in layouts:
            env = dict(os.environ)
            env.update({"DWH_SKILLS": str(tmp / "dist" / "skills"), "DWH_RUNS": str(tmp / f"runs-{lay}"),
                        "DWH_TMP_DIR": str(tmp / f"tmp-{lay}"), "DWH_TEST_LAYOUT": lay, "PYTHONUTF8": "1"})
            (tmp / f"tmp-{lay}").mkdir()
            print(f"== validation suite, layout {lay}", flush=True)
            rc |= subprocess.call([sys.executable, str(REPO / "validation" / "validate.py")], env=env)
    return rc


if __name__ == "__main__":
    sys.exit(main())
