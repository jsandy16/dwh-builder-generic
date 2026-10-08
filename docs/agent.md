# The dwh agent (Claude in your terminal)

`python tools/dwh_agent.py <pipeline>` starts Claude in your terminal, working on one pipeline,
`pipelines/<pipeline>/`. It does the work Claude does in a chat, but from the repository: it reads
the request, drafts every answer, writes the intake workbook, runs the builds, explains what
happened and makes a local commit. It works for any kind of data. It knows the business only from
`requirements/`, the supplier's documents and the counts the engine measures.

**Its role: it drafts and runs; people decide; the engine judges.** The agent stops whenever a
decision belongs to a person.

## Before the first run

| Step | Command |
|---|---|
| Install the framework and the agent | `pip install -r framework/requirements.txt -r tools/dwhagent/requirements.txt` |
| An Anthropic API key (from console.anthropic.com) | `export ANTHROPIC_API_KEY=…` (Windows: `set ANTHROPIC_API_KEY=…`) |
| The pipeline folder | `python tools/new_pipeline.py sales` |
| The `./dwh` command on this computer | `python tools/doctor.py sales` |
| The request | write it in `pipelines/sales/requirements/request.md` and add the supplier's notes next to it |
| The data | put the files in `pipelines/sales/data/raw/`, then `python tools/data_manifest.py sales` |

**On Windows, the agent needs Git for Windows (Git Bash).** Claude Code offers its command tool only when it finds Git Bash's `bash.exe`; without it the agent could read files but run nothing. The agent looks in the usual places (next to `git`, Program Files, your user folder) and stops with instructions if it finds none. If yours is elsewhere, set `export CLAUDE_CODE_GIT_BASH_PATH='C:\Program Files\Git\bin\bash.exe'` (the path to your `bash.exe`), e.g. at the end of `.venv/Scripts/activate`.

The agent uses the API, so each session costs money. The default cap is $5 a session
(`--max-budget-usd`). A claude.ai subscription does not cover it.

## Running it

```bash
python tools/dwh_agent.py sales --check   # where the pipeline stands and what the agent would do (no AI, free)
python tools/dwh_agent.py sales           # start working
python tools/dwh_agent.py sales --ask "why were 72 sales rows set aside in March?"
```

Options: `--model` (a Claude model id), `--max-turns` (default 80 per step) and `--max-budget-usd`
(default 5).

In the session, `you>` waits for you:

- **Enter** goes on to the next stage.
- **Typing a request** asks the agent something or tells it to change something.
- **`/status`** prints `./dwh status`.
- **`/exit`** stops.

Whenever the agent wants to do something that needs your yes (a commit, an import, running a
check script), it asks `[y/N]`. Anything other than `y` means no.

## What it does at each stage

The agent works out the stage from the files. It does not remember it from last time.

| Stage | What the agent does | Then who acts |
|---|---|---|
| setup | nothing: it lists what is missing (request, data) | **you** add them |
| draft | reads the request and the supplier's notes; `./dwh intake analyze` (counts only); writes `intake/draft.yaml` with a reason for each proposal; generates the workbook and repeats until the defaults check is clean; asks the reviewer subagent to check the draft | **owners** answer the workbook |
| await | asks you: "Have the owners finished answering …?" | you say yes, or come back later |
| import | `./dwh intake import`; if the import is refused, explains every problem in the `-issues.xlsx` file | owners fix the workbook if needed |
| rework | explains what blocks a layer, changes its draft if the draft was the cause, and regenerates the workbook | owners |
| bronze | `./dwh build bronze`; explains the files and rows landed and the files rejected | — |
| after load | prepares the after-first-load questions; explains each rule read-back with its row count | **owners** answer the "After first load" tab |
| build | `./dwh build silver`, `build gold`, `publish` (local), `serve --check`; summarises the result; local commit (asks you first) | **you**: review, push, approve, release |
| operate | built and published: answers questions, adds new batches, takes change requests through the draft and workbook | — |

When a build fails, the agent finds the cause with counts. It can use
`tools/dwhagent/probe.py … what-if` to test a fix on a temporary copy. It then proposes the fix in
its draft, regenerates the workbook and stops. **It never weakens a check to get a build to pass.**

## What it may do

- **Run** `./dwh` commands: status, doctor, profile, generate, synth, layout show, intake
  analyze/check/show/readback/export/workbook, build bronze/silver/gold, publish (local only) and
  serve --check. It may run `intake import` only once you have said the workbook is answered.
- **Run** the repo tools for its own pipeline: `data_manifest`, `check_layout`, `check_pipelines`
  and `doctor`.
- **Run** `tools/dwhagent/probe.py` (counts only): `tables`, `dead-letters`, and `what-if`, which
  works on a temporary copy.
- **Run** read-only git commands (`status`, `diff`, `log`, `show`, `branch`), plus `ls`, `wc` and
  `pwd`.
- **Read** the pipeline's specs, decisions, reports, read-backs, requirements and workbooks.
- **Write** only these files: `intake/draft.yaml`, `README.md`, `gold/checks/*`, `governance/adr/*`
  and its notes file `.dwh/agent/notes.md`.
- **Ask** the `reviewer` subagent, which can only read, to check a draft or a fix before you see it.
- **Commit** locally with `tools/dwhagent/commit.py`, after you say yes. On `main` it first creates
  a branch `dwh/<pipeline>/<date-time>`. It commits only this pipeline's folder, and runs the same
  checks as the pre-commit hook.

## What it must never do (refused by the code, not just by the instructions)

| Never | Why |
|---|---|
| record an answer, or change a workbook, or confirm a rule read-back, or type golden values | answers come only from the owners, through the workbook |
| `./dwh approve`, `publish --target consumers`, `reset`, `layout migrate`, `intake set/confirm/infer/pending` | approving, releasing and destructive actions are people's decisions |
| read `data/raw/` or `.dwh/` (the warehouse, landed files, dead letters, salt) | the agent sees counts, never data values |
| edit specs, decisions, provenance, generated code or the kernel pin | those come only from `intake import` and `generate` |
| read or change another pipeline; change `framework/`, `skills/`, `tools/` or `docs/` (it may read them); read `.git/` | one pipeline per session; the framework changes only through review |
| `git push`, `reset`, `checkout`, `merge`, `rebase`; commit on `main` | you review and push |
| pipes, `;`, `&&`, redirections, `$(…)`, environment-variable prefixes, `cd`, `python -c` | one plain command per call, so every call can be checked |
| use the web, MCP servers, the browser or scheduling | only the tools listed above are offered at all |

Every refusal is printed (`✗ refused: …`) and logged, and the agent is told not to retry in
another form.

## How the rules are enforced

1. **Only a few tools are offered:** Bash, Read, Write, Edit, Glob, Grep, Skill and the reviewer
   subagent. Web tools, MCP servers, the browser integration and personal Claude settings are
   switched off (`setting_sources=[]`, `--strict-mcp-config`, `--no-chrome`).
2. **Every call goes through a rule check.** A hook calls `tools/dwhagent/policy.py` before every
   tool call, the reviewer's included. A refusal there is final.
3. **You are asked about the risky calls.** Anything the policy marks "ask" goes to you as `[y/N]`.
4. **The engine still checks everything.** Gates, provenance, read-backs, golden values and
   approvals work exactly as they do without the agent.

The rules are tested call by call (`tools/dwhagent/tests/test_policy.py`). They are also tested
end to end through the real Claude Code CLI, with a scripted stand-in for the model
(`test_wiring.py`), so no API key is needed in CI.

## Logs and memory

- `pipelines/<p>/.dwh/agent/sessions/<date-time>.jsonl` records every tool call, every decision
  (allowed, asked or refused), your answers, the agent's text and the cost.
- `pipelines/<p>/.dwh/agent/notes.md` holds the agent's short notes between sessions. You can read
  or edit them.
- Both are in `.dwh/`, so they are never committed.

## Limits and caveats

- **What leaves your computer.** The agent sends Anthropic's API what it reads: the request, the
  supplier's notes, specs, reports (counts) and command output. It never sends raw data or the
  warehouse. If your requirements documents are confidential, treat the session like sharing them
  with Claude in a chat.
- **Counts only depends on the policies.** The "no data values" promise assumes the pipeline's
  governance egress is `stats_only`, which is the default. If an owner allows samples, the engine's
  reports may contain values, and the agent will read them.
- **Git history is repository-wide.** `git log -p` shows committed changes in every folder. Raw
  data and `.dwh/` are never committed, so this exposes no data values. File paths given to git
  must be inside the pipeline, and `<revision>:<path>` reads are refused.
- **A check script is a script.** A script the agent writes in `gold/checks/` reads the raw files
  when you run it. Read it before you say yes. It should print only totals.
- **The model can be wrong.** Its drafts are proposals. The owners' answers, the reviewer and the
  engine's checks are what make the warehouse right.
- **Not yet run against the real model in this repository's CI.** The wiring test uses a scripted
  stand-in. The first real sessions should be watched.
- **Interactive only.** There is no unattended mode, by design.
