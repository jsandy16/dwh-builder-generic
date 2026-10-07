# What dwh_core v1 does not do (yet)

v1 is the MVP slice of the plan (phases 1–2). When a request needs one of these, say so plainly
instead of approximating it.

| Not in v1 | What happens instead | Arrives with |
|---|---|---|
| Row-level security | any `serve.row_security` other than `none` is refused | governed phase |
| Regulated-mode controls for gdpr / hipaa / gxp (validation pack, versioned silver, identity-bound approvals) | the regime is recorded; release to consumers is refused | governed phase |
| Fiscal calendars (4-4-5 …) | refused at the gold gate; Gregorian only | governed phase |
| Custom (hand-written) steps in `custom/` | not executed; requirements templates cannot express are recorded as open | phase 2b |
| S3 / ADLS / GCS / SFTP / JDBC / paginated REST connectors | local files and plain HTTP(S) files only | phase 6 |
| SCD2 dimensions, star schema, schedulers, schema-change drills, DQ certificates | not part of these skills | phases 3–5 |
| Collecting every skill's Gate A before the first build | each build checks its own and its upstream skills' gates; `dwh intake show all` lets you collect everything up front | — |
| Per-reason dead-letter tolerances | one overall tolerance per entity | phase 3 |
| Read-back of gold filters with match counts | silver rules only (gold golden values and reconciliation catch wrong filters) | phase 3 |
| Case-folding of text keys | keys are trimmed, not lower-cased (IDs can be case-sensitive) | — |
| Identity proof for answers and approvals | answers are attributed to the person the user names; `approve` needs an interactive terminal — a guard rail, not authentication | governed phase |
| Windows CI | the validation suite ran on Linux; the wrappers and doctor are written for Windows (cmd / PowerShell / Git Bash) but have not been run there by the suite | phase 1 exit |
| Money above ~9×10¹⁵ | the no-silent-rounding check compares via DOUBLE | — |
