"""The agent's rules, call by call. Every 'must never' in docs/agent.md has a test here."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dwhagent.policy import ALLOW, ASK, DENY, Context, decide  # noqa: E402


@pytest.fixture()
def ctx(tmp_path):
    repo = tmp_path / "repo"
    p = repo / "pipelines" / "sales"
    for d in ("data/raw/batch_01", ".dwh/dead_letter", "intake/current", "gold/checks", "silver/specs/entities",
              "silver/generated", "governance/adr", "requirements"):
        (p / d).mkdir(parents=True)
    (repo / "pipelines" / "olist").mkdir(parents=True)
    (repo / "tools" / "dwhagent").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / ".git").mkdir()
    return Context(repo=repo, pipeline=p)


def kind(ctx, tool, **inp):
    return decide(ctx, tool, inp).kind


@pytest.mark.parametrize("cmd", [
    "./dwh status", "./dwh doctor", "./dwh intake analyze data/raw", "./dwh intake workbook",
    "./dwh intake check all", "./dwh intake check silver --gate B --json", "./dwh intake readback sales",
    "./dwh intake import intake/current/sales-intake.xlsx --dry-run",
    "./dwh build bronze", "./dwh build silver --rebuild", "./dwh build gold", "./dwh publish",
    "./dwh publish --target local", "./dwh serve --check", "./dwh generate --verify", "./dwh layout show",
    "./dwh synth --score", "./dwh profile",
    "python ../../tools/data_manifest.py sales", "python ../../tools/data_manifest.py sales --check",
    "python3 ../../tools/check_layout.py sales", "python ../../tools/check_pipelines.py sales",
    "python ../../tools/dwhagent/probe.py sales dead-letters",
    "python ../../tools/guard_commit.py intake/draft.yaml",
    "git status", "git diff --stat", "git log --oneline -5", "git branch --show-current",
    "ls", "ls silver/specs", "ls data/raw", "wc -l data/raw/batch_01/orders.csv", "pwd",
])
def test_allowed_commands(ctx, cmd):
    assert kind(ctx, "Bash", command=cmd) == ALLOW, cmd


@pytest.mark.parametrize("cmd,why", [
    ("./dwh approve --by sandeep", "only a person approves"),
    ("./dwh publish --target consumers", "releasing to consumers"),
    ("./dwh reset --data --yes", "deletes built data"),
    ("./dwh layout migrate", "a person decides"),
    ("./dwh intake set silver.entities.x.readback_confirmed yes --by sandeep", "workbook"),
    ("./dwh intake pending policies.egress --owner gina", "workbook"),
    ("./dwh intake confirm sources.s.role --by dana", "workbook"),
    ("./dwh serve", "another terminal"),
    ("./dwh intake workbook --out /tmp/x.xlsx", "inside intake"),
    ("./dwh intake import /tmp/elsewhere.xlsx", "inside the pipeline"),
    ("cat data/raw/batch_01/orders.csv", "not on the allowlist"),
    ("head -5 data/raw/batch_01/orders.csv", "not on the allowlist"),
    ("./dwh status | head", "one plain command"),
    ("./dwh status; rm -rf data", "one plain command"),
    ("./dwh build bronze && ./dwh build silver", "one plain command"),
    ("echo $(cat x)", "one plain command"),
    ("./dwh status > out.txt", "one plain command"),
    ("python -c 'print(1)'", "script file"),
    ("python ../../tools/new_pipeline.py other", "not an allowed script"),
    ("python ../../tools/data_manifest.py olist", "this pipeline"),
    ("python ../../tools/dwhagent/probe.py olist tables", "first argument"),
    ("python ../../tools/guard_commit.py ../olist/README.md", "only files of this pipeline"),
    ("git push origin main", "not allowed"),
    ("git reset --hard", "not allowed"),
    ("git checkout main", "not allowed"),
    ("git commit -m x", "commit through"),
    ("git add -A", "commit through"),
    ("rm -rf .dwh", "not on the allowlist"),
    ("curl https://example.com", "not on the allowlist"),
    ("cd ../olist", "stay in the pipeline"),
    ("ls ../olist", "another pipeline"),
    ("FOO=1 ./dwh status", "environment"),
    ("duckdb .dwh/warehouse.duckdb", "not on the allowlist"),
])
def test_denied_commands(ctx, cmd, why):
    d = decide(ctx, "Bash", {"command": cmd})
    assert d.kind == DENY and why in d.reason, (cmd, d)


@pytest.mark.parametrize("cmd", [
    "./dwh intake import intake/current/sales-intake.xlsx",
    "python ../../tools/dwhagent/commit.py sales -m \"pipeline(sales): intake answers\"",
    "python gold/checks/golden_independent.py data/raw gold/checks/golden.csv",
])
def test_ask_first(ctx, cmd):
    assert kind(ctx, "Bash", command=cmd) == ASK, cmd


def test_import_preapproved_by_the_person(ctx):
    wb = ctx.pipeline / "intake/current/sales-intake.xlsx"
    ctx.import_preapproved.add(str(wb.resolve()))
    assert kind(ctx, "Bash", command="./dwh intake import intake/current/sales-intake.xlsx") == ALLOW


@pytest.mark.parametrize("path,expected", [
    ("requirements/request.md", ALLOW), ("silver/specs/entities/x.yaml", ALLOW), ("intake/analysis.json", ALLOW),
    ("../../docs/guide.md", ALLOW), ("../../skills/dwh-init/SKILL.md", ALLOW), (".dwh/last_error.txt", ALLOW),
    (".dwh/agent/notes.md", ALLOW),
    ("data/raw/batch_01/orders.csv", DENY), (".dwh/warehouse.duckdb", DENY), (".dwh/dead_letter/x.csv", DENY),
    ("../olist/README.md", DENY), ("../../.git/config", DENY), ("/etc/passwd", DENY),
])
def test_reads(ctx, path, expected):
    assert kind(ctx, "Read", file_path=path) == expected, path


@pytest.mark.parametrize("path,expected", [
    ("intake/draft.yaml", ALLOW), ("gold/checks/golden_independent.py", ALLOW), ("governance/adr/0001-x.md", ALLOW),
    ("README.md", ALLOW), (".dwh/agent/notes.md", ALLOW),
    ("silver/specs/entities/sales.yaml", DENY), ("silver/decisions/provenance.yaml", DENY),
    ("silver/generated/sales__merge.sql", DENY), ("dwh-project.yaml", DENY), ("project/people.yaml", DENY),
    ("requirements/request.md", DENY), ("governance/approvals.log", DENY), ("data/raw/x.csv", DENY),
    ("../olist/intake/draft.yaml", DENY), ("../../framework/dwh_core/silver.py", DENY), ("/tmp/x", DENY),
])
def test_writes(ctx, path, expected):
    for tool in ("Write", "Edit"):
        assert kind(ctx, tool, file_path=path) == expected, (tool, path)


def test_grep_and_glob(ctx):
    assert kind(ctx, "Grep", pattern="x") == DENY                      # no path: refused
    assert kind(ctx, "Grep", pattern="x", path=".") == DENY            # whole pipeline includes data/raw
    assert kind(ctx, "Grep", pattern="x", path="../..") == DENY
    assert kind(ctx, "Grep", pattern="x", path="data/raw") == DENY
    assert kind(ctx, "Grep", pattern="x", path="silver/specs") == ALLOW
    assert kind(ctx, "Glob", pattern="**/*.yaml") == ALLOW            # names only
    assert kind(ctx, "Glob", pattern="*", path="../olist") == DENY


def test_tools_and_subagents(ctx):
    assert kind(ctx, "Agent", subagent_type="reviewer", prompt="x") == ALLOW
    assert kind(ctx, "Agent", subagent_type="general-purpose", prompt="x") == DENY
    for t in ("WebFetch", "WebSearch", "NotebookEdit", "SomethingNew"):
        assert kind(ctx, t) == DENY
    assert kind(ctx, "TodoWrite", todos=[]) == ALLOW


def test_symlink_escape_is_caught(ctx):
    link = ctx.pipeline / "gold" / "checks" / "sneaky"
    link.symlink_to(ctx.pipeline / "data" / "raw")
    assert kind(ctx, "Read", file_path="gold/checks/sneaky/batch_01/orders.csv") == DENY
    assert kind(ctx, "Write", file_path="gold/checks/sneaky/x.csv") == DENY


# ---------------------------------------------------------------- found in review: dodges
@pytest.mark.parametrize("cmd,why", [
    ("./dwh publish --target=consumers", "person"),
    ("./dwh intake workbook --out=/tmp/w.xlsx", "inside intake"),
    ("./dwh intake import intake/current/w.xlsx --out /tmp/issues.xlsx", "inside intake"),
    ("./dwh intake analyze /etc", "this pipeline"),
    ("./dwh intake analyze ../olist/data/raw", "this pipeline"),
    ("git diff --no-index /etc/passwd /etc/hosts", "no-index"),
    ("git show HEAD:pipelines/olist/README.md", "history"),
    ("git show main:../../.env", "history"),
    ("git diff HEAD -- ../olist", "only"),
    ("git log -- ../../docs", "only"),
])
def test_dodges_are_refused(ctx, cmd, why):
    d = decide(ctx, "Bash", {"command": cmd})
    assert d.kind == DENY and why in d.reason, (cmd, d)


@pytest.mark.parametrize("cmd", [
    "git log --oneline -5", "git log --format=%h:%s -3", "git diff HEAD~1 -- intake", "git show --stat HEAD",
    "git diff -- intake/draft.yaml", "./dwh intake analyze data/raw", "./dwh publish --target=local",
])
def test_ordinary_git_and_dwh_still_allowed(ctx, cmd):
    assert kind(ctx, "Bash", command=cmd) == ALLOW, cmd


# ---------------------------------------------------------------- shortened options, helper programs
@pytest.mark.parametrize("cmd", [
    "./dwh publish --targ consumers", "./dwh publish --t consumers", "./dwh serve --rel --check",
    "./dwh intake workbook --o /tmp/w.xlsx", "./dwh intake import intake/current/w.xlsx --o /tmp/i.xlsx",
    "./dwh build silver -x", "git diff --ext-diff", "git log -p --textconv", "git diff --textconv=x",
    "wc --files0-from=data/raw/list.txt", "wc --files0-from /etc/hosts",
])
def test_shortened_options_and_helpers_are_refused(ctx, cmd):
    assert kind(ctx, "Bash", command=cmd) == DENY, cmd


def test_grep_on_one_raw_file_is_refused(ctx):
    assert kind(ctx, "Grep", pattern="x", path="data/raw/batch_01/orders.csv") == DENY


def test_write_through_a_symlink_in_an_allowed_folder_is_refused(ctx):
    link = ctx.pipeline / "gold" / "checks" / "escape.py"
    link.symlink_to(ctx.pipeline / "silver" / "specs" / "entities" / "orders.yaml")
    assert kind(ctx, "Write", file_path="gold/checks/escape.py", content="x") == DENY


@pytest.mark.parametrize("cmd", ["./dwh intake check all --gate B --json", "./dwh build silver --rebuild",
                                 "./dwh publish --target local", "./dwh generate --verify", "./dwh doctor --no-write"])
def test_full_options_still_allowed(ctx, cmd):
    assert kind(ctx, "Bash", command=cmd) == ALLOW, cmd
