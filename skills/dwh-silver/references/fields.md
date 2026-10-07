# Silver fields — worked examples and plain-language explanations

## Single source (SaaS events)
```yaml
sources: [events]
columns:
  event_id:   {type: VARCHAR}
  account_id: {type: INTEGER}
  region:     {type: VARCHAR}
  event_date: {type: DATE, formats: ["%Y-%m-%d", "%d/%m/%Y", "%b %d %Y"]}
  mrr_amount: {type: "DECIMAL(18,2)"}
  status:     {type: VARCHAR}
natural_key: [event_id]
tiebreaker: ["account_id DESC"]
merge: {strategy: partition_replace, partition_column: NA}
```
SME: `rejected_survivor_policy: keep_last_good`; `null_policy: {event_id: drop, mrr_amount: drop, …: keep}`;
`valid_anomalies: {refund: {predicate: "mrr_amount < 0", reason: "negative MRR is a refund"}}`;
`hard_rejects: none`. PO: `dead_letter_tolerance_pct: 5`, `tolerance_source: real`.

## Two sources into one entity (yellow CSV + green Parquet)
```yaml
sources: [yellow, green]
mapping:
  yellow: {vendor_id: VendorID, pickup_ts: tpep_pickup_datetime, airport_fee: airport_fee, …}
  green:  {vendor_id: VendorID, pickup_ts: lpep_pickup_datetime, airport_fee: "NULL", …}
lookups:
  pu: {reference: zones, on: {pu_zone: location_id}, columns: [borough]}   # → column pu_borough
```
`airport_fee: NULL` for green means green never supplies it. The gate then asks the SME:
`structural_nulls."airport_fee|source=green"` → **structural** (stays NULL, never imputed or
dropped). Answering *defect* while also imputing or dropping is refused — it would fabricate or
delete every green value. Metrics reading imputed or structurally-null columns must state their
population (dwh-gold).

## How to explain the ★ questions to a business owner
- **Rejected-survivor policy**: "If the newest version of a record breaks a rule, should we keep
  the most recent version that was fine (keep_last_good), or drop the record entirely until it's
  fixed (reject_key)?"
- **Valid anomalies**: "Which rows look wrong but are real? For example negative amounts that are
  refunds. Those must never be deleted as dirt." Answer `none` if there are none.
- **Null policy**: per column, "if this is missing: drop the row (it goes to the dead-letter file
  with a reason), fill a value (and flag it), or keep it empty?"
- **Structural null**: "This column is empty for every row from <source>/<subset>. Is that because
  it is never measured there (structural), or is data missing (defect)?"
- **Date ambiguity**: "N values like 03/04/2024 read as different dates under two formats. Use the
  first listed format, or reject those rows?"
- **Masking** (governance): "For <column> (classified pii): hash it (joinable, not readable), drop
  it, or keep it as is?"

## CDC feed
```yaml
merge: {strategy: cdc_apply, op_column: op, op_codes: {insert: I, update: U, delete: D}, sequence_column: seq}
tiebreaker: ["seq DESC"]
```
Delete records may have empty business columns: null policies, allowed values, hard rejects and
lookups are not applied to them (unparseable values still are). A row whose op is NULL or not one
of the declared codes is dead-lettered `unknown_op`.
