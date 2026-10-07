# 0004 — Raw data stays out of git; a manifest records it

- **Date:** 2026-10-07 · **Status:** accepted

## Context

Source files can be large and can hold personal data. Git history cannot be cleaned easily, and
Git LFS spreads the data to every clone and uses quota.

## Decision

`data/raw/` is ignored. `data/manifest.yaml` (committed) lists every file a build used with size,
sha256 and row count; `tools/data_manifest.py --check` proves a rebuild uses the same files. CI
needs no real data: it checks contracts, gates and generated code from specs alone.

## Consequences

Whoever rebuilds must obtain the files from their owner. If versioned data is ever required, a
cloud bucket referenced from the source spec is preferred over LFS.
