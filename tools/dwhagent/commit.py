#!/usr/bin/env python3
"""Local commit of one pipeline, for the dwh agent: python ../../tools/dwhagent/commit.py <pipeline> -m "<message>"

* never on main/master: a branch dwh/<pipeline>/<yyyymmdd-hhmm> is created first;
* stages pipelines/<pipeline>/ only (what .gitignore keeps out stays out);
* refuses if the guard (no data, .dwh, salt, secrets, >5 MB) or the folder contract fails;
* commits with a "Prepared-by: dwh-agent" trailer. It never pushes: that is the person's call.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def git(*a: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(a)} failed: {r.stderr.strip()[:400]}")
    return r


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 3 or args[1] != "-m" or not args[2].strip():
        print(__doc__)
        return 2
    name, message = args[0], args[2].strip()
    rel = f"pipelines/{name}"
    if not (REPO / rel / "dwh-project.yaml").exists():
        print(f"no pipeline {name}")
        return 2
    branch = git("branch", "--show-current").stdout.strip()
    if branch in ("main", "master", ""):
        branch = f"dwh/{name}/{datetime.now().strftime('%Y%m%d-%H%M')}"
        git("switch", "-c", branch)
        print(f"created branch {branch} (never committing to main)")
    already = [f for f in git("diff", "--cached", "--name-only", "-z").stdout.split("\0") if f]
    outside = [f for f in already if not f.startswith(rel + "/")]
    if outside:
        print(f"refused: {len(outside)} file(s) outside {rel}/ are already staged ({', '.join(outside[:5])}). "
              "Commit or unstage them yourself first; this helper commits one pipeline only.")
        return 1
    git("add", "-A", "--", rel)
    staged = [f for f in git("diff", "--cached", "--name-only", "-z").stdout.split("\0") if f]
    if not staged:
        print("nothing to commit")
        return 0
    checks = [[sys.executable, str(REPO / "tools" / "guard_commit.py"), *staged],
              [sys.executable, str(REPO / "tools" / "check_layout.py"), name]]
    for c in checks:
        r = subprocess.run(c, cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            git("reset", "-q", "--", rel)
            print(f"refused, nothing committed:\n{(r.stdout + r.stderr).strip()[-1500:]}")
            return 1
    body = f"{message}\n\nPrepared-by: dwh-agent (Claude), reviewed and committed locally; not pushed\n"
    git("commit", "-q", "-m", body)
    sha = git("rev-parse", "--short", "HEAD").stdout.strip()
    print(f"committed {len(staged)} file(s) on {branch} as {sha}. Not pushed: review it, then `git push -u origin {branch}`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
