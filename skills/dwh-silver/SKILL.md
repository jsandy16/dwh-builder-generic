---
name: dwh-silver
description: Build the silver layer of a dwh-init warehouse — type, conform several sources into one entity, de-duplicate with a tiebreaker, apply owner-approved business rules (valid anomalies kept, impossible rows dead-lettered with reasons), null policies, masking, lookups and flags, then merge by strategy (append, upsert by version, partition replace, CDC, snapshot diff) — proven by an exact row-count law before every commit. Use whenever someone wants to clean, standardise, deduplicate, conform, validate or "fix" bronze/raw data, define cleaning or business rules, handle refunds/negative values, nulls, date formats or late/corrected batches in a dwh-* project.
---

# dwh-silver — clean, conform, prove it by counting

> **Paths.** File paths below are for a layout-v1 project. In a layout-v2 pipeline (inside a pipelines repository) the same files sit per layer — specs in `<layer>/specs/`, proofs in `<layer>/reports/`, rejected rows and snapshots under `.dwh/`. `./dwh layout show` prints the exact places; the commands are identical.

Silver turns bronze into one trustworthy table per business entity. Every rule that changes
or removes data is a **decision with an owner**, recorded before the build; every batch is
committed only after the kernel proves, from counts:

`batch rows = survivors + dead-lettered + duplicates`, every survivor has exactly one merge
outcome, the table changed by exactly `inserted − removed`, no cast loss, no NULL or duplicate
keys, the dead-letter share is within tolerance — otherwise the batch rolls back untouched.

**Prerequisites:** `dwh-init` done and bronze built (`./dwh build bronze`), because some silver
questions can only be asked after profiling. Run commands via `./dwh` or `dwh.cmd`.

## 1. Ask for every input first

**Questions are asked in the intake workbook.** A project set up by `dwh-init` collects these answers in its Excel workbook (the Silver model, Entities, Data quality and Lookups & flags tabs — and, after the first load, the After first load tab (ambiguous dates, rule read-back, never-filled columns)). Run `./dwh intake check silver --gate B` first: if it passes, go to step 2. If something is missing or new (a new source, a new KPI, a changed rule), add your proposal to `config/intake/draft.yaml`, run `./dwh intake workbook`, send the file to the user and `./dwh intake import` what they send back — see dwh-init's `references/intake-workbook.md`. Use the per-field commands below only when the user asks to answer in chat.

Run `./dwh intake show silver --gate B` and read `artefacts/bronze-profile.md`. Present one form
per entity, grouped by owner. You may **draft** DE fields from the bronze schema (columns, types,
formats, mapping) — show the draft and get it confirmed. You never draft ★ fields.

| Field (`silver.entities.<entity>.`) | Lvl | Owner | Notes |
|---|---|---|---|
| `policies.timezone.reporting` (project) | M★ | PO | IANA name; decides which day a timestamp belongs to |
| `sources` | M | DE | bronze sources feeding the entity |
| `columns.<c>.type` | M | DE | money is DECIMAL(p,s), never DOUBLE |
| `columns.<c>.formats` | C | DE | every date/time format present, most common first (the profile lists them) |
| `columns.<c>.source_timezone` | C | DE | zone timestamps were recorded in |
| `mapping.<source>.<c>` | C | DE | needed for >1 source or renames: a source column, an expression, or `NULL` (never supplied) |
| `natural_key` | M | DE | identity columns only — never a measure that can be corrected |
| `tiebreaker` | M | DE | which duplicate wins, e.g. `["updated_at DESC"]`; must separate every real duplicate |
| `rejected_survivor_policy` | M★ | SME | keep_last_good / reject_key — if a record's newest version fails a rule |
| `null_policy.<c>` (every column) | M | SME | drop (dead-letter) / impute:<value> (flagged `is_<c>_imputed`) / keep |
| `structural_nulls."<c>\|source=<s>[\|col=val]"` | M★ | SME | structural (never measured there → stays NULL) / defect |
| `valid_anomalies` | M★ | SME | rows that look wrong but are real (refunds) — {name: {predicate, reason}} or `none` |
| `hard_rejects` | M | SME | impossible rows — {name: {predicate, reason}} or `none` |
| `dead_letter_tolerance_pct`, `tolerance_source` | M | PO | fail if more of a batch is dead-lettered |
| `merge.strategy` (+ `version_column` / `op_column`, `op_codes`, `sequence_column` / `partition_column`) | M / C | DE | see `references/merge-strategies.md` |
| `lookups.<name>` {reference, on, columns} + `missing` (SME) | O | DE | brings in `<name>_<column>`; reference key must be unique |
| `flags.<name>` | O | SME | business flags defined once, as SQL conditions |
| `masking.<c>` | M★ | GOV | hash / drop / keep — required for every pii/sensitive/regulated column |
| `drop_columns.<col>` | O | DE | bronze columns deliberately not carried, with a reason (every other column must map) |
| `date_ambiguity.<c>` | M★ (gate B) | SME | prefer_first / reject — asked only when values parse to different dates under two formats |
| `readback_confirmed` | C★ (gate B) | SME | yes, after the SME has seen the rule read-back |

Rules and flags are single SQL conditions over the entity's canonical columns
(`total_amount < 0`, `dropoff_ts <= pickup_ts`, `pu_zone IN (1, 132, 138)`). The kernel refuses
statements, subqueries, file/HTTP functions and unknown columns. Write the SME's words into the
`reason`; record the predicate exactly as agreed.

`references/fields.md` has worked examples (single source, two sources with a `NULL` mapping, a
CDC feed) and explains each choice in plain language for the business owner.

Record answers attributed to whoever gave them (`--by <person>`; `--quote` their words for ★).
Write anything longer than one value as a YAML draft with your file tool (`.dwh/drafts/…`) and
pass `--file`; SQL inside shell-quoted `--yaml` breaks easily:

```bash
./dwh intake set silver.entities.trips --file .dwh/drafts/trips_entity.yaml --by dana
./dwh intake set silver.entities.trips.valid_anomalies --file .dwh/drafts/trips_anomalies.yaml --by sam --quote "negatives are refunds, keep them"
./dwh intake set silver.entities.trips.null_policy.passenger_count "impute:1" --by sam
./dwh intake set silver.entities.trips.hard_rejects none --by sam
```

Only decisions the build does not compute with may wait for their owner in the fast profile
(compliance, egress, dispute owner, golden values, row security); every silver ★ decision is
needed to build, so `intake pending` refuses it — ask the owner.

**Values you chose yourself.** Anything the person did not state or clearly imply — a project or
source name, a load type, a key, a tolerance — is a draft. When they are present, show it and
record it once they agree. When they are not (an unattended run), record it with `--drafted
--by <the person who must confirm it>`: the gate then treats it as unanswered until that person
confirms (`./dwh intake confirm <path> --by <person>`), and your note lists every draft. Never
draft a ★ field.

**When the templates cannot express a requirement** (currency conversion, geo matching,
sessionisation, exploding lists…), stop and say so: v1 generates every runtime step from specs and
does not run hand-written SQL. Do not approximate it with a rule or a mapping expression that
means something else; record it as an open requirement for the owner.

## 2. The read-back (V07) — the SME must see the rules run on real data

```bash
./dwh intake readback <entity>
```

This renders `artefacts/readback-<entity>.md`: every rule as it will run, how many bronze rows it
matches, and any row that is both a valid anomaly and a hard reject (a conflict blocks the build).
Show it to the SME **verbatim**, point out rules that match 0 rows (often mistyped), and record
their verdict: `./dwh intake set silver.entities.<entity>.readback_confirmed yes --by <sme>`.
Any later change to the rules invalidates it — run the read-back again.

## 3. Gate B, then build

```bash
./dwh intake check silver --gate B     # must exit 0
./dwh build silver
```

Gate B also asks, from the data: structural-null decisions for columns ~100% NULL for a source or
subset, and a parse rule for values that read as different dates under two declared formats **or
with day and month swapped** (03/04/2024 under `%d/%m/%Y` is also a valid `%m/%d/%Y` date).
Put these to the SME as plain questions — never choose for them.

If the specs changed since the last build, silver is rebuilt from all bronze batches (latest
version of each); otherwise only new or re-delivered batches are processed. A re-delivered batch
under upsert/CDC/snapshot/append, or a snapshot that arrives after a newer one, makes the entity
replay its whole history in batch order, so the result never depends on arrival order. Force a
replay with `./dwh build silver --rebuild`.

## 4. Report

Read `artefacts/silver-verify.md` and tell the user, per batch: rows in, kept, dead-lettered (the
reason counts are in its facts), duplicates, inserted/updated/removed/withdrawn. The rejected rows
themselves are in `dead_letter/silver_dead_letter.csv` (protected columns hashed); it is data for
the owners, so read individual rows only if the egress policy allows samples. If a
check failed, nothing from that batch was committed: name the check (e.g. `TOL-…` tolerance,
`V14a` ties the tiebreaker cannot separate, `V23` duplicated reference key) and ask the owner of
that input. **Never** loosen a tolerance, edit a rule or change a key yourself to make it pass.

Then suggest `dwh-gold`.
