# Olist Brazilian E-commerce: raw data split into 25 chronological batches

**Source:** official Olist repo, `github.com/olist/work-at-olist-data` (`datasets/`). Real anonymised marketplace data from Sep 2016 to Oct 2018. Licence: CC BY-NC-SA 4.0.
**Size:** 9 tables (entities), 52 attributes, 1,550,931 data rows, ~120 MB raw CSV.
**Fidelity:** every row is copied **byte-for-byte** from the source files. Quoting, line endings, embedded newlines and dropped leading zeros are all left as they were. Each part file repeats the original header. Verified: every source record appears in exactly one batch.

## Entities

| Table | Rows | Cols | Key | Notes |
|---|---|---|---|---|
| olist_orders_dataset | 99,441 | 8 | order_id | 5 lifecycle timestamps + status |
| olist_order_items_dataset | 112,650 | 7 | order_id + order_item_id | FK to orders, products, sellers |
| olist_order_payments_dataset | 103,886 | 5 | order_id + payment_sequential | |
| olist_order_reviews_dataset | 99,224 | 7 | review_id (NOT unique) | free-text Portuguese |
| olist_customers_dataset | 99,441 | 5 | customer_id (per order) / customer_unique_id (per person) | SCD-style |
| olist_products_dataset | 32,951 | 9 | product_id | |
| olist_sellers_dataset | 3,095 | 4 | seller_id | |
| olist_geolocation_dataset | 1,000,163 | 5 | none (zip prefix repeats) | |
| product_category_name_translation | 71 | 2 | product_category_name | PT to EN lookup |

## Real data-quality issues (measured, not injected)

**Formatting / types**
- Zip prefix formatting is inconsistent: geolocation stores it quoted as text (`"01037"`); customers/sellers store it unquoted, so **23,995 customer zips are 4 digits** (leading zero lost).
- City names in geolocation: 8,011 raw spellings collapse to 5,966 once accents and case are normalised. Examples: `são paulo`, `sao paulo`, `sãopaulo`, `sa£o paulo` (mojibake), `embu-guacu`, `embu guaçu`, `guarulhos-sp`.
- Seller city holds junk: `sao paulo / sao paulo`, `lages - sc`, `sbc/sp`, `novo hamburgo, rio grande do sul, brasil`, and a phone-like number `4482255`.
- Misspelled column names: `product_name_lenght`, `product_description_lenght`.
- Numeric columns stored as decimals (`product_photos_qty`); reviews use date-only values padded with `00:00:00` next to full timestamps.
- **3,852 review comments contain embedded newlines** inside quoted fields. Naive line-based readers will break.

**Data quality**
- Geolocation: **261,831 exact duplicate rows**; **42 points outside Brazil's bounding box**.
- Reviews: **814 duplicate review_id**s; 551 orders with more than one review.
- Orders: 160 missing `order_approved_at`, 1,783 missing carrier date, 2,965 missing delivery date. **8 orders have status `delivered` but no delivery date.** 1,359 orders were handed to the carrier *before* approval.
- 775 orders have no order items. 4,019 customer zips have no geolocation match.
- Products: 610 have no category (and their name/description/photo fields are null too); 2 have no dimensions. 2 categories are missing from the translation table (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`).
- Payments: 9 with value 0, 2 with 0 installments, 3 with type `not_defined`.
- 99,441 customer_ids map to only 96,096 real people (`customer_unique_id`). Useful for identity resolution and SCD2.

## How the 25 batches were cut

The source orders file is **not** stored chronologically (rows are shuffled), so batches are cut by **event time**, not file position.

| Table | Batch rule |
|---|---|
| orders | sorted by `order_purchase_timestamp`, 25 equal-count slices (3,978 each; last has 3,969). See `batch_manifest.csv` for time windows. |
| order_items, payments | same batch as their parent order |
| customers | same batch as their order (customer_id is 1:1 with order) |
| reviews | by their own `review_creation_date` against the same windows. Reviews often land 1 to 3 batches after their order, which makes them **late-arriving facts**. |
| products, sellers | batch of first sale (first appearance in order_items) |
| geolocation | no timestamp, so 25 contiguous chunks in original file order (~40k rows each) |
| category translation | static lookup, so batch_01 only |

Within each file, rows are in event-time order.

## Things this set lets you test
Bronze schema/type gates · zip-code text normalisation · accent/mojibake city cleansing · dedup with tie-breakers (geolocation, review_id) · quarantine of impossible rows (carrier-before-approval, delivered-without-date) · orphan FK handling (items without order, zips without geo) · late-arriving facts (reviews) · late dimension members (products/sellers appear only when first sold) · SCD2 on customers via `customer_unique_id` · incremental/CDC merge across 25 batch drops.

**Caveat on CDC:** the orders file is a final snapshot, so each order appears once with all its timestamps filled. There are no natural status-change updates across batches. For true update/delete CDC you would need to simulate change events, for example re-emitting orders as status moves from `created` to `approved` to `shipped` to `delivered`.
