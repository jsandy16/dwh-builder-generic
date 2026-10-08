"""The real Claude Code CLI, driven by a scripted fake model: the rules hold end to end.

Checks that the PreToolUse hook and can_use_tool are actually wired: refused calls never run (for
the agent and for its reviewer subagent), allowed calls run, a question to the person is asked and
a "no" is respected, and only the base tools are offered. Needs `claude-agent-sdk`; skipped otherwise.
No API key and no network: the model is tools/dwhagent/tests/fake_model.py.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("claude_agent_sdk")

from dwhagent import policy as P  # noqa: E402
from dwhagent import session  # noqa: E402

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from fake_model import FakeModel  # noqa: E402

SCRIPT = [
    ("Bash", {"command": "./dwh approve --by demo", "description": "approve"}),
    ("Read", {"file_path": "data/raw/orders.csv"}),
    ("Bash", {"command": "cat data/raw/orders.csv", "description": "peek"}),
    ("Write", {"file_path": "silver/specs/entities/orders.yaml", "content": "x: 1\n"}),
    ("Bash", {"command": "git push origin HEAD", "description": "push"}),
    ("Bash", {"command": "./dwh layout show", "description": "layout"}),
    ("Write", {"file_path": "intake/draft.yaml", "content": "# proposals only\nanswers: {}\n"}),
    ("SUBAGENT", {"description": "review the draft", "prompt": "review intake/draft.yaml", "subagent_type": "reviewer"}),
    ("Bash", {"command": 'python ../../tools/dwhagent/commit.py demo -m "pipeline(demo): draft"',
              "description": "commit"}),
]
SUB_SCRIPT = [("Read", {"file_path": "data/raw/orders.csv"}), ("Read", {"file_path": "intake/draft.yaml"})]


@pytest.fixture()
def repo(scratch_repo, tmp_path):
    r = tmp_path / "repo"
    shutil.copytree(scratch_repo, r, symlinks=True)
    (r / "pipelines" / "demo" / "data" / "raw" / "orders.csv").write_text("id,amount\n1,10\n")
    return r


def test_rules_hold_through_the_real_cli(repo, monkeypatch, tmp_path):
    asked = []

    async def person_says_no(question):
        asked.append(question)
        return False

    monkeypatch.setattr(session, "_ask_person", person_says_no)
    pipeline = repo / "pipelines" / "demo"
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout
    with FakeModel(SCRIPT, SUB_SCRIPT) as fake:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", fake.url)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-key")
        monkeypatch.setenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))

        async def go():
            from claude_agent_sdk import ClaudeSDKClient
            ctx = P.Context(repo=repo, pipeline=pipeline, python_names=("python", "python3", sys.executable.split("/")[-1]))
            log = session.Log(pipeline / ".dwh" / "agent" / "sessions")
            async with ClaudeSDKClient(options=session.build_options(ctx, log, None, 30, None)) as client:
                await client.query("wiring test")
                await session._stream(client, log, {"cost": 0.0, "turns": 0})
        asyncio.run(asyncio.wait_for(go(), timeout=240))

        res = fake.tool_results()
        offered = fake.offered_tools()

    main = [r for r in res if not r[0]]
    sub = [r for r in res if r[0]]
    assert len(main) == len(SCRIPT), res
    approve, read_raw, cat_raw, write_spec, push, layout, write_draft, review, commit = main
    assert approve[1] and "only a person approves" in approve[2]
    assert read_raw[1] and "data values" in read_raw[2]
    assert cat_raw[1]
    assert write_spec[1] and "intake import" in write_spec[2]
    assert push[1] and "push" in push[2]
    assert not layout[1] and "layout" in layout[2].lower()
    assert not write_draft[1]
    assert (pipeline / "intake" / "draft.yaml").read_text().startswith("# proposals only")
    assert not (pipeline / "silver" / "specs" / "entities" / "orders.yaml").exists()
    assert "no problems found" in review[2]
    assert sub[0][1] and "data values" in sub[0][2], sub
    assert not sub[1][1]
    assert commit[1] and "said no" in commit[2] and asked and "Commit" in asked[0]
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout == head
    assert set(offered) <= set(session.BASE_TOOLS) | {"Task"}, offered


def test_no_shell_tool_stops_before_anything_runs(repo, monkeypatch, tmp_path):
    """On Windows without Git Bash the CLI offers no Bash tool: the session must stop at once."""
    pipeline = repo / "pipelines" / "demo"
    monkeypatch.setattr(session, "BASE_TOOLS", ("Read", "Write"))
    with FakeModel(SCRIPT) as fake:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", fake.url)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-key")
        monkeypatch.setenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))

        async def go():
            from claude_agent_sdk import ClaudeSDKClient
            ctx = P.Context(repo=repo, pipeline=pipeline, python_names=("python", "python3"))
            log = session.Log(pipeline / ".dwh" / "agent" / "sessions")
            async with ClaudeSDKClient(options=session.build_options(ctx, log, None, 30, None)) as client:
                await client.query("wiring test")
                await session._stream(client, log, {"cost": 0.0, "turns": 0})
        with pytest.raises(session.NoShell):
            asyncio.run(asyncio.wait_for(go(), timeout=240))
    assert not (pipeline / "intake" / "draft.yaml").exists()
