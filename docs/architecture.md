# Architecture

## Three parts

| Part | Where | Role |
|---|---|---|
| Skills | `skills/` | instructions Claude follows: what to ask, when to stop for a person, how to report |
| Kernel | `framework/dwh_core` | the only thing that builds; refuses to run unless the gates pass |
| Pipelines | `pipelines/<name>/` | one warehouse each: specs, answers, generated code, proofs |

Claude never writes runtime SQL or Python. It edits **specs** (through the workbook import or
`dwh intake set`); the kernel **renders** code from specs with tamper-evident headers and **runs**
it; every run writes **proofs** (`<layer>/reports/`).

## The answer path

```
request + data  ──analyse (counts only)──▶  draft.yaml  ──▶  intake workbook (.xlsx)
                                                                  │  people answer
                                                                  ▼
             specs (YAML, one file per item)  ◀──import (all-or-nothing, every gate)
             + provenance (who, when, which cell, default kept?)
```

Every catalogue question has an owner (DE / PO / SME / GOV) and a level: **M** mandatory,
**M★** mandatory owner decision, **C** conditional, **O** optional. ★ answers can never be
recorded by the agent. Each recorded answer carries a hash of its value, so a hand edit to a YAML
file is detected and blocks the build.

## The build path

| Layer | Input → output | Proves |
|---|---|---|
| bronze | files → `bronze_<source>` as received (+ `_src, _batch_id, _batch_version, _row_number …`) | declared columns, types, zero rows, volume, freshness; records = landed + parse rejects |
| silver | bronze → one table per entity | rows in = survivors + dead-lettered + duplicates; one merge outcome per survivor; no cast loss; tolerance |
| gold | silver → one table per metric card | golden values; reconciliation to silver; exclusion bounds; denominator population |
| serve | gold → snapshot (parquet + manifest) → dashboard | file hashes match the manifest; ratios recomputed, never averaged; headless check |

Approval (`dwh approve`) binds the hash of every spec and answer; any change makes it stale.
Consumer release needs a valid approval and no pending ★ decisions.

## Layouts

Layout v1 (one standalone folder, its own kernel copy) is what the skills create outside a
repository. Layout v2 is what this repository uses. Both hold the same document, so hashes,
approvals and gates are identical; `dwh layout migrate` moves v1 → v2. See
[ADR 0003](adr/0003-layout-v2-and-shared-kernel.md).

## Determinism

Rendering is deterministic (byte-identical across runs; 1 vs 4 threads give identical content
hashes — validation V43). Time comes from `DWH_FIXED_NOW` in tests and from the reference clock in
demo mode.
