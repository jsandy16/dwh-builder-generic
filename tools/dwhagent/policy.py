"""What the dwh agent may do: every tool call is decided here, before it runs.

The decision is one of:
  allow — runs without asking;
  ask   — the person at the terminal is asked (y/N) first;
  deny  — refused, with a reason the agent sees (so it does not retry).

The rules (docs/agent.md has the reasoning):
  * one pipeline per session: nothing outside pipelines/<name>/ is written, other pipelines are
    not even read;
  * answers come only from the intake workbook: `dwh intake set/pending/confirm/infer` are refused;
  * people approve and release: `dwh approve`, `publish --target consumers`, `reset`,
    `layout migrate` are refused;
  * the agent never sees data values: data/raw/ and .dwh/ (warehouse, dead letters, snapshots) are
    not readable; the warehouse is reached only through `dwh` commands and the counts-only probe;
  * the engine owns specs, provenance and generated code: the agent writes only its draft, its
    golden-value check scripts, decision notes and its own notes;
  * Git: read-only commands, plus a local commit through tools/dwhagent/commit.py (asked first);
    never push;
  * the shell is an allowlist: one command per call, no pipes, redirections or substitutions.
This module is pure (no SDK, no I/O besides path resolution) so it can be tested exhaustively.
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

ALLOW, ASK, DENY = "allow", "ask", "deny"


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.kind == ALLOW


@dataclass
class Context:
    repo: Path
    pipeline: Path                      # pipelines/<name>, absolute
    python_names: tuple = ("python", "python3")
    import_preapproved: set = field(default_factory=set)   # workbook paths the person already confirmed

    def __post_init__(self):
        self.repo = Path(self.repo).resolve()
        self.pipeline = Path(self.pipeline).resolve()

    @property
    def name(self) -> str:
        return self.pipeline.name


def allow(reason: str = "") -> Decision:
    return Decision(ALLOW, reason)


def ask(reason: str) -> Decision:
    return Decision(ASK, reason)


def deny(reason: str) -> Decision:
    return Decision(DENY, reason)


# ---------------------------------------------------------------- paths
def resolve(ctx: Context, path: str) -> Path:
    p = Path(os.path.expanduser(str(path)))
    if not p.is_absolute():
        p = ctx.pipeline / p
    return Path(os.path.realpath(p))


def _inside(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def _rel(ctx: Context, p: Path) -> str:
    return p.relative_to(ctx.pipeline).as_posix() if _inside(p, ctx.pipeline) else str(p)


# readable even though they sit in a protected folder
_READ_EXCEPTIONS = (".dwh/last_error.txt", ".dwh/agent/notes.md")
# where the agent may write (relative to the pipeline): its draft, its check scripts, notes
_WRITE_EXACT = ("intake/draft.yaml", "README.md", ".dwh/agent/notes.md")
_WRITE_PREFIXES = ("gold/checks/", "governance/adr/")


def read_decision(ctx: Context, path: str, names_only: bool = False) -> Decision:
    """Reading file contents (Read, Grep) or, with names_only, listing names (Glob, ls)."""
    p = resolve(ctx, path)
    if not _inside(p, ctx.repo):
        return deny(f"{path}: outside the repository")
    if _inside(p, ctx.repo / ".git"):
        return deny("the .git folder is not for reading")
    pipelines = ctx.repo / "pipelines"
    if _inside(p, pipelines) and not _inside(p, ctx.pipeline) and p != pipelines:
        return deny(f"{path}: another pipeline; this session works on pipelines/{ctx.name} only")
    if _inside(p, ctx.pipeline) and not names_only:
        rel = _rel(ctx, p)
        if rel in _READ_EXCEPTIONS:
            return allow()
        if rel == "data/raw" or rel.startswith("data/raw/"):
            return deny("data/raw holds data values, which you may not see (governance egress). Use "
                        "`./dwh intake analyze` or the bronze profile: counts only.")
        if rel == ".dwh" or rel.startswith(".dwh/"):
            return deny(".dwh holds the warehouse, rejected rows and snapshots (data values). Use `./dwh` "
                        "commands, the reports, or `python ../../tools/dwhagent/probe.py` (counts only).")
    for part in ("/.venv/", "/venv/", "/node_modules/"):
        if part in p.as_posix() + "/":
            return deny(f"{path}: not part of the project")
    return allow()


def write_decision(ctx: Context, path: str) -> Decision:
    p = resolve(ctx, path)
    if not _inside(p, ctx.pipeline):
        return deny(f"{path}: you only write inside pipelines/{ctx.name}/")
    rel = _rel(ctx, p)
    if rel in _WRITE_EXACT or rel.startswith(_WRITE_PREFIXES):
        return allow()
    if rel.startswith(("bronze/specs/", "silver/specs/", "gold/specs/", "serve/specs/", "project/")) \
            or rel == "dwh-project.yaml" or "/decisions/" in f"/{rel}":
        return deny(f"{rel}: specs and decisions are written only by `./dwh intake import` from the "
                    "owner's workbook. Put your proposal in intake/draft.yaml and regenerate the workbook.")
    if "/generated/" in f"/{rel}":
        return deny(f"{rel}: generated code is rendered by the engine and never edited")
    if rel.startswith("requirements/"):
        return deny("requirements/ is the requester's input; you read it, you do not change it")
    if rel.startswith("governance/"):
        return deny("governance/ (approvals, releases) is written by the engine and by people")
    return deny(f"{rel}: you may write only intake/draft.yaml, gold/checks/, governance/adr/, README.md "
                "and .dwh/agent/notes.md")


# ---------------------------------------------------------------- shell
_FORBIDDEN = (";", "&", "|", ">", "<", "`", "$(", "${", "\n", "\r")


def bash_decision(ctx: Context, command: str) -> Decision:
    cmd = (command or "").strip()
    if not cmd:
        return deny("empty command")
    bad = [s for s in _FORBIDDEN if s in cmd]
    if bad:
        return deny("one plain command per call: no pipes, redirections, chaining or substitutions "
                    f"(found {' '.join(repr(b) for b in bad)})")
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        return deny(f"could not parse the command: {e}")
    if "=" in argv[0] and not argv[0].startswith(("./", "/")):
        return deny("no environment-variable prefixes")
    head = argv[0]
    base = Path(head).name
    if base in ("dwh", "dwh.cmd") and (head in ("dwh", "dwh.cmd") or resolve(ctx, head).parent == ctx.pipeline):
        return _dwh(ctx, argv[1:])
    if base in ctx.python_names or base.startswith("python3"):
        return _python(ctx, argv[1:])
    if head == "git":
        return _git(ctx, argv[1:])
    if head in ("ls", "wc", "pwd"):
        for a in argv[1:]:
            if a.startswith("--files0-from"):
                return deny("`wc --files0-from` reads a list of files; name the files instead")
            if not a.startswith("-"):
                d = read_decision(ctx, a, names_only=True)
                if not d.allowed:
                    return d
        return allow()
    if head == "cd":
        return deny("stay in the pipeline folder; give paths instead of changing directory")
    return deny(f"`{head}` is not on the allowlist. Allowed: ./dwh <command>, python ../../tools/<tool>.py, "
                "python gold/checks/<script>.py, git status|diff|log|branch|show, ls, wc, pwd. "
                "Read files with the Read tool.")


def _split_eq(args: list[str]) -> list[str]:
    """`--target=consumers` is read as `--target consumers`, so no rule can be dodged with `=`."""
    out = []
    for a in args:
        if a.startswith("--") and "=" in a:
            out += a.split("=", 1)
        else:
            out.append(a)
    return out


# Every long option the dwh CLI has. Anything else is refused: argparse accepts shortened options
# (`--targ` for `--target`), so an exact list is the only way the checks below see what will run.
_DWH_FLAGS = {"--gate", "--unattended", "--json", "--role", "--out", "--no-analysis", "--dry-run", "--batch",
              "--source", "--rebuild", "--target", "--check", "--released", "--no-write", "--verify", "--to",
              "--score", "--help"}


def _dwh(ctx: Context, args: list[str]) -> Decision:
    args = _split_eq(args)
    d = _dwh_command(ctx, args)
    if d.kind == DENY:
        return d
    for a in args:
        if a.startswith("--") and a not in _DWH_FLAGS:
            return deny(f"`{a}`: write dwh options in full (unknown or shortened options are refused)")
        if a.startswith("-") and not a.startswith("--") and a != "-h":
            return deny(f"`{a}`: dwh has no short options; write them in full")
    return d


def _dwh_command(ctx: Context, args: list[str]) -> Decision:
    if not args:
        return allow()
    sub, rest = args[0], args[1:]
    if sub in ("status", "doctor", "profile", "generate", "synth"):
        return allow()
    if sub == "approve":
        return deny("only a person approves, in their own terminal (`./dwh approve --by <id>`). Tell the user.")
    if sub == "reset":
        return deny("`dwh reset` deletes built data; only a person runs it")
    if sub == "layout":
        if rest[:1] == ["show"]:
            return allow()
        return deny("`dwh layout migrate` changes the project layout and the kernel pin: a person decides that")
    if sub == "build":
        if rest[:1] and rest[0] in ("bronze", "silver", "gold"):
            return allow()
        return deny("build what? bronze, silver or gold")
    if sub == "publish":
        if "--target" in rest:
            i = rest.index("--target")
            if rest[i + 1:i + 2] != ["local"]:
                return deny("releasing to consumers is a person's action (`./dwh publish --target consumers`)")
        return allow()
    if sub == "serve":
        if "--check" in rest and "--released" not in rest:
            return allow()
        return deny("the dashboard server keeps running; tell the user to start it in another terminal "
                    "(`./dwh serve`). You may run `./dwh serve --check`.")
    if sub == "intake":
        act = rest[0] if rest else ""
        if act == "analyze":
            folders = [a for a in rest[1:] if not a.startswith("-")]
            if folders and not _inside(resolve(ctx, folders[0]), ctx.pipeline):
                return deny("analyze a folder of this pipeline (data/raw)")
            return allow()
        if act in ("check", "show", "readback", "export"):
            return allow()
        if act == "workbook":
            if "--out" in rest:
                i = rest.index("--out")
                target = resolve(ctx, rest[i + 1]) if i + 1 < len(rest) else None
                if target is None or not _inside(target, ctx.pipeline / "intake"):
                    return deny("write workbooks inside intake/ (the default intake/current/ is best)")
            return allow()
        if act == "import":
            files = [a for a in rest[1:] if not a.startswith("-")]
            if not files:
                return deny("import which workbook?")
            wb = resolve(ctx, files[0])
            if not _inside(wb, ctx.pipeline):
                return deny("the workbook must be inside the pipeline folder; ask the user to save it in "
                            "intake/current/")
            if "--out" in rest:
                i = rest.index("--out")
                target = resolve(ctx, rest[i + 1]) if i + 1 < len(rest) else None
                if target is None or not _inside(target, ctx.pipeline / "intake"):
                    return deny("write the issues copy inside intake/ (the default is best)")
            if "--dry-run" in rest:
                return allow()
            if str(wb) in ctx.import_preapproved:
                return allow("the person confirmed the workbook is answered")
            return ask(f"Import {_rel(ctx, wb)}? Answer yes only when the owners have finished answering it.")
        if act in ("set", "pending", "confirm", "infer"):
            return deny("answers come only from the intake workbook (this pipeline's workbook-only rule). "
                        "Propose the change in intake/draft.yaml, regenerate the workbook and let the owner answer.")
        return deny(f"`dwh intake {act}` is not allowed")
    return deny(f"`dwh {sub}` is not allowed")


_TOOL_SCRIPTS = {"data_manifest.py", "check_layout.py", "check_pipelines.py", "doctor.py", "guard_commit.py"}


def _python(ctx: Context, args: list[str]) -> Decision:
    if not args or args[0].startswith("-"):
        return deny("run a script file (no `python -c`, `-m` or an interactive interpreter)")
    script = resolve(ctx, args[0])
    rest = args[1:]
    tools = ctx.repo / "tools"
    if script.parent == tools and script.name in _TOOL_SCRIPTS:
        if script.name == "guard_commit.py":
            for a in rest:
                if not _inside(resolve(ctx, a), ctx.pipeline):
                    return deny("guard_commit.py: only files of this pipeline")
            return allow()
        if [a for a in rest if not a.startswith("-")][:1] != [ctx.name]:
            return deny(f"{script.name}: run it for this pipeline only (`{ctx.name}`)")
        return allow()
    if script.parent == tools / "dwhagent" and script.name in ("probe.py", "commit.py"):
        if rest[:1] != [ctx.name]:
            return deny(f"{script.name}: first argument must be this pipeline (`{ctx.name}`)")
        if script.name == "commit.py":
            msg = rest[rest.index("-m") + 1] if "-m" in rest and rest.index("-m") + 1 < len(rest) else "(no message)"
            return ask(f"Commit pipelines/{ctx.name}/ locally (no push) with the message:\n    {msg}")
        return allow()
    if _inside(script, ctx.pipeline / "gold" / "checks") and script.suffix == ".py":
        return ask(f"Run {_rel(ctx, script)}? It reads the raw files on this computer; check that it prints "
                   "only totals, never rows.")
    return deny(f"{args[0]}: not an allowed script")


def _git(ctx: Context, args: list[str]) -> Decision:
    if not args:
        return deny("which git command?")
    sub = args[0]
    if sub in ("status", "diff", "log", "show"):
        if any(a in ("--output", "-o") or a.startswith("--output=") for a in args):
            return deny("no output files")
        risky = [a for a in args if a.split("=", 1)[0] in ("--ext-diff", "--textconv", "--exec", "--upload-pack",
                                                             "--open-files-in-pager")]
        if risky:
            return deny(f"`{risky[0]}` runs helper programs; plain git output only")
        if "--no-index" in args:
            return deny("`git diff --no-index` compares files outside git; use Read on this pipeline's files")
        after_dashes = False
        for a in args[1:]:
            if a == "--":
                after_dashes = True
                continue
            if a.startswith("-") and not after_dashes:
                continue
            if ":" in a and not after_dashes:
                return deny("`<revision>:<path>` reads a file from history; read this pipeline's files with Read")
            p = resolve(ctx, a)
            if (after_dashes or p.exists()) and not _inside(p, ctx.pipeline):
                return deny(f"{a}: git commands here look at pipelines/{ctx.name} only")
        return allow()
    if sub == "branch" and all(a in ("--show-current", "--list", "-a", "-v") for a in args[1:]):
        return allow()
    if sub in ("add", "commit"):
        return deny("commit through `python ../../tools/dwhagent/commit.py "
                    f"{ctx.name} -m \"<message>\"` (it stages this pipeline only and checks it first)")
    return deny(f"`git {sub}` is not allowed (never push, reset, checkout, merge or rebase)")


# ---------------------------------------------------------------- tools
READ_TOOLS = {"Read"}
NAME_TOOLS = {"Glob"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}
FREE_TOOLS = {"TodoWrite", "Skill", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"}
REVIEWER = "reviewer"


def decide(ctx: Context, tool: str, tool_input: dict) -> Decision:
    tool_input = tool_input or {}
    if tool == "Bash":
        return bash_decision(ctx, tool_input.get("command", ""))
    if tool in READ_TOOLS:
        return read_decision(ctx, tool_input.get("file_path", ""))
    if tool in NAME_TOOLS:
        base = tool_input.get("path") or str(ctx.pipeline)
        d = read_decision(ctx, base, names_only=True)
        if not d.allowed:
            return d
        pattern = tool_input.get("pattern", "")
        if ".." in pattern.split("/"):
            return deny("no '..' in glob patterns")
        return allow()
    if tool == "Grep":
        if not tool_input.get("path"):
            return deny("give Grep an explicit path inside the pipeline (e.g. silver/specs) or the repo docs")
        p = resolve(ctx, tool_input["path"])
        if _inside(ctx.pipeline, p):      # the pipeline itself or a folder above it would search data/raw
            return deny("that path is too broad (it contains data/raw and .dwh); search a subfolder such as "
                        "silver/specs, intake or bronze/reports")
        return read_decision(ctx, tool_input["path"])
    if tool in WRITE_TOOLS:
        return write_decision(ctx, tool_input.get("file_path", ""))
    if tool in ("Agent", "Task"):
        if tool_input.get("subagent_type") == REVIEWER:
            return allow()
        return deny(f"only the '{REVIEWER}' subagent may be used")
    if tool in FREE_TOOLS:
        return allow()
    return deny(f"the {tool} tool is not available to this agent")
