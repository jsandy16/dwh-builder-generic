"""Windows: the agent's command tool needs Git Bash.

On Windows, Claude Code offers its Bash tool only when it finds Git Bash's bash.exe; otherwise it
falls back to a PowerShell tool, which the dwh agent does not allow (its rules are written for one
plain bash command per call). Without either the agent can read and write files but run nothing.

find_git_bash() looks where Git for Windows installs bash.exe and returns the first that exists;
the agent then sets CLAUDE_CODE_GIT_BASH_PATH so the CLI uses it.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ENV = "CLAUDE_CODE_GIT_BASH_PATH"

HELP = """\
The agent needs Git Bash on Windows to run commands, and none was found.
  1. Install Git for Windows (https://git-scm.com/download/win), or find your bash.exe:
       in Git Bash, `cygpath -w /` prints the Git folder; bash.exe is in its bin folder
  2. Tell the agent where it is (Git Bash):
       export CLAUDE_CODE_GIT_BASH_PATH='C:\\Program Files\\Git\\bin\\bash.exe'
     (PowerShell: $env:CLAUDE_CODE_GIT_BASH_PATH="C:\\Program Files\\Git\\bin\\bash.exe")
     To keep it, add the export line to .venv/Scripts/activate.
  3. Run the agent again."""


def candidates(env: dict | None = None, which=shutil.which) -> list[Path]:
    env = os.environ if env is None else env
    out: list[Path] = []
    if env.get(ENV):
        out.append(Path(env[ENV]))
    git = which("git")
    if git:
        # ...\Git\cmd\git.exe or ...\Git\bin\git.exe or ...\Git\mingw64\bin\git.exe -> ...\Git\bin\bash.exe
        p = Path(git).resolve()
        for up in (p.parent.parent, p.parent.parent.parent):
            out.append(up / "bin" / "bash.exe")
    for base in (env.get("ProgramFiles"), env.get("ProgramW6432"), env.get("ProgramFiles(x86)"),
                 str(Path(env["LOCALAPPDATA"]) / "Programs") if env.get("LOCALAPPDATA") else None,
                 str(Path(env["USERPROFILE"]) / "scoop" / "apps" / "git" / "current") if env.get("USERPROFILE") else None):
        if base:
            root = Path(base)
            out.append(root / "bin" / "bash.exe" if root.name == "current" else root / "Git" / "bin" / "bash.exe")
    seen, uniq = set(), []
    for c in out:
        k = str(c).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def find_git_bash(env: dict | None = None, which=shutil.which, exists=lambda p: p.is_file()) -> Path | None:
    for c in candidates(env, which):
        if exists(c):
            return c
    return None
