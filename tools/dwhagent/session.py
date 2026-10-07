"""The terminal session: Claude Agent SDK + the rules in policy.py + the stages in state.py.

Two locks on every tool call:
  1. a PreToolUse hook (runs first, for the agent and its reviewer subagent): policy.decide();
     a deny there is final in every permission mode;
  2. can_use_tool: anything the policy marks "ask" is put to the person at the terminal (y/N).
Settings files are not loaded (setting_sources=[]): personal Claude settings cannot loosen the rules.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from . import policy as P
from . import prompts
from . import state as S

GREY, RED, GREEN, BOLD, RESET = "\033[90m", "\033[31m", "\033[32m", "\033[1m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GREY = RED = GREEN = BOLD = RESET = ""


class Log:
    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"

    def write(self, kind: str, **data):
        rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, **data}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")


def _say(text: str, prefix: str = "") -> None:
    width = min(shutil.get_terminal_size((100, 20)).columns, 110)
    for para in text.strip().split("\n"):
        if not para.strip():
            print()
            continue
        lead = para[: len(para) - len(para.lstrip())]
        print(textwrap.fill(para.strip(), width=width, initial_indent=prefix + lead,
                            subsequent_indent=prefix + lead + ("   " if para.lstrip()[:2] in ("- ", "* ") else "")))


def _short(block) -> str:
    i = block.input or {}
    if block.name == "Bash":
        return i.get("command", "")
    if block.name in ("Read", "Write", "Edit", "MultiEdit"):
        return f"{block.name.lower()} {i.get('file_path', '')}"
    if block.name in ("Glob", "Grep"):
        return f"{block.name.lower()} {i.get('pattern', '')} {i.get('path', '')}".strip()
    if block.name in ("Agent", "Task"):
        return f"asks the {i.get('subagent_type', '?')} subagent"
    if block.name == "Skill":
        return f"reads skill {i.get('skill', i.get('command', ''))}"
    return block.name


async def _ask_person(question: str) -> bool:
    print(f"\n{BOLD}? {question}{RESET}")
    ans = await asyncio.to_thread(input, "  [y/N] ")
    return ans.strip().lower() in ("y", "yes")


# The only tools the model is given. policy.py still decides every single call.
BASE_TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill", "Agent", "TodoWrite")


def build_options(ctx: P.Context, log: Log, model: str | None, max_turns: int, max_budget: float | None):
    from claude_agent_sdk import (AgentDefinition, ClaudeAgentOptions, HookMatcher, PermissionResultAllow,
                                  PermissionResultDeny)

    async def policy_hook(input_data, tool_use_id, context):
        tool = input_data.get("tool_name", "")
        d = P.decide(ctx, tool, input_data.get("tool_input") or {})
        log.write("decision", tool=tool, input=input_data.get("tool_input"), decision=d.kind, reason=d.reason,
                  agent=input_data.get("agent_type"))
        if d.kind == P.DENY:
            print(f"{RED}    ✗ refused: {d.reason}{RESET}")
        out = {"hookEventName": "PreToolUse", "permissionDecision": d.kind}
        if d.reason:
            out["permissionDecisionReason"] = d.reason
        return {"hookSpecificOutput": out}

    async def can_use_tool(tool, tool_input, context):
        d = P.decide(ctx, tool, tool_input or {})
        if d.kind == P.ALLOW:
            return PermissionResultAllow(updated_input=tool_input)
        if d.kind == P.ASK and await _ask_person(d.reason):
            log.write("person", tool=tool, input=tool_input, answer="yes")
            return PermissionResultAllow(updated_input=tool_input)
        log.write("person", tool=tool, input=tool_input, answer="no" if d.kind == P.ASK else "denied")
        return PermissionResultDeny(message=d.reason if d.kind == P.DENY else
                                    "The person said no. Do not retry; ask them what they want instead.")

    notes_file = ctx.pipeline / ".dwh" / "agent" / "notes.md"
    notes = notes_file.read_text(encoding="utf-8")[-4000:] if notes_file.exists() else ""
    person = _person(ctx)
    path_env = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    return ClaudeAgentOptions(
        system_prompt=prompts.system_prompt(ctx.name, str(ctx.repo), person, notes),
        cwd=str(ctx.pipeline),
        setting_sources=[],
        plugins=[{"type": "local", "path": str(ctx.repo)}],
        agents={"reviewer": AgentDefinition(
            description="Read-only reviewer: checks the dwh agent's draft or proposed fix before a person sees it.",
            prompt=prompts.REVIEWER, tools=["Read", "Grep", "Glob"], maxTurns=20)},
        hooks={"PreToolUse": [HookMatcher(hooks=[policy_hook])]},
        can_use_tool=can_use_tool,
        permission_mode="default",
        tools=list(BASE_TOOLS),  # nothing else is even offered to the model (no web, no MCP, no scheduling)
        strict_mcp_config=True, mcp_servers={},  # ignore every MCP server configured on this computer
        disallowed_tools=["WebFetch", "WebSearch", "NotebookEdit"],
        forward_subagent_text=True,
        extra_args={"no-chrome": None},  # never the browser integration, even if this computer has it
        max_turns=max_turns,
        max_budget_usd=max_budget,
        model=model,
        env={"PATH": path_env, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _person(ctx: P.Context) -> str:
    try:
        sys.path.insert(0, str(ctx.repo / "framework"))
        from dwh_core.project import Project
        people = Project(ctx.pipeline).load_namespace("people") or {}
        for pid, rec in people.items():
            if isinstance(rec, dict) and rec.get("name"):
                return f"{rec['name']} ({pid})"
    except Exception:
        pass
    r = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, cwd=ctx.repo)
    return r.stdout.strip()


async def _stream(client, log: Log, totals: dict) -> None:
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            sub = bool(getattr(msg, "parent_tool_use_id", None))
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    log.write("text", text=block.text, subagent=sub)
                    if sub:
                        _say(block.text, prefix=f"{GREY}  [reviewer] ")
                        print(RESET, end="")
                    else:
                        print()
                        _say(block.text)
                elif isinstance(block, ToolUseBlock):
                    log.write("tool", name=block.name, input=block.input, subagent=sub)
                    print(f"{GREY}  {'[reviewer] ' if sub else ''}› {_short(block)}{RESET}")
        elif isinstance(msg, ResultMessage):
            totals["cost"] += msg.total_cost_usd or 0.0
            totals["turns"] += msg.num_turns or 0
            log.write("result", subtype=msg.subtype, cost=msg.total_cost_usd, turns=msg.num_turns,
                      is_error=msg.is_error, session=msg.session_id)
            if msg.is_error:
                print(f"{RED}  (stopped: {msg.subtype}{' — ' + '; '.join(msg.errors) if getattr(msg, 'errors', None) else ''}){RESET}")


STAGE_TEXT = {
    S.SETUP: "waiting for you: the request and the data",
    S.DRAFT: "draft every answer and write the intake workbook",
    S.AWAIT_ANSWERS: "waiting for the owners to answer the workbook",
    S.IMPORT: "import the answered workbook",
    S.REWORK: "explain what is missing and regenerate the workbook",
    S.BRONZE: "load bronze (and prepare the after-first-load questions)",
    S.AFTER_LOAD: "prepare the after-first-load questions",
    S.BUILD: "build silver, gold, publish, check the dashboard, commit locally",
    S.OPERATE: "built and published: help with what you need",
}


async def run(repo: Path, name: str, model: str | None, max_turns: int, max_budget: float | None,
              first_request: str | None = None) -> int:
    from claude_agent_sdk import ClaudeSDKClient
    pipeline = repo / "pipelines" / name
    ctx = P.Context(repo=repo, pipeline=pipeline,
                    python_names=("python", "python3", Path(sys.executable).name))
    log = Log(pipeline / ".dwh" / "agent" / "sessions")
    totals = {"cost": 0.0, "turns": 0}
    log.write("start", pipeline=name, model=model)
    print(f"{BOLD}dwh agent · pipelines/{name}{RESET}  {GREY}(log: {log.path.relative_to(repo)}){RESET}")
    async with ClaudeSDKClient(options=build_options(ctx, log, model, max_turns, max_budget)) as client:
        if first_request:
            await client.query(first_request)
            await _stream(client, log, totals)
        while True:
            st = S.detect(repo, pipeline)
            log.write("stage", stage=st.stage, why=st.why, facts=st.facts)
            print(f"\n{BOLD}── stage: {st.stage} — {STAGE_TEXT[st.stage]}{RESET}  {GREY}({st.why}){RESET}")
            if st.stage == S.SETUP:
                missing = [f"  - {m}" for m, ok in (("requirements/request.md: what is asked, by whom, which data",
                                                     st.facts.get("request_written")),
                                                    ("data/raw/: the source files, then "
                                                     f"`python tools/data_manifest.py {name}`",
                                                     st.facts.get("raw_files"))) if not ok]
                print(prompts.SETUP_HELP.format(name=name, missing="\n".join(missing)))
                break
            if st.stage == S.AWAIT_ANSWERS:
                rel = st.workbook.relative_to(pipeline).as_posix()
                if not await _ask_person(f"Have the owners finished answering {rel} (saved in place)?"):
                    print("Stopping here. Run the agent again when the workbook is answered.")
                    break
                ctx.import_preapproved.add(str(st.workbook.resolve()))
                st = S.State(S.IMPORT, "the person confirmed the workbook is answered", st.workbook, st.facts)
            await client.query(prompts.task(st, name))
            await _stream(client, log, totals)
            nxt = S.detect(repo, pipeline)
            while True:
                hint = (f"Enter = continue ({STAGE_TEXT[nxt.stage]})" if nxt.stage not in (S.SETUP,)
                        else "Enter = check again")
                said = (await asyncio.to_thread(input, f"\n{BOLD}you>{RESET} {GREY}[{hint} · a request · /status · "
                                                       f"/exit]{RESET} ")).strip()
                if said in ("/exit", "/quit", "exit", "quit"):
                    print(f"{GREY}cost this session: ${totals['cost']:.2f} · turns: {totals['turns']}{RESET}")
                    log.write("end", **totals)
                    return 0
                if said == "/status":
                    subprocess.run([sys.executable, "-m", "dwh_core", "status"], cwd=pipeline,
                                   env={**os.environ, "PYTHONPATH": str(repo / "framework")})
                    continue
                if not said:
                    break
                log.write("request", text=said)
                await client.query(said)
                await _stream(client, log, totals)
                nxt = S.detect(repo, pipeline)
            if nxt.stage == st.stage and st.stage not in (S.OPERATE,) and nxt.stage not in S.PERSON_STAGES:
                print(f"{GREY}(still at {nxt.stage}: {nxt.why}){RESET}")
    print(f"{GREY}cost this session: ${totals['cost']:.2f} · turns: {totals['turns']}{RESET}")
    log.write("end", **totals)
    return 0
