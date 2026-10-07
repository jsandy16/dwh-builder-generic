---
name: dwh-gold
description: Build gold KPI tables in a dwh-init warehouse from metric cards — the owner-approved definition of each number (formula, filters, grain, denominator, zero-denominator rule, additivity, golden values) — and prove every build against hand-computed golden values, per-key reconciliation to silver, exclusion bounds and denominator population. Use whenever someone wants metrics, KPIs, aggregates, a gold/mart/reporting layer, revenue/churn/conversion/average numbers, or asks "why is this KPI different" in a dwh-* project, even if they only say "add a churn rate" or "give me daily revenue by region".
---

# dwh-gold — metric cards → verified KPI tables

> **Paths.** File paths below are for a layout-v1 project. In a layout-v2 pipeline (inside a pipelines repository) the same files sit per layer — specs in `<layer>/specs/`, proofs in `<layer>/reports/`, rejected rows and snapshots under `.dwh/`. `./dwh layout show` prints the exact places; the commands are identical.

A metric that is valid SQL but means the wrong thing is the most expensive failure in reporting.
So the **card is the source of truth, not the SQL**: the product owner states what the number
means, the kernel renders the SQL from the card, and every build proves the result against
numbers the owner computed by hand. Gold is rebuilt fully every run, inside one transaction,
and committed only if every check holds.

**Prerequisites:** silver built and current (`./dwh build silver`). Run commands via `./dwh` or
`dwh.cmd`.

## 1. Ask for every card input first

**Questions are asked in the intake workbook.** A project set up by `dwh-init` collects these answers in its Excel workbook (the Reporting policy, KPIs and Golden values tabs). Run `./dwh intake check gold` first: if it passes, go to step 2. If something is missing or new (a new source, a new KPI, a changed rule), add your proposal to `config/intake/draft.yaml`, run `./dwh intake workbook`, send the file to the user and `./dwh intake import` what they send back — see dwh-init's `references/intake-workbook.md`. Use the per-field commands below only when the user asks to answer in chat.

In chat: run `./dwh intake show gold` and interview the product owner metric by metric; the questions in
`references/metric-cards.md` are written for a business person. Never draft a formula, filter,
grain or denominator yourself — these are ★ PO answers. Non-★ fields (entity, target table,
unit, precision, reconciliation…) you may draft from what was said and show for confirmation;
unconfirmed drafts are recorded with `--drafted` (see dwh-init).

Project policies (once): `policies.calendar.type` (★ PO; v1 builds `gregorian`),
`policies.calendar.week_start` (★ PO), `policies.money.scale` (★ PO).

Per metric (`metrics.<name>.`; names become column names — letters, digits, underscore):

| Field | Lvl | Owner | Notes |
|---|---|---|---|
| `entity`, `plain_definition` | M | DE / PO | |
| `metric_type` | M★ | PO | sum / count / distinct_count / ratio / average |
| `numerator.measure`, `numerator.filter` | M★ | PO | `count` · `sum:<col>` · `count_distinct:<col>`; filter is a SQL condition or `none` |
| `denominator.measure` | C★ | PO | ratio / average |
| `denominator.include.column` + `include.values` + `exclude.values` | C★ | PO | ratio: an **inclusion list** — a value nobody classified stops the build |
| `filters` | M★ | PO | rows excluded from the whole metric, or `none` |
| `zero_denominator` | C★ | PO | null / zero / omit (omit needs its own table) |
| `population` | O (required when an input is imputed or structurally NULL) | PO | which rows count |
| `grain`, `time_grain`, `date_basis` | M★ / M★ / M | PO | one row per …; date basis must be in the grain |
| `unit`, `precision`, `additivity` | M | PO | count / percent / currency:USD …; additive / semi_additive / non_additive |
| `valid_range.min`, `.max`, `cadence` | M | PO | `none` allowed for a range side |
| `dispute_owner` | M★ | PO | the named person who arbitrates the meaning (may be pending in `fast`) |
| `golden_values` | M★ | PO | ≥3 values the owner computed **by hand from the raw data**: `[{key: {<grain col>: <value>, …}, value: <number or null>}]` (may be pending in `fast` — then nothing is released to consumers) |
| `version`, `effective_from` | M | DE | |
| `reconciliation.control`, `.excluded_by`, `.max_excluded_pct` | M | DE / PO | silver total the metric ties back to; rows deliberately outside it; bound on that share |
| `target_table` | M | DE | metrics sharing a table share entity, grain, time grain and date basis |

**Golden values are the owner's, not yours.** Do not compute them from the warehouse — that
proves nothing. Ask the owner to pick ≥3 grain keys (include a tricky one: a refund day, a day
with no denominator) and work the numbers from the source data by hand or in their own
spreadsheet. If they ask you to help, compute them **from the raw files with an independent
method** (e.g. pandas over the source CSV), show your working, and record them only after the
owner confirms them as theirs (`--by <po>`).

For anything longer than one value, write the YAML to a draft file with your file tool and pass
`--file` (shell quoting of SQL inside `--yaml '…'` breaks easily):

```yaml
# .dwh/drafts/churn_rate.yaml — the DE part of the card
entity: events
plain_definition: Share of active+churned events that are churn, per day (trialing excluded).
date_basis: event_date
unit: percent
precision: "2"
additivity: non_additive
valid_range: {min: "0", max: "100"}
cadence: daily
version: 1.0.0
effective_from: 2024-01-01
reconciliation: {control: count, excluded_by: "status NOT IN ('active', 'churned')", max_excluded_pct: "60"}
target_table: gold_churn_rate
population: NA
```

```bash
./dwh intake set metrics.churn_rate --file .dwh/drafts/churn_rate.yaml --by dana
./dwh intake set metrics.churn_rate.metric_type ratio --by priya
./dwh intake set metrics.churn_rate.numerator.filter "status = 'churned'" --by priya
./dwh intake set metrics.churn_rate.denominator.include.values --yaml '[active, churned]' --by priya
./dwh intake set metrics.churn_rate.golden_values --file .dwh/drafts/churn_golden.yaml --by priya
```

## 2. Gate, then build

```bash
./dwh intake check gold     # must exit 0
./dwh build gold            # refuses if silver is not current
```

## 3. Report

`artefacts/gold-verify.md` lists every check; `artefacts/metric-cards.md` renders each card for
humans. Explain failures in the owner's terms:

- **V25 golden value** mismatch → the card and the owner's hand calculation disagree. Show both
  numbers; the owner decides whether the card or their calculation is wrong. Never edit a golden
  value to match the warehouse.
- **V27 reconciliation** off for N keys → `metric + excluded ≠ silver control`: the filter and
  `excluded_by` don't describe complementary sets (often NULLs on the filter column).
- **V28 excluded share** above bound → an exclusion is swallowing too much.
- **V26b unclassified value** → a new value of the denominator column appeared; the PO must put it
  in include or exclude.
- **Distinct counts** reconcile as `metric = distinct count over the rows not excluded`, per key.
- A golden value of `0` (count/sum) or `null` (ratio) for a key with no qualifying rows is valid.
- **RANGE** → values outside the plausible range.

Ratios publish `<metric>__num` and `<metric>__den`; dashboards must recompute ratios from them
and never average a ratio. Then suggest `dwh-serve`.
