# Olist — Brazilian e-commerce

Pipeline `olist`, created 2026-10-07. Built with the dwh skills on the shared kernel in
`framework/` (layout v2).

## Status

| Step | State |
|---|---|
| Request written (`requirements/request.md`) | to do |
| Intake workbook answered and imported | to do |
| Bronze loaded | to do |
| After-first-load questions answered | to do |
| Silver, gold, dashboard built and verified | to do |
| Approved and released to consumers (a person, `./dwh approve`) | to do |

## Owners

| Role | Person |
|---|---|
| DE — data engineer | |
| PO — product owner (KPIs, dashboard) | |
| SME — business-rule owner | |
| GOV — governance (privacy, compliance) | |

## Where things are

| Folder | Holds |
|---|---|
| `requirements/` | what was asked, and the supplier's documentation |
| `data/` | `raw/` source files (never committed), `synthetic/`, `manifest.yaml` (which files a build used) |
| `project/` | people and policies, and who answered them (`decisions/`) |
| `intake/` | the agent's draft, the counts-only analysis, every workbook sent and returned |
| `bronze/` `silver/` `gold/` `serve/` | per layer: `specs/` (one file per source / entity / metric), `decisions/`, `generated/` (never edit), `reports/` (proofs) |
| `governance/` | approvals, release records, debt, decision records (`adr/`), lineage |

## Run it

```bash
python ../../tools/doctor.py olist   # once per machine: writes ./dwh (dwh.cmd on Windows)
./dwh status
./dwh build bronze && ./dwh build silver && ./dwh build gold
./dwh publish && ./dwh serve
```
