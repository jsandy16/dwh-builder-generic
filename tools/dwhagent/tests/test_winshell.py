"""Finding Git Bash on Windows (pure path logic, runs on any OS)."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath

from dwhagent import winshell


def _find(env, git=None, present=()):
    present = {str(p).lower() for p in present}
    return winshell.find_git_bash(env, which=lambda _: git, exists=lambda p: str(p).lower() in present)


def test_explicit_setting_wins():
    p = Path("/opt/custom/bash.exe")
    assert _find({winshell.ENV: str(p)}, present=[p]) == p


def test_found_from_git_on_path():
    git = Path("/progs/Git/cmd/git.exe")
    bash = Path("/progs/Git/bin/bash.exe")
    assert _find({}, git=str(git), present=[bash.resolve()]) == bash.resolve()


def test_found_in_program_files():
    env = {"ProgramFiles": "/pf"}
    assert _find(env, present=[Path("/pf/Git/bin/bash.exe")]) == Path("/pf/Git/bin/bash.exe")


def test_found_in_user_install():
    env = {"LOCALAPPDATA": "/u/AppData/Local"}
    want = Path("/u/AppData/Local/Programs/Git/bin/bash.exe")
    assert _find(env, present=[want]) == want


def test_none_when_missing():
    assert _find({"ProgramFiles": "/pf"}) is None


def test_help_names_the_setting():
    assert winshell.ENV in winshell.HELP and "bash.exe" in winshell.HELP
    assert PureWindowsPath(r"C:\Program Files\Git\bin\bash.exe").name == "bash.exe"
