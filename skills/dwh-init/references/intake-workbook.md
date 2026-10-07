# The intake workbook

Every question of every layer, in one Excel file, answered before anything builds.

```
./dwh intake analyze data/raw     # sources + counts-only measurements; starts the draft
(edit the draft)                  # config/intake/draft.yaml (v1) or intake/draft.yaml (v2)
./dwh intake workbook             # intake/<project>-intake.xlsx, every answer pre-filled
… the user fills it in and sends it back …
./dwh intake import <file.xlsx>   # all-or-nothing: records it, or writes <file>-issues.xlsx
./dwh intake import <file> --dry-run   # check only, record nothing
```

## Where each default comes from

Lowest to highest priority:

1. the catalogue's documented default (e.g. dead-letter tolerance 5 %, retries 3);
2. the analysis of the sample files — detected types (money → DECIMAL, codes with ragged lengths →
   text), candidate keys (a unique id column, or a unique pair), empty counts → null policy,
   date formats that parse, columns never filled, classification hints from column names;
3. your draft (`config/intake/draft.yaml`, or `intake/draft.yaml` in layout v2);
4. answers already recorded by a person — shown as the current answer when the workbook is
   regenerated. For collections (sources, columns, rules, lookups, KPIs, tiles, charts) the
   recorded set wins: an item the owner removed is not brought back by the draft.

★ decisions get a default too. Keeping it in the returned workbook records it as that owner's
answer (`default_kept: yes` in provenance) and `./dwh status` lists such decisions. Two answers
never get a default because a default would make the check prove itself: **golden values** and
the **rule read-back confirmation**.

## The draft file

Same shape as the specs (`people`, `project`, `policies`, `sources`, `silver.entities`,
`metrics`, `serve`) plus `notes:`. Give only what you have a reason for; the rest is filled in.

```yaml
people:
  dana: {name: Dana Rao, roles: [DE, PO, SME, GOV]}     # the requester, if they are the only person
policies:
  timezone: {reporting: Europe/Berlin}                  # when the data or request makes it clear
sources:
  trips:                                                # short names; drop files that are not sources
    location: data/raw/trips_{batch}.csv
    schema:
      columns:                                          # only overrides: the analysis fills the rest
        trip_id: {key: "yes"}
        fare: {type: "DECIMAL(10,2)"}
        rider_email: {classification: pii}
  zones:
    location: data/raw/zones.csv
    load_type: full_refresh
silver:
  entities:
    trips:
      sources: [trips]
      mapping: {trips: {zone_code: "lpad(zone_code, 3, '0')"}}   # expressions only; plain columns copy
      hard_rejects:
        dropoff_before_pickup: {predicate: dropoff_ts < pickup_ts, reason: dropoff_before_pickup}
        tiny_fare: {predicate: fare < 0.01, reason: tiny_fare, decision: skip}  # proposed but off
      valid_anomalies:
        refund: {predicate: fare < 0, reason: refunds carry negative amounts}
      lookups:
        zone: {reference: zones, "on": {zone_code: zone_code}, columns: [borough], missing: keep_null}
metrics:
  revenue:
    entity: trips
    plain_definition: Fares charged per pickup day and borough.
    metric_type: sum
    numerator: {measure: "sum:fare", filter: none}
    grain: [pickup_ts, zone_borough]                   # lookup columns are <lookup>_<column>
    time_grain: day
    date_basis: pickup_ts
    unit: "currency:EUR"
serve:
  title: Trips — development
  kpis: {rev: {metric: revenue, label: Revenue}}
  charts: {rev_trend: {type: line, metric: revenue, x: pickup_ts, color: NA, title: Revenue per day}}
notes:
  silver.entities.trips.hard_rejects.dropoff_before_pickup: "data README: 0.3 % of trips end before they start"
  sources.zones.load_type: "static lookup shipped once"
```

What to propose, and where it usually comes from:

| Proposal | Source of the idea |
|---|---|
| source names, which files belong together, static lookups (`full_refresh`, fixed location) | file names, data docs |
| keys the analysis could not find, composite keys | data docs, column names |
| types the first batch hides (e.g. decimals that arrive later as `1.0`) | data docs |
| expressions (zero-padding codes, trimming) | analysis length ranges, data docs |
| impossible rows and real-but-odd rows, with a note giving the documented count | data docs / known issues |
| lookups needed by the KPIs' grain (a KPI can only group by its entity's columns and lookup columns) | the request |
| KPI cards, tiles, charts, filters | the request |
| reporting time zone | where the business is |

A rule's `decision: skip` shows it in the workbook as proposed-but-off. Classification and masking
defaults come from column names (ids of people, contacts, postal codes, coordinates → pii, hashed;
free text → sensitive, dropped); override them in the draft when the data says otherwise (e.g. a
business's address is not a person's) and say why in a note. Lookups compare hashed keys correctly
when both entities hash the key, so hashing a join key is safe.

Never put data values you have not been allowed to see into the draft. Values the request or the
documentation states (status codes, category names) are fine.

## Tabs

| Tab | One row per | Owner |
|---|---|---|
| Start here | — instructions, colour key, counts per tab | — |
| People | person (id, name, email, roles) | DE |
| Project | question: name, profile, builder, **who answered each role** | DE |
| Governance ★ | question: compliance, egress, row security | GOV |
| Reporting policy ★ | question: time zone, calendar, week start, money scale | PO |
| Sources | source: connector, location, format, load type, re-delivery, drift, freshness, volume, CSV/Excel dialect | DE |
| Schema | source column: type, required, key, allowed values (+ counts from the sample) | DE |
| Classification ★ | source column: classification, handling in silver (hash / drop / keep) | GOV |
| Silver model | source column: entity, silver column, expression, silver type, date formats, time zone, or "not carried" reason | DE |
| Entities | entity: record key, tiebreaker, merge strategy (+ version/partition/CDC columns), survivor policy ★, tolerance | DE · SME · PO |
| Data quality | check: impossible row, real but unusual ★, empty values (drop / keep / impute:<v>), never filled ★ | SME |
| Lookups & flags | lookup or flag | DE · SME |
| KPIs ★ | KPI **column**; rows are the metric-card fields | PO |
| Golden values ★ | hand-computed value: KPI, key (`col=value; col=value`), value | PO |
| Dashboard | question: title, audience, clock, filters | PO |
| Dashboard visuals | tile or chart | PO |
| After first load ★ | only after bronze: ambiguous dates, rule read-back (no default), never-filled columns | SME |

Tokens in any answer cell: `NA` = not applicable (optional answers only), `none` = there are none,
`pending` = the owner decides later (only on ★ answers that may wait, fast profile; blocks consumer
release). A KPI with no golden values is pending in the fast profile and blocking in governed.

Several people can share one workbook — each fills their tabs; the Project tab names who answered
for each role, and every answer is recorded in that person's name. The assistant can never be one
of them.

## Import

1. Parse every tab (rows identified by their key columns, never by position; example rows and
   empty rows ignored; header text must not be changed).
2. Apply to a scratch copy of the project and run the gates of project, bronze, silver (gate A),
   gold and serve there.
3. Any problem → nothing recorded; `<file>-issues.xlsx` written (Issues tab + red cells with notes).
4. Clean → specs written, provenance per answer (`by`, `source: workbook`, file, sha256, cell,
   `default_kept`), the workbook copied to the archive (`config/intake/workbooks/`, v2: `intake/workbooks/`), audit entry.

Answers given after the first load (After first load tab) survive a later import of a workbook
generated before them.
