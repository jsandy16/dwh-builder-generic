# 0001 — Geolocation: append batches, reject a re-delivered batch

- **Date:** 2026-10-07
- **Decided by:** sandeep (DE, SME)
- **Recorded in:** `olist-golden-values-returned.xlsx`, cells `Entities!F13` (merge strategy) and
  `Sources!I13` (re-delivery); proposed by Claude in the draft, kept by the owner.

## Context

The geolocation file has no key: the same zip-code prefix appears many times with different
coordinates. It was first set to `partition_replace`. Loading batch 02 failed silver's row-law
check V14b: 214 rows of batch 02 repeated rows already loaded from batch 01, so replacing a
partition would have silently dropped or duplicated rows.

## Decision

Merge strategy `append` (every batch adds its rows) and re-delivery policy `reject` (a batch that
arrives a second time is refused with an alert instead of being appended twice).

## Consequences

- Geolocation grows with every batch; repeated points are kept (they are real rows in the source).
- A corrected geolocation batch cannot replace the old one: it is rejected and needs a person to
  decide. The kernel's proposal now defaults keyless incremental entities to exactly this pair.
