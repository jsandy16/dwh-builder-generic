# 0002 — Moved into the pipelines repository (layout v2, kernel 1.2.0)

- **Date:** 2026-10-07
- **Decided by:** sandeep (asked for the repository structure)
- **Recorded in:** `dwh-project.yaml` (`layout: v2`, `dwh_core_version: "1.2.0"`)

## Context

The project was a standalone folder (layout v1, its own copy of kernel 1.1.0). The repository keeps
one shared kernel and one folder per layer, with one spec file per source, entity and metric.

## Decision

Migrated with `dwh layout migrate`, which wrote every spec and answer into the v2 files, read them
back and compared them with the originals before removing anything. The only spec line that
changed is the kernel pin (1.1.0 → 1.2.0), which is why any earlier approval would be stale.

## Consequences

- Rebuilt on 1.2.0 with the same results: silver 216 checks, gold 48 checks, the 18 golden values,
  the same row counts in every gold table; the dashboard check passed.
- The project has not been approved yet; approval and consumer release stay with a person.
