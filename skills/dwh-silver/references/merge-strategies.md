# Merge strategies

Pick by how the source delivers data. One rule for every load type loses updates or resurrects
deletes, so the gate checks the strategy against each source's `load_type`.

| Strategy | Use for | Extra inputs | Behaviour (proven per batch) |
|---|---|---|---|
| `append` | immutable events | — | new keys inserted; a key already present is counted `already_present` and not duplicated. Cannot apply a corrected re-delivery — use another strategy if `redelivery_policy: replace` |
| `upsert_by_version` | records updated over time | `version_column`; tiebreaker must start `"<version> DESC"` | incoming row wins only if its version is newer; a late, older batch never overwrites (`stale`) |
| `partition_replace` | monthly files, full refreshes, corrected re-deliveries | `partition_column` (default: the batch) | the batch's partition for that source is deleted and re-inserted atomically |
| `cdc_apply` | change feeds | `op_column`, `op_codes.{insert,update,delete}`, `sequence_column`; tiebreaker `"<seq> DESC"` | changes applied in sequence; deletes become `_is_deleted = true`; an older change never resurrects a delete |
| `snapshot_diff` | full snapshots | — | keys missing from the new snapshot are soft-deleted, changed rows replaced, returning keys reactivated; an older snapshot arriving after a newer one is refused |

Every silver table has `_sk` (surrogate key = md5 of the canonical natural key), `_row_hash`,
`_src, _batch_id, _batch_version, _source_file, _row_number, _loaded_at, _is_deleted`.
Gold reads only rows with `_is_deleted = false`.

## Row law terms
`survivors = inserted + updated + stale + already_present + unchanged + reactivated (+ deleted for CDC)`
and `Δ table = inserted − removed`. The cumulative check compares the row count before each batch
with the ledger, so a table changed outside the pipeline is detected.
