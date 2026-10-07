# Bronze intake fields — explained

## location and batches
- Local: a path relative to the project, e.g. `data/raw/yellow_{batch}.csv`. Every file matching
  the pattern is a batch; the text that replaces `{batch}` is the batch id (`2024-01`). Batches are
  processed in ascending order.
- A source loaded as one file each time (full refresh) has no `{batch}`; its batch id is `full`.
- HTTP: `https://…/yellow_tripdata_{batch}.parquet` — HTTP sources need `--batch <id>` per run
  because URLs cannot be listed. Credentials: put the token in an environment variable and give
  its NAME in `credentials_env` (sent as a Bearer header).

## load_type → what silver can do
| load_type | Meaning | Silver merge strategies that fit |
|---|---|---|
| full_refresh | each file replaces everything | partition_replace, snapshot_diff |
| incremental_append | each batch adds rows (monthly files) | partition_replace (re-deliveries), upsert_by_version, append |
| snapshot | each batch is a full picture at a date | snapshot_diff, partition_replace |
| cdc | insert/update/delete records | cdc_apply |

## redelivery_policy (incremental / snapshot / cdc)
- `replace` — a batch id seen before with different content lands as `_batch_version` n+1 and
  silver replaces that batch's rows. Use when sources publish corrections (TLC does).
- `reject` — refuse it and log `redelivery_rejected`; someone decides by hand.

## schema.columns
```yaml
trip_id:      {type: VARCHAR, required: "yes", key: "yes"}
pickup_ts:    {type: TIMESTAMP, required: "yes"}
fare:         {type: "DECIMAL(10,2)", required: "yes"}
payment_type: {type: INTEGER, required: "yes", allowed_values: ["1", "2", "3", "4", "5", "6"]}
region:       {type: VARCHAR, required: "yes", allowed_values: [NA, EMEA, APAC, LATAM]}
```
- `required` = the column must be present in every file (a missing one rejects the file). Whether
  its values may be empty is a silver question (null policy).
- `key` marks identity columns for duplicate profiling.
- `allowed_values` are enforced in silver (`domain_<col>` dead-letter reason). `NA` inside the list
  is a value.
- Text formats land as VARCHAR whatever the declared type; the declared type is what silver casts
  to. Parquet types are fingerprinted: a declared INTEGER arriving as VARCHAR rejects the file
  (`type_change`) and routes to a schema change.

## classification (★ GOV, every column)
public · internal · pii · sensitive · regulated. pii/sensitive/regulated columns must later be
masked (hash), dropped or explicitly kept in silver — also ★ GOV.

## freshness
- `batch_token`: the batch id is a date, `token_format` its strftime format (`%Y-%m`), and a batch
  whose date is older than `window_days` is rejected `stale_batch`.
- `column`: the newest value of a date column (with its `formats`) must be within `window_days`.
- `none`: no freshness gate (historical/replayed data). Say so explicitly.

## volume
`min_rows`/`max_rows` bound a file's row count; `threshold_source` says where the numbers came
from (synthetic / real / owner) — synthetic thresholds must be re-confirmed on real data.
A zero-row file is always rejected: a broken source, never "no news".
