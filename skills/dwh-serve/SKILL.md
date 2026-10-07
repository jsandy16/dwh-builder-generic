---
name: dwh-serve
description: Publish verified gold tables of a dwh-init warehouse as a versioned snapshot and serve a local Streamlit dashboard whose KPIs are bound to the metric cards (ratios recomputed from numerator and denominator, never averaged), with a freshness banner, unreleased/synthetic banners and a headless `serve --check` proof with screenshot. Use whenever someone wants a dashboard, report, KPI view, "show me the numbers in a browser", to refresh or publish the warehouse output, or to release figures to consumers in a dwh-* project.
---

# dwh-serve — publish a snapshot, serve a dashboard bound to the cards

> **Paths.** File paths below are for a layout-v1 project. In a layout-v2 pipeline (inside a pipelines repository) the same files sit per layer — specs in `<layer>/specs/`, proofs in `<layer>/reports/`, rejected rows and snapshots under `.dwh/`. `./dwh layout show` prints the exact places; the commands are identical.

The dashboard never reads the warehouse directly. `dwh publish` copies verified gold into
`serving/snap_<run_id>/` with a manifest of row counts and file hashes, then swaps the
`serving/CURRENT` pointer last; the dashboard re-checks every hash before showing anything.
A crash mid-publish leaves the previous snapshot live.

**Prerequisites:** gold built and verified (`./dwh build gold`). Run commands via `./dwh` or
`dwh.cmd`.

## 1. Ask for every input first

**Questions are asked in the intake workbook.** A project set up by `dwh-init` collects these answers in its Excel workbook (the Dashboard and Dashboard visuals tabs). Run `./dwh intake check serve` first: if it passes, go to step 2. If something is missing or new (a new source, a new KPI, a changed rule), add your proposal to `config/intake/draft.yaml`, run `./dwh intake workbook`, send the file to the user and `./dwh intake import` what they send back — see dwh-init's `references/intake-workbook.md`. Use the per-field commands below only when the user asks to answer in chat.

Run `./dwh intake show serve`; present all questions in one form:

| Field | Lvl | Owner | Notes |
|---|---|---|---|
| `serve.title`, `serve.audience` | M | PO | |
| `serve.runtime` | M | DE | streamlit (v1) |
| `serve.reference_clock` | M | PO | event (newest data date vs today) / load (time since publish) / replay (historical or demo data — no stale alarm) |
| `serve.stale_after_hours` | C | PO | for event/load clocks |
| `serve.kpis.<name>` {metric, label} | M | PO | each KPI is a metric card; ratios are recomputed over the selection |
| `serve.charts.<name>` {type: line\|bar, metric, x, color, title} | M | PO | x and color must be grain columns of the metric; a non-additive metric must be charted at its full grain |
| `serve.filters` | O | PO | grain columns for sidebar filters |
| `serve.row_security` | M★ | GOV | `none` = every viewer sees every row. v1 does **not** enforce row-level security, so any other answer is refused — such a dashboard waits for the governed phase. May be pending in `fast` (blocks consumer release) |
| `serve.port`, `serve.auto_refresh_seconds` | O | DE | default 8501 / manual refresh |

Record with `--by <person>` as in the other dwh skills (YAML drafts + `--file` for the whole
`serve` block, ★ fields separately by their owner).

## 2. Gate, publish, check

```bash
./dwh intake check serve
./dwh publish                     # local snapshot → serving/CURRENT
./dwh serve --check               # V42 hashes, V30 KPI = gold headline, charts non-empty, headless start, screenshot
```

Read `artefacts/serve-check.md` and look at `artefacts/dashboard.png` before telling the user it
works. If a KPI differs from the gold-verified headline, do not adjust anything — report it.

## 3. Run it

```bash
./dwh serve                        # http://localhost:<port> (this machine only), Ctrl+C to stop
./dwh serve --released             # the snapshot released to consumers instead of the latest local one
```

Tell the user which banners they will see and why: **SYNTHETIC DATA** (the project was fed by
dwh-synthetic-source), **Unreleased** (★ decisions still pending — see `governance/debt.md`),
**STALE** (per the reference clock). After new data: `./dwh build bronze && ./dwh build silver &&
./dwh build gold && ./dwh publish` — the open dashboard picks up the new snapshot on refresh.

## 4. Releasing to consumers

```bash
./dwh publish --target consumers
```

This refuses unless **no ★ decision is pending, every gate passes in strict mode, the current
specs carry a valid approval, and the compliance regime is `none`** (v1 does not release
gdpr/hipaa/gxp data — the regulated-mode controls arrive with the governed phase). Approval is a person's act in their own terminal:
`./dwh approve --by <their id>` (role PO or GOV; in the governed profile not the builder).
You never run `approve` and never type someone's id into it. Any spec change after approval
invalidates it. When refused, show the user the exact reason and who must act.
