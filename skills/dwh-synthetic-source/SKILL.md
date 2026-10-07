---
name: dwh-synthetic-source
description: Generate synthetic source files for a dwh-init warehouse from bronze's own declared schema (same format, dialect, columns, batch naming), with planted defects (nulls, unparseable values, out-of-domain values, duplicates) recorded in a planted-truth ledger, and score the silver build against that ledger. Use whenever someone wants test data, fake/sample/dummy data, to try the pipeline before real files arrive, to rehearse a demo, or to prove the cleaning rules catch known defects in a dwh-* project.
---

# dwh-synthetic-source — test data with a known truth

> **Paths.** File paths below are for a layout-v1 project. In a layout-v2 pipeline (inside a pipelines repository) the same files sit per layer — specs in `<layer>/specs/`, proofs in `<layer>/reports/`, rejected rows and snapshots under `.dwh/`. `./dwh layout show` prints the exact places; the commands are identical.

Synthetic data proves nothing unless you know what is wrong in it. This tool writes files that
look exactly like the real sources (it reads `sources.<name>` — format, dialect, columns,
allowed values, batch pattern) and records every defect it plants in
`synthetic/truth_<source>.csv`. After silver runs, `dwh synth --score` checks that every planted
defect was dead-lettered with the right reason and that no clean row was rejected for a
structural reason (V21).

**Prerequisites:** `dwh-init` done and the bronze intake for those sources answered (the schema
is what gets generated). Local CSV and Parquet sources only. Run via `./dwh` or `dwh.cmd`.

## 1. Ask for every input first

`./dwh intake show synthetic`:

| Field (`synthetic.sources.<source>.`) | Lvl | Owner | Notes |
|---|---|---|---|
| `batches` | M | DE | batch ids, e.g. `[2024-01, 2024-02]`; `[full]` when the location has no `{batch}` |
| `rows_per_batch`, `seed` | M | DE | same seed → identical files |
| `defects` | M | DE | percent per class `{null: 2, cast: 1, domain: 1, duplicate: 2}`, or `none` |
| `columns.<col>` | O | DE | hints: `{range: [lo, hi]}`, `{choices: [...]}`, `{sequence: yes}`, `{format: '%d/%m/%Y'}`, `{null_rate: 30}`, `{after: <ts col>, minutes: [lo, hi]}` |
| `date_range` | O | DE | `[start, end]` when batch ids are not dates |

Make reference data line up with facts (e.g. zone ids `sequence: yes` 1..30 and trip zone hints
`range: [1, 30]`), and use `after` so end times follow start times — otherwise silver's rules will
(correctly) reject half the rows.

## 2. Generate, build, score

```bash
./dwh intake check synthetic
./dwh synth                       # writes the files into each source's location + truth ledgers
./dwh build bronze && ./dwh build silver
./dwh synth --score               # artefacts/synthetic-score.md
```

Explain the score: planted vs caught per class, wrong reasons, false positives; clean rows
rejected by **business** rules are listed separately (random values can legitimately break them).

## 3. Be explicit that it is synthetic

Generating flags the project as synthetic (`.dwh/synthetic.json`): every published snapshot and
the dashboard carry a **SYNTHETIC DATA** banner. Tolerances and volume bounds tuned on this data
must be recorded with `tolerance_source: synthetic` / `threshold_source: synthetic` and
re-confirmed by their owners on real data.

When real files arrive, synthetic rows must not mix with them. With the user's agreement, remove
the synthetic files from `data/raw/`, run `./dwh reset --data --yes` (clears warehouse, ledgers,
snapshots and dead letters; keeps every spec, answer and approval) and rebuild from bronze.
