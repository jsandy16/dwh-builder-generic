# 0005 — A terminal agent, with its rules in code

**Status:** accepted · 2026-10-07

## Context

Until now the dwh skills ran in a Claude chat. Teams want the same work from the repository itself,
in a terminal, on any kind of data. An agent that can run commands needs firmer limits than
instructions in a prompt.

## Decision

- `tools/dwh_agent.py`, built on the Claude Agent SDK, lives in this repository and works on one
  pipeline per session.
- **Role:** it drafts and runs; people decide; the engine judges. It never approves, never releases,
  never records an answer, and never pushes.
- **Answers come only from the workbook.** Nothing the agent is told in the terminal counts as an
  owner's answer.
- **The shell is restricted to an allowlist** (`tools/dwhagent/policy.py`), not opened up and not
  replaced by typed tools. One plain command per call; `./dwh` subcommands, the repo tools and
  read-only git commands are allowed; everything else is refused. Every call, the reviewer
  subagent's included, goes through a PreToolUse hook. Personal settings, MCP servers, web tools and
  the browser integration are switched off.
- **Diagnostics are counts only:** `probe.py` (tables, dead letters, what-if on a temporary copy)
  replaces direct database access.
- **Git stops at a local commit** (`commit.py`): a branch when on `main`, this pipeline only, the
  guard and layout checks first, and the person says yes.
- **Interactive only.** The stage is worked out from the files each time.

## Consequences

- The person's role is unchanged: answer the workbook, approve, release, push.
- Adding a command for the agent means changing `policy.py` and its tests, which is a reviewed
  change.
- The model sees whatever the agent reads (requirements, specs, reports). Raw data and the warehouse
  stay closed to it.
- Running the agent needs an Anthropic API key and costs money per session, with a cap per session.
