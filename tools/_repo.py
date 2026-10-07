"""Shared helpers for the repository tools (standard library + PyYAML only)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FRAMEWORK = REPO / "framework"
KERNEL = FRAMEWORK / "dwh_core"
SKILLS = REPO / "skills"
PIPELINES = REPO / "pipelines"
TEMPLATE = REPO / "templates" / "pipeline"
NAME_RX = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


def kernel_version() -> str:
    text = (KERNEL / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^VERSION = "([^"]+)"', text, re.M).group(1)


def key_algo() -> str:
    text = (KERNEL / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^KEY_ALGO = "([^"]+)"', text, re.M).group(1)


def pipelines() -> list[Path]:
    """Every pipeline folder: a direct child of pipelines/ holding dwh-project.yaml."""
    return sorted(p.parent for p in PIPELINES.glob("*/dwh-project.yaml"))


def manifest(pipeline: Path) -> dict:
    import yaml
    data = yaml.load((pipeline / "dwh-project.yaml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader) or {}
    return data.get("project", {}) if isinstance(data, dict) else {}


def dwh(pipeline: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run the kernel for one pipeline without the machine-specific wrapper."""
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(FRAMEWORK), "DWH_PROJECT": str(pipeline), "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    r = subprocess.run([sys.executable, "-m", "dwh_core", *args], cwd=pipeline, env=env,
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"`dwh {' '.join(args)}` failed in {pipeline.name}:\n{r.stdout}{r.stderr}")
    return r


def git_tracked(path: Path) -> list[str]:
    """Files git tracks (or has staged) under path. A git failure is an error, never 'nothing tracked'."""
    r = subprocess.run(["git", "ls-files", "-z", "--", str(path)], cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git ls-files failed ({r.stderr.strip()[:300]}); the tracked-file checks cannot run")
    return [f for f in r.stdout.split("\0") if f]
