# dwh skill suite — validation report

Run on 2026-10-07 10:53 UTC · Python 3.13.16 · DuckDB 1.5.6 · Linux x86_64 · project layout **v2**

**201 of 201 checks passed** across 11 suites.

| Suite | Result | Checks | Time |
|---|---|---|---|
| Kernel + intake gate suite | PASS | 48/48 | 8.1 s |
| Domain 1 — Module 700 pack sample (content oracle) | PASS | 18/18 | 39.5 s |
| Generated code: deterministic rendering + tamper detection | PASS | 3/3 | 2.4 s |
| Domain 2 — taxi-style, synthetic data, 3 sources | PASS | 29/29 | 99.2 s |
| Merge strategies (append / upsert / CDC / snapshot, late + out-of-order) | PASS | 13/13 | 31.3 s |
| Mutation-kill matrix (V33) | PASS | 19/19 | 101.0 s |
| Independent-review regressions (C1–C3, H1–H8, M2–M8, L8, drafts, formats) | PASS | 25/25 | 79.7 s |
| Intake workbook (analyse → draft → Excel → import, all-or-nothing) | PASS | 32/32 | 75.3 s |
| Layout v2 + pipelines repository (migrate, shared kernel, one file per spec) | PASS | 12/12 | 2.9 s |
| Determinism (V43) | PASS | 1/1 | 92.7 s |
| python -O (V40) | PASS | 1/1 | 38.7 s |

## Kernel + intake gate suite

- ✅ YAML is read as strings: NO, NA, 010, 1.10, ~ survive (V01)
- ✅ NA means not-applicable only as a whole answer; inside a list it is a value
- ✅ written YAML round-trips safely
- ✅ fragment refused: 'amount > 0; DROP TABLE x' → SQL fragments must be a single expression (no ';')
- ✅ fragment refused: 'amount > (SELECT 1)' → not allowed in spec fragments: subquery
- ✅ fragment refused: "read_csv('x') IS NOT NULL" → function(s) not allowed in spec fragments: read_csv
- ✅ fragment refused: "getenv('HOME') = 'x'" → function(s) not allowed in spec fragments: getenv
- ✅ fragment refused: 'nosuch > 1' → unknown column(s): nosuch (available: amount, status, ts)
- ✅ fragment refused: 'amount + 1' → a filter/rule must be TRUE/FALSE, but this expression is DECIMAL(13,2)
- ✅ fragment refused: "status = 'a' UNION SELECT 1" → not a valid SQL expression: syntax error at or near "UNION"
- ✅ fragment refused: 'row_number() OVER () > 1' → not allowed in spec fragments: window
- ✅ fragment accepted: 'amount < 0'
- ✅ fragment accepted: "status IN ('a', 'b;c')"
- ✅ fragment accepted: "ts >= TIMESTAMP '2024-01-01'"
- ✅ fragment accepted: "lower(status) LIKE 'x%'"
- ✅ fragment accepted: 'amount BETWEEN 1 AND 2 OR status IS NULL'
- ✅ type strings are shape-checked before reaching DuckDB
- ✅ keys canonicalise whitespace (' EVT-1 ' = 'EVT-1')
- ✅ key is an md5 over a JSON struct
- ✅ golden key test: key_algo v1 output unchanged (V15)
- ✅ a NULL key still hashes deterministically (no crash)
- ✅ empty project: every mandatory input reported missing
- ✅ ★ answer attributed to the agent is refused (V05) — refused: policies.compliance is human-owned; the agent cannot be its author. Ask the GOV owner and record thei
- ✅ ★ answer from someone without the owner role is refused — refused: 'dana' does not hold role GOV in the people list, so cannot answer policies.compliance. Mark it pendi
- ✅ 'default' on a ★ field is refused
- ✅ 'infer' on a ★ field is refused
- ✅ NA on a mandatory field blocks the gate with the reason
- ✅ fast profile: a pending ★ answer is a warning, the gate passes
- ✅ unattended run: a pending ★ answer blocks (§5.6)
- ✅ a ★ value edited outside the intake is detected (value hash)
- ✅ project gate passes once every answer is recorded by its owner
- ✅ C field with a false condition (CSV dialect for parquet) is skipped
- ✅ C field with a true condition (incremental → re-delivery policy) is required
- ✅ incremental source without {batch} in its location is refused (V02)
- ✅ a secret pasted as credentials_env is refused (V53)
- ✅ unclassified column blocks bronze (classification is ★ GOV)
- ✅ switching the format to CSV makes the declared dialect mandatory
- ✅ an inferred schema blocks until confirmed
- ✅ blank on a none-only field is refused: answer 'none' explicitly
- ✅ rejected-survivor policy (★ SME) is required
- ✅ SQL injection in a rule is caught at the gate
- ✅ 'none' is accepted on a none-only field
- ✅ approve refuses a non-interactive shell (the agent cannot approve)
- ✅ a person in a terminal can approve; approval binds the spec hash
- ✅ any spec change invalidates the approval
- ✅ editing the approval log breaks the hash chain
- ✅ a live run's lease blocks a second run (exit 75 from the CLI)
- ✅ a lease left by a dead process is recovered, then released

## Domain 1 — Module 700 pack sample (content oracle)

- ✅ intake check all reports every skill
- ✅ bronze verification passed
- ✅ bronze landed all 515 rows as received
- ✅ region 'NA' survives as a value (not read as missing)
- ✅ silver BLOCKED until the SME confirms the rule read-back (V07)
- ✅ silver BLOCKED until the SME rules on dates that read differently day-first vs month-first (V12)
- ✅ read-back renders the refund rule with its match count
- ✅ silver verification passed (row law, ties, cast loss, tolerance)
- ✅ silver rows 483 = 515 − 17 − 15 = 483 (pack oracle)
- ✅ dead letters by reason {'null_mrr_amount': 17} == 17 null mrr
- ✅ 11 refund rows kept as valid anomalies
- ✅ gold verification passed (grain, golden values, reconciliation, population)
- ✅ gold_daily_mrr_by_plan 384 rows = 384 (pack oracle)
- ✅ 13 NULL churn days (zero denominator → null) = oracle
- ✅ every daily_mrr value equals the independent pandas oracle (content, not counts)
- ✅ every churn_rate value equals the oracle
- ✅ consumer release refused without an approval
- ✅ serve --check: snapshot hashes, KPI parity, charts, headless health

## Generated code: deterministic rendering + tamper detection

- ✅ rendering twice gives byte-identical files (7 files, V50)
- ✅ a hand-edited generated file is detected (V49)
- ✅ the build refuses to overwrite or run a hand-edited file

## Domain 2 — taxi-style, synthetic data, 3 sources

- ✅ synthetic files generated from bronze's declared schema with a truth ledger
- ✅ retry fired 12× with exponential backoff, then succeeded (V11)
- ✅ bronze verification passed incl. records = landed + parse rejects (V09)
- ✅ edge batch: 1 unparseable record dead-lettered at parse, 9 landed
- ✅ re-run skips every batch by content (V08)
- ✅ ingress gates reject zero-row, missing-column, stale and type-changed files ({'2024-06': 'type_change', '2019-01': 'stale_batch', '2024-04': 'zero_rows', '2024-05': 'missing_required_columns'})
- ✅ rejected files wrote no rows and no checkpoint
- ✅ silver blocked until the SME confirms the read-back
- ✅ read-back shows each rule with its match count
- ✅ injected fault after merge → transaction rolled back, nothing committed (V17)
- ✅ dead-letter tolerance stops the build on the 33%-defect edge batch; earlier batches stay committed
- ✅ silver verification passed for every batch of both sources
- ✅ silver_trips 3684 rows = independent pandas oracle 3684
- ✅ dead-letter reasons {'cast_trip_distance': 3, 'null_key': 34, 'cast_passenger_count': 8, 'null_total_amount': 5, 'cast_pu_zone': 3, 'cast_total_amount': 3, 'null_fare_amount': 2, 'cast_fare_amount': 1, 'cast_pickup_ts': 3, 'domain_payment_type': 48, 'cast_do_zone': 3, 'cast_airport_fee': 3, 'cast_dropoff_ts': 2, 'cast_tip_amount': 3, 'dropoff_before_pickup': 1, 'missing_pu': 1} = oracle
- ✅ structural NULL (green has no airport fee) stays NULL, never imputed
- ✅ 6 missing passenger counts imputed and flagged
- ✅ within-batch correction: the tiebreaker kept total 21.00 over 20.00
- ✅ business flag is_airport_trip computed
- ✅ planted-truth score: every planted defect dead-lettered with the right reason, no false positives (V21)
- ✅ gold verification passed (golden values, reconciliation, population V26)
- ✅ every trips value equals the oracle
- ✅ every revenue value equals the oracle (exact DECIMAL)
- ✅ every tip_rate value equals the oracle
- ✅ re-delivered batch with new content landed as version 2 (V08)
- ✅ gold refuses to build on stale silver
- ✅ fault injected mid-merge of the re-delivery → silver content and ledger unchanged (V17)
- ✅ partition replaced: silver 3666 rows = oracle after re-delivery, no version-1 rows left
- ✅ serve --check passes on the re-delivered data
- ✅ after re-delivery every revenue value equals the oracle

## Merge strategies (append / upsert / CDC / snapshot, late + out-of-order)

- ✅ four merge-strategy entities pass the intake gate
- ✅ row law holds for every strategy and batch
- ✅ upsert: newer version wins, older B v0 is stale ({'B': '1:basic', 'A': '2:pro'})
- ✅ cdc: update applied, delete is a soft delete ({'B': ('Bob', True), 'A': ('Annie', False)})
- ✅ snapshot: B deleted on day 2 then reactivated on day 3, C deleted on day 3 ({'C': ('3.00', True), 'A': ('1.50', False), 'B': ('2.00', False)})
- ✅ append: e2 already present is not duplicated
- ✅ upsert terms: 1 updated, 1 stale, 1 in-batch duplicate
- ✅ append terms: 1 already present
- ✅ late batch with an older version never overwrites newer data ({'B': '1:basic', 'A': '2:pro', 'C': '1:basic'})
- ✅ late CDC update older than the delete does not resurrect the row
- ✅ late older snapshot → entity replayed in date order; Z is deleted by the next snapshot ({'Z': ('9.00', True), 'C': ('3.00', True), 'A': ('1.50', False), 'B': ('2.00', False)})
- ✅ other entities untouched by the replay
- ✅ re-delivery policy 'reject' refuses a changed batch and logs it

## Mutation-kill matrix (V33)

- ✅ mutant d1/region_swap: killed by gold verification — V25-active_events-1 (active_events golden value at event_date=2024-01-01, region=APAC, plan_name=Enterprise); V25-active_events-3 (active_events golden value at
- ✅ mutant d1/date_plus_1: killed by gold verification — V25-active_events-1 (active_events golden value at event_date=2024-01-01, region=APAC, plan_name=Enterprise); V25-active_events-2 (active_events golden value at
- ✅ mutant d1/trialing_in_denominator: killed by gold verification — V25-churn_rate-1 (churn_rate golden value at event_date=2024-02-22); V27-churn_rate (denominator + excluded = silver count per grain key)
- ✅ mutant d1/ambiguous_format_cascade: killed by gold verification — V25-active_events-2 (active_events golden value at event_date=2024-05-06, region=LATAM, plan_name=Enterprise); V25-daily_mrr-2 (daily_mrr golden value at event_
- ✅ mutant d1/ambiguous_format_prefer_first: killed by gold verification — V25-active_events-2 (active_events golden value at event_date=2024-05-06, region=LATAM, plan_name=Enterprise); V25-daily_mrr-2 (daily_mrr golden value at event_
- ✅ mutant d1/flipped_tiebreaker: killed by harness content oracle (V32): silver differs from the executed pack output
- ✅ mutant d1/dropped_filter: killed by gold verification — V27-daily_mrr (metric + excluded = silver sum:mrr_amount per grain key)
- ✅ mutant d1/key_column_swap: killed by silver verification — V14a-events/events/full (tiebreaker separates every real duplicate)
- ✅ mutant d1/money_as_double: killed by gold intake gate — `silver.entities.events.columns.mrr_amount.type` [X, DE] money must be DECIMAL, not floating point (money policy) → e.g. DECIMAL(18,2)
- ✅ mutant d1/null_policy_keep: killed by harness content oracle (V32): silver differs from the executed pack output
- ✅ mutant d1/refund_conflict: killed by silver intake gate — `silver.entities.events.valid_anomalies` [X, SME] rule conflict: 12 rows match valid anomaly 'refund' AND hard reject 'negative' → a row can
- ✅ mutant d1/refund_deleted_as_dirt: killed by silver verification — TOL-events/events/full (dead-lettered share within tolerance)
- ✅ mutant d1/zero_denominator_as_zero: killed by gold verification — V25-churn_rate-1 (churn_rate golden value at event_date=2024-02-22)
- ✅ mutant d1/hand_edited_sql: killed by gold intake gate — BLOCKED — gold/generated/gold_churn_rate.sql was edited by hand; refusing to overwrite. Move the custom logic into custom/ and restore the f
- ✅ mutant d1/upstream_file_corrupted: killed by V42 snapshot manifest hash check (serve --check)
- ✅ mutant d2/wrong_reporting_timezone: killed by gold verification — V25-revenue-1 (revenue golden value at pickup_ts=2024-01-01, pu_borough=Bronx); V25-revenue-2 (revenue golden value at pickup_ts=2024-01-31, pu_borough=EWR); V2
- ✅ mutant d2/join_fan_out: killed by silver verification — V23-trips-pu (reference key of lookup pu is unique in silver_zones)
- ✅ mutant d2/imputed_input_without_population: killed by gold intake gate — `metrics.tip_rate.population` [X, PO] input column(s) tip_amount are imputed or structurally NULL for some rows → state which rows count (e.
- ✅ mutant d2/structural_null_imputed: killed by silver intake gate — `silver.entities.trips.structural_nulls.airport_fee|source=green` [X, SME] the mapping says this source never supplies 'airport_fee', so tre

## Independent-review regressions (C1–C3, H1–H8, M2–M8, L8, drafts, formats)

- ✅ C1: schema answered 'none' is refused — the schema stays mandatory
- ✅ C1: metrics answered 'none' is refused
- ✅ a value the assistant chose (--drafted) blocks the gate
- ✅ ★ answers can never be drafted
- ✅ after the person confirms the draft, the gate passes
- ✅ H1: an assistant listed under another id or name is refused
- ✅ C2: a header containing SQL is quoted, not executed (no side-effect file)
- ✅ C2: the odd header landed as an ordinary column name (drift logged)
- ✅ C3: a batch id with a quote is rejected (bad_batch_id)
- ✅ M6: 3.149 → DECIMAL(10,2) and 3.7 → INTEGER are cast loss, not silent rounding ({'cast_amount': 1, 'cast_qty': 1})
- ✅ H5: a corrected re-delivery (same version) is applied under upsert — incremental = rebuild
- ✅ H6: reject_key withdraws K when its newest version is rejected ({'L': False, 'K': True})
- ✅ H7: rows with an unknown or NULL op code are dead-lettered unknown_op
- ✅ H8: a pii value is hashed in the dead-letter row (never stored in clear)
- ✅ CDC delete applied; masked email is a 32-char hash
- ✅ M2: 31-01-2024 is applied before 01-02-2024 (date order, not text) ({'B': True, 'A': False})
- ✅ M3/M4: cp1252 file with CRLF and blank lines lands correctly (['Montréal', 'Zürich'])
- ✅ M5: Excel source with a padded header (' id ') lands its values
- ✅ JSON-lines source lands
- ✅ HTTP source lands with an explicit --batch
- ✅ L8: clock-dependent functions are refused in rules (determinism)
- ✅ M7: a distinct-count metric reconciles to the distinct count of non-excluded rows
- ✅ M8: golden value 0 for a key with no qualifying rows passes
- ✅ H2/H4: RLS answer refused; serve --check blocked by its gate
- ✅ H3: a title containing ''' and code is a string, never executed

## Intake workbook (analyse → draft → Excel → import, all-or-nothing)

- ✅ W1 analyze groups batch_01/batch_02 files into one source with a {batch} location
- ✅ W1 analysis output carries counts only — no data value appears
- ✅ W1 analyze starts the draft (config/intake/draft.yaml or intake/draft.yaml) with the proposed sources
- ✅ W2 one tab per kind of question, every layer (16 tabs)
- ✅ W2 project, governance, bronze, silver, gold and serve questions all carry a default
- ✅ W2 analysis defaults: money → DECIMAL, a ragged code (zip) → text
- ✅ W2 classification defaults from column names (email → pii)
- ✅ W2 answer cells with a fixed list carry a drop-down
- ✅ W2 golden values have no default (blank rows per KPI)
- ✅ W2 egress: the workbook holds no data value (counts and names only)
- ✅ W3 a refused import records nothing (specs and provenance unchanged)
- ✅ W3 an -issues.xlsx copy is written with an Issues tab
- ✅ W3 each problem names its tab, cell and fix (schema NA, missing GOV answerer)
- ✅ W3 the problem cell is marked red with a note
- ✅ W4 bad drop-down value, bad SQL, assistant as a person, malformed golden key, unknown grain column, governed + pending golden → each refused on its cell (6/6)
- ✅ W4 --dry-run checks and records nothing
- ✅ W5 a kept ★ default is recorded as the GOV owner's answer, with its cell and default_kept: yes
- ✅ W5 a changed default is recorded with default_kept: no
- ✅ W5 the imported workbook is kept as received in the workbook archive
- ✅ W5 dwh status lists the ★ decisions taken by keeping a default
- ✅ W5 KPIs without golden values are pending in the fast profile (build may go on, release blocked)
- ✅ W5 project, bronze, gold and serve gates pass straight from the workbook
- ✅ W6 regenerating after the bronze load adds the After first load tab
- ✅ W6 the rule read-back shows match counts and has no default
- ✅ W6 importing without confirming the read-back is refused
- ✅ W6 after the owner confirms the read-back in the workbook, silver gate B passes
- ✅ W6 regenerating the workbook keeps a confirmed read-back confirmed (and shows it)
- ✅ W7 customer_id hashed in both entities, the lookup still matches every order (6 kept, 0 missing)
- ✅ W8 a KPI the owner removed is not brought back by the draft on regeneration
- ✅ W8 read-back answers given after the first load survive re-importing an older workbook
- ✅ W9 an older pinned kernel is not replaced silently
- ✅ W9 --upgrade replaces the kernel and re-pins the manifest (same key algorithm)

## Layout v2 + pipelines repository (migrate, shared kernel, one file per spec)

- ✅ L1 skipped: the suite runs on layout v2 (projects start on v2, nothing to migrate)
- ✅ L2 the repository's dwh-init (no kernel/ of its own) installs a pipeline
- ✅ L2 inside a repository nothing is copied and the pipeline starts on layout v2
- ✅ L2 the wrapper runs the shared kernel in framework/
- ✅ L2 the pipeline has the full v2 folder tree (specs / decisions / generated / reports per layer)
- ✅ L2 answers land in the v2 files (project/people.yaml, project/decisions/provenance.yaml)
- ✅ L2 a kernel version the pipeline does not pin is refused
- ✅ L2 doctor still runs, so the pin can be fixed
- ✅ L3 each metric is written to its own file
- ✅ L3 removing a metric from the spec removes its file
- ✅ L3 the same metric name in two files is refused with a clear message
- ✅ L3 the CLI refuses it too (no traceback)

## Determinism (V43)

- ✅ 1 thread vs 4 threads → identical content hashes for every silver and gold table (V43)

## python -O (V40)

- ✅ domain 1 passes under python -O (18 checks): no assert-based checks (V40)

## Not covered by this run (stated, not hidden)

- **Windows** (cmd / PowerShell / Git Bash): the wrappers and doctor target it, but this suite ran on Linux only. Run `validate.py` on a Windows machine before relying on it there.
- **Real NYC TLC files**: domain 2 uses synthetic data shaped like TLC; the real-file run is the next step.
- **Scale**: largest batch ~1.9k rows; DuckDB handles the 500 MB / 50 MB targets, but timings were not measured.
- **Out of v1 scope** (see dwh-init/references/limits.md): row-level security, regulated-mode controls, fiscal calendars, custom steps, cloud connectors.
