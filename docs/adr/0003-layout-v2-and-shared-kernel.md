# 0003 — Layout v2 and a shared, pinned kernel

- **Date:** 2026-10-07 · **Status:** accepted (kernel 1.2.0)

## Context

A v1 project is one standalone folder: all sources in one `config/sources.yaml`, all metrics in one
`config/metrics.yaml`, proofs in `artefacts/`, data rows next to specs, and its own kernel copy. In a
repository of many pipelines that means large conflicting diffs, data one `git add` away, and many
kernel copies drifting apart.

## Decision

- **Per layer:** `bronze/ silver/ gold/ serve/`, each with `specs/`, `decisions/`, `generated/`,
  `reports/`; `project/` for people and policies; `intake/` for the workbook trail; `governance/`
  for approvals and releases.
- **One file per item:** each source, silver entity and metric card is its own YAML file.
- **Rows only in `.dwh/`:** warehouse, landed files, dead letters and snapshots — never committed.
- **One kernel:** `framework/dwh_core`. Pipelines pin its version; the kernel refuses a pipeline
  pinned to another version, so upgrades are explicit, per pipeline, reviewed.
- The kernel reads either layout into the same document, so hashes and approvals do not depend on
  the layout; `dwh layout migrate` moves v1 → v2 and proves the content identical before removing
  anything.

## Consequences

Adding a pipeline is adding a folder. Diffs are small and per item. Standalone v1 projects keep
working; the validation suite runs on both layouts.
