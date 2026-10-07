# Project layout

A project uses one of two layouts, set by `project.layout` in `dwh-project.yaml`. `./dwh layout show`
prints where every kind of file lives in the project at hand — trust it over this page.

- **v1** (standalone folder, the installer's default outside a repository): the table below.
- **v2** (a pipeline inside a pipelines repository — any parent folder has `framework/dwh_core`): one
  folder per layer, one spec file per source / entity / metric; see "Layout v2" at the end.
  `./dwh layout migrate` moves a v1 project to v2 and proves every spec and answer read back identical.

## Layout v1

| Path | Holds | Who writes it |
|---|---|---|
| `dwh-project.yaml` | project name, profile, builder, pinned kernel version, key algorithm | intake |
| `governance/people.yaml` | everyone who answers or approves, with roles | intake |
| `config/policies.yaml` | compliance, egress, time zone, calendar, money scale | intake (★ owners) |
| `config/sources.yaml` | bronze sources: connector, location, format, dialect, schema, classification, gates | intake |
| `config/silver.yaml` | silver entities: types, mapping, key, rules, null policy, merge | intake |
| `config/metrics.yaml` | metric cards (the source of truth for every KPI) | intake |
| `config/serve.yaml` | dashboard: KPIs, charts, freshness clock, access | intake |
| `config/synthetic.yaml` | synthetic test data spec (optional) | intake |
| `config/intake/provenance.yaml` | who answered each field, when, from which source (chat / workbook cell), value hash, default kept | kernel |
| `config/intake/draft.yaml` | the assistant's proposals for the workbook's defaults, with a note per path — never read by a build | assistant |
| `config/intake/workbooks/` | every imported workbook, exactly as received (its sha256 is in provenance) | kernel |
| `intake/<project>-intake.xlsx` | the intake workbook sent to the user (and `-issues.xlsx` copies when an import is refused) | kernel |
| `governance/approvals.log` | hash-chained approvals | **people only** (`dwh approve`) |
| `governance/lineage.md` | lineage diagram generated from each skill's registration | kernel |
| `governance/debt.md` | ★ decisions still pending (block consumer release) | kernel |
| `pipeline/generated/` | SQL/Python rendered from specs, each with a tamper-evident header | kernel — never edit |
| `custom/` | logic the templates cannot express, owned by a person (not executed by v1) | people |
| `data/raw/` | source files (git-ignored) | you / the source |
| `artefacts/` | proofs: `*-verify.md`, profile, read-backs, metric cards, serve check, screenshot | kernel |
| `artefacts/results/*.json` | the results each artefact is rendered from | kernel |
| `dead_letter/` | rejected files, unparseable records, rejected rows with reasons | kernel |
| `serving/` | published snapshots + `CURRENT` / `RELEASED` pointers | kernel |
| `.dwh/` | warehouse.duckdb, ledgers, lock, profile.json, analysis.json, actions log, salt (git-ignored) | kernel |

## Layout v2

| Path | Holds |
|---|---|
| `dwh-project.yaml` | name, profile, builder, `layout: v2`, pinned kernel version, key algorithm |
| `requirements/` | the request and the supplier's documentation (input; never written by a build) |
| `data/raw/` · `data/synthetic/` · `data/manifest.yaml` | source files (not in git) · synthetic spec + planted truth · what was received |
| `project/people.yaml` · `project/policies.yaml` · `project/decisions/provenance.yaml` | people, policies and who answered them |
| `intake/draft.yaml` · `intake/analysis.json` | the assistant's proposals · counts-only measurements |
| `intake/current/` | the workbook waiting to be filled (not in git) |
| `intake/workbooks/` | every workbook sent (`…_sent.xlsx`), returned and refused (`-issues.xlsx`), date-stamped |
| `bronze/specs/sources/<source>.yaml` | one file per source |
| `silver/specs/entities/<entity>.yaml` | one file per silver entity |
| `gold/specs/metrics/<metric>.yaml` | one file per metric card (golden values included) |
| `serve/specs/serve.yaml` | the dashboard |
| `<layer>/decisions/provenance.yaml` | who answered each of that layer's questions, from which workbook cell, default kept or not |
| `silver/decisions/readbacks/` | the rule read-back each owner confirmed (`<entity>.md` + counts) |
| `<layer>/generated/` | code rendered from the specs — never edit |
| `<layer>/reports/` | proofs: `*-verify.md/json`, profile, schema drift, metric cards, serve check, screenshot |
| `gold/checks/` | independent scripts that re-derive golden values from the raw files |
| `governance/` | `approvals.log` (people only), `releases/<snapshot>.json`, `debt.md`, `lineage.*`, `adr/` |
| `custom/` | logic the templates cannot express (not executed yet) |
| `.dwh/` | everything holding data rows or machine state: warehouse, ledgers, landed files, dead letters, snapshots, salt (not in git) |

In a repository the kernel is shared (`framework/dwh_core`): nothing is copied into the pipeline,
and the kernel refuses to run a pipeline that pins another version — upgrading is a reviewed change
to `project.dwh_core_version`.

Commands (prefix with `./dwh` or `dwh.cmd`):

| Command | Does |
|---|---|
| `doctor` | environment check; rewrites the wrappers |
| `intake analyze [folder]` | propose sources from a folder and measure them — counts only, no values |
| `intake workbook [--out FILE]` | write the Excel intake workbook: every question of every layer, defaults pre-filled |
| `intake import FILE [--dry-run]` | read a filled workbook back: all-or-nothing; records it, or writes `FILE-issues.xlsx` |
| `intake show <skill\|all> [--gate B]` | the questionnaire with the state of every field |
| `intake set <path> <value> \| --yaml … \| --file … --by <person> [--quote …] [--drafted]` | record an answer; `--drafted` = chosen by the assistant, blocks until confirmed |
| `intake pending <path> --owner <person> [--due …]` | ★ answer awaited (fast profile only) |
| `intake infer <source> --sample <file>` | propose a schema from a sample (must be confirmed) |
| `intake confirm <path> --by <person>` | confirm an inferred or drafted value (and everything drafted below it) |
| `intake check <skill\|all> [--gate B] [--unattended]` | the gate: exit 0 = may build |
| `intake readback <entity>` | render silver rules with match counts for the SME |
| `intake export <skill> --role PO` | plain-language form for one owner |
| `build bronze\|silver\|gold [--source s] [--batch b] [--unattended] [--rebuild]` | run a layer (refuses until its gate passes); `--rebuild` replays silver from all bronze history |
| `profile` | re-profile bronze |
| `publish [--target consumers]` | snapshot gold; consumers needs 0 pending ★ + a valid approval |
| `serve [--check] [--released]` | run the dashboard (localhost only) / prove it headlessly; `--released` shows the consumer snapshot |
| `synth [--score]` | synthetic files with planted truth / score silver against it |
| `status` | gates, ledgers, publish state, pending decisions |
| `generate [--verify]` | render generated code / detect hand edits |
| `layout show` / `layout migrate [--dry-run]` | where each file lives / move a v1 project to v2 (content-checked) |
| `reset --data --yes` | clear warehouse, ledgers, snapshots, dead letters; keep specs, answers, approvals (ask first) |

Exit codes: 0 ok · 1 verification failed (nothing committed) · 2 refused/blocked (inputs missing,
tampered file, stale upstream) · 3 unexpected error (trace in `.dwh/last_error.txt`) · 75 another run
holds the warehouse lease.
