# Why a file was rejected, and who fixes it

Nothing from a rejected file is landed and no checkpoint is written, so fixing the cause and
re-running the build simply picks the file up again.

| Reason | Meaning | Who acts |
|---|---|---|
| `missing_required_columns` | a column declared `required: yes` is absent | source owner fixes the file, or the DE changes the schema through a schema change |
| `unexpected_columns` | new columns and `drift_policy: reject` | DE decides: add them to the schema (and GOV classifies them) or keep rejecting |
| `type_change` | a typed file's column type differs from the declaration or from the first batch | schema change — never relax the declared type silently |
| `zero_rows` | the file has no records | source owner (a zero-row file is broken, not "quiet") |
| `volume_out_of_bounds` | fewer than `min_rows` / more than `max_rows` | source owner, or the DE updates the bounds with a stated threshold source |
| `stale_batch` | newest data older than `window_days` | source owner; or the PO changes the window |
| `bad_batch_token` | the batch id does not match `token_format` | file naming / DE |
| `freshness_unknown` | no value of the freshness column matches its formats | DE fixes the formats |
| `redelivery_rejected` | a loaded batch came back with new content and the policy is `reject` | DE decides whether to switch to `replace` |
| `file_not_found` / `unreachable` | path wrong, or network failed after the retries | DE / infrastructure |
| `batch_required` | an HTTP source was run without `--batch` | run with `--batch <id>` |

Unparseable records (wrong column count, broken quoting) are not file rejections: they go to
`dead_letter/parse_<source>.csv` with the line number, and the build proves
`records = landed + parse rejects` for every batch.
