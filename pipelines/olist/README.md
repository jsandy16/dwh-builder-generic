# olist — Brazilian e-commerce warehouse

Olist marketplace orders (public Brazilian e-commerce dataset), built with the dwh skills on the
shared kernel (`dwh_core` 1.2.0, layout v2). Development uses batches 01 and 02.

## Status

| Step | State |
|---|---|
| Request (`requirements/request.md`) | done |
| Intake workbook answered and imported | done — 2026-10-07 (`intake/workbooks/`) |
| Bronze loaded | batches 01–02 (17 files, see `data/manifest.yaml`) |
| After-first-load round (read-backs confirmed) | done |
| Silver | PASS — 216 checks (`silver/reports/silver-verify.md`) |
| Gold | PASS — 48 checks, 18 golden values match (`gold/reports/gold-verify.md`) |
| Dashboard check | PASS (`serve/reports/serve-check.md`) |
| Approval and consumer release | **waiting for a person**: `./dwh approve --by sandeep`, then `./dwh publish --target consumers` |

7,931 orders, purchased 2016-09-04 → 2017-04-30. Profile: `fast` (one person holds every role).

## KPIs (`gold/specs/metrics/`)

| KPI | Meaning | Grain |
|---|---|---|
| `orders_placed` | orders purchased | day × customer state |
| `gmv` | item price of orders, canceled/unavailable excluded | day |
| `avg_order_value` | GMV ÷ orders | day |
| `on_time_delivery_rate` | delivered by the estimated date ÷ delivered | day |
| `avg_review_score` | review points ÷ reviews | review day |
| `cancellation_rate` | canceled ÷ all orders, × 100 | day |

Golden values were checked independently from the raw files: `gold/checks/golden_independent.py`.

## Owners

| Role | Person |
|---|---|
| DE, PO, SME, GOV | sandeep |

## Decisions worth knowing

- [`governance/adr/0001-geolocation-append-reject.md`](governance/adr/0001-geolocation-append-reject.md) —
  geolocation has no key, so batches are appended and a re-delivered batch is rejected.
- [`governance/adr/0002-layout-v2.md`](governance/adr/0002-layout-v2.md) — moved into this repository
  (layout v2, kernel 1.1.0 → 1.2.0); every spec and answer read back identical.

## Rebuild from a fresh clone

The raw files and the warehouse are not in git. To rebuild:

1. Put batch_01 and batch_02 in `data/raw/` and check them: `python tools/data_manifest.py olist --check`.
2. Restore `.dwh/salt` from your backup if you want the same hashed ids as before (otherwise a new
   salt is created and hashed ids differ; the KPIs do not change).
3. `python tools/doctor.py olist` (writes `./dwh`), then `./dwh build bronze`, `./dwh build silver`, `./dwh build gold`,
   `./dwh publish`, `./dwh serve`.
