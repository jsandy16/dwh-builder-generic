# dwh-builder-generic

A framework for building checked data warehouses with Claude. You describe the data and what you
want to measure; Claude asks every question in one Excel workbook, the owners answer it, and a
build kernel turns the answers into bronze → silver → gold → dashboard. Every layer proves itself by
counting, so nothing reaches a report without passing checks.

**The rule behind everything: Claude drafts and runs; people decide.** No answer counts until a
named person has given it, and only a person can approve a release.

## What is in this repository

| Folder | What it holds |
|---|---|
| [`framework/`](framework/) | `dwh_core`, the build kernel: one shared, versioned copy used by every pipeline |
| [`skills/`](skills/) | the six Claude skills (dwh-init, dwh-bronze, dwh-silver, dwh-gold, dwh-serve, dwh-synthetic-source) |
| [`pipelines/`](pipelines/) | one folder per warehouse project, e.g. [`pipelines/olist/`](pipelines/olist/) |
| [`templates/pipeline/`](templates/pipeline/) | the skeleton every new pipeline starts from |
| [`validation/`](validation/) | the end-to-end test suite (≈200 checks, run on both project layouts) |
| [`tools/`](tools/) | repo scripts: new pipeline, package skills, layout checks, data manifest, and the terminal agent ([`tools/dwh_agent.py`](tools/dwh_agent.py)) |
| [`docs/`](docs/) | the life-cycle guide, architecture, repository layout, runbooks, decision records |

## Quick start

```bash
pip install -r framework/requirements.txt

# a new pipeline: one folder, nothing else to change
python tools/new_pipeline.py sales
#   then put the request in pipelines/sales/requirements/request.md
#   and the files in pipelines/sales/data/raw/ (not committed),
#   and ask Claude: "set up the warehouse for pipelines/sales"

# once per machine: check Python and write each pipeline's ./dwh (dwh.cmd on Windows) wrapper
python tools/doctor.py

# work inside a pipeline
cd pipelines/olist
./dwh status
./dwh intake check all
```

The full walk-through for non-engineers is in [`docs/guide.md`](docs/guide.md).

### Or from the terminal: the dwh agent

```bash
pip install -r tools/dwhagent/requirements.txt
export ANTHROPIC_API_KEY=...            # an Anthropic API key; each session costs money (default cap $5)
python tools/dwh_agent.py sales --check # where the pipeline stands (free, no AI)
python tools/dwh_agent.py sales         # Claude drafts, builds and explains; you decide
```

The agent works on one pipeline, for any kind of data. It drafts every answer and writes the
workbook, runs the builds and commits locally. It never answers for an owner, never sees data
values, and never approves, releases or pushes; those limits are enforced in code. See
[`docs/agent.md`](docs/agent.md).

## Adding a pipeline

`python tools/new_pipeline.py <name>` creates `pipelines/<name>/` from the template and pins the
shared kernel. CI discovers every `pipelines/*/dwh-project.yaml` by itself, so the framework does
not change when you add one. What a pipeline folder must contain is in
[`docs/pipeline-contract.md`](docs/pipeline-contract.md).

## What git holds, and what it does not

| In git | Never in git |
|---|---|
| specs (one file per source, entity, metric), answers and who gave them, every intake workbook, generated code, reports (counts only), approvals, release records, the data manifest | raw data (`data/raw/`), the warehouse and everything with data rows (`.dwh/`), the salt, the `dwh` / `dwh.cmd` wrappers (machine-specific) |

`.gitignore` and a pre-commit hook enforce this. Raw data stays with whoever is allowed to hold it;
`data/manifest.yaml` records exactly which files (sha256, rows) a build used.

## Versions

Kernel `dwh_core` **1.2.0** · project layout **v2** (see [`CHANGELOG.md`](CHANGELOG.md)).
A pipeline pins the kernel version it was built with; the kernel refuses to run a pipeline pinned
to another version, so upgrading is always a reviewed change.
