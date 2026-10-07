# Changelog

## 1.2.0 — pipelines repository

- **Layout v2.** One folder per layer (`bronze/ silver/ gold/ serve/`), each with `specs/`,
  `decisions/`, `generated/` and `reports/`. Sources, silver entities and metrics are one YAML file
  each. Every file holding data rows (warehouse, landed files, dead letters, snapshots) lives in
  `.dwh/`, so a pipeline folder can be committed as is.
- **Shared kernel.** Inside a repository (`framework/dwh_core` above the pipeline) the installer
  copies nothing; the pipeline pins the kernel version and the kernel refuses a version it was not
  pinned to.
- `dwh layout show` and `dwh layout migrate` (v1 → v2): every spec and answer is read back and
  compared before the old files are removed; approvals stay valid.
- Publishing writes a small release record to `governance/releases/<snapshot>.json`.
- Every generated intake workbook is archived as `…_sent.xlsx` next to the returned copies.
- Validation suite: new layout suite (migration, shared kernel, one file per spec); the whole suite
  runs on both layouts. Unit tests (`framework/tests`).
- **Fix:** `dwh publish` failed to import on Python 3.10/3.11 (an f-string that only Python 3.12+
  accepts). Found by the new lint step; the kernel now compiles on 3.11–3.13.
- Hardening from an independent review: a migration interrupted midway leaves a working v1 project
  and can simply be run again; a refused spec save writes nothing; spec file names are compared
  without case (Windows/macOS); an invalid `project.layout` is explained instead of a traceback; the
  installer never changes an existing project's layout.

## 1.1.0 — intake workbook

- Every question of every layer in one Excel workbook, a tab per kind of question, defaults
  pre-filled from the catalogue, the data analysis (counts only) and the agent's draft.
- All-or-nothing import with an `-issues.xlsx` copy; ★ defaults kept are recorded as the owner's
  answer and listed by `dwh status`.
- After-first-load round (ambiguous dates, rule read-back, never-filled columns).
- Fixes: lookups on hashed reference keys; read-back regeneration cancelling a confirmation;
  keyless incremental entities default to `append` + redelivery `reject`.

## 1.0.0 — first release

- dwh_core kernel, intake gates A/B with owners and provenance, bronze / silver / gold / serve,
  synthetic source with planted truth, approvals and release gate.
