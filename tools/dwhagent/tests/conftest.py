"""A throw-away copy of the repository with one fresh pipeline, for the state and wiring tests."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))


@pytest.fixture(scope="session")
def scratch_repo(tmp_path_factory) -> Path:
    """framework/, skills/, templates/, tools/ and the plugin manifest, plus pipelines/demo (git initialised)."""
    root = tmp_path_factory.mktemp("repo")
    keep = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache")
    for d in ("framework", "skills", "templates", "tools", ".claude-plugin"):
        shutil.copytree(REPO / d, root / d, ignore=keep)
    (root / "pipelines").mkdir()
    for f in (".gitignore",):
        if (REPO / f).exists():
            shutil.copy2(REPO / f, root / f)
    run = lambda *a: subprocess.run(a, cwd=root, capture_output=True, text=True)  # noqa: E731
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Test")
    r = run(sys.executable, "tools/new_pipeline.py", "demo")
    assert r.returncode == 0, r.stdout + r.stderr
    r = run(sys.executable, "tools/doctor.py", "demo")
    assert (root / "pipelines" / "demo" / "dwh").exists(), r.stdout + r.stderr
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "start")
    return root
