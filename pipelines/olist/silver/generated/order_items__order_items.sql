-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=3e436bcf4c03aedb body_sha=b1d145cc66608fd7dde4c63d67f80e7bc55ca9e5de74571f2a7f508b652fc8cb
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step typed
CREATE OR REPLACE TEMP TABLE _typed AS
WITH b AS (SELECT * FROM "bronze_order_items" WHERE "_batch_id" = (SELECT batch_id FROM _scope) AND "_batch_version" = (SELECT batch_version FROM _scope)),
t AS (SELECT
  "_src",
  "_batch_id",
  "_batch_version",
  "_source_file",
  "_row_number",
  "order_id" AS "_raw__order_id",
  trim("order_id") AS "order_id",
  FALSE AS "_amb__order_id",
  FALSE AS "_dom__order_id",
  "order_item_id" AS "_raw__order_item_id",
  CASE WHEN regexp_matches(trim("order_item_id"), '^[+-]?[0-9]+$') THEN TRY_CAST(trim("order_item_id") AS BIGINT) END AS "order_item_id",
  FALSE AS "_amb__order_item_id",
  FALSE AS "_dom__order_item_id",
  "product_id" AS "_raw__product_id",
  "product_id" AS "product_id",
  FALSE AS "_amb__product_id",
  FALSE AS "_dom__product_id",
  "seller_id" AS "_raw__seller_id",
  "seller_id" AS "seller_id",
  FALSE AS "_amb__seller_id",
  FALSE AS "_dom__seller_id",
  "shipping_limit_date" AS "_raw__shipping_limit_date",
  TRY_STRPTIME("shipping_limit_date", '%Y-%m-%d %H:%M:%S') AS "shipping_limit_date",
  FALSE AS "_amb__shipping_limit_date",
  FALSE AS "_dom__shipping_limit_date",
  "price" AS "_raw__price",
  CASE WHEN TRY_CAST(trim("price") AS DOUBLE) = TRY_CAST(TRY_CAST(trim("price") AS DECIMAL(18,2)) AS DOUBLE) THEN TRY_CAST(trim("price") AS DECIMAL(18,2)) END AS "price",
  FALSE AS "_amb__price",
  FALSE AS "_dom__price",
  "freight_value" AS "_raw__freight_value",
  CASE WHEN TRY_CAST(trim("freight_value") AS DOUBLE) = TRY_CAST(TRY_CAST(trim("freight_value") AS DECIMAL(18,2)) AS DOUBLE) THEN TRY_CAST(trim("freight_value") AS DECIMAL(18,2)) END AS "freight_value",
  FALSE AS "_amb__freight_value",
  FALSE AS "_dom__freight_value"
FROM b)
SELECT t.*, md5(to_json(struct_pack(k0 := trim("order_id"), k1 := CAST("order_item_id" AS VARCHAR)))) AS "_sk", md5(to_json(struct_pack("order_id" := "order_id", "order_item_id" := "order_item_id", "product_id" := "product_id", "seller_id" := "seller_id", "shipping_limit_date" := "shipping_limit_date", "price" := "price", "freight_value" := "freight_value"))) AS "_content", ("order_id" IS NOT NULL AND "order_item_id" IS NOT NULL) AS "_key_ok", FALSE AS "_is_del"
FROM t;

-- @step judged
CREATE OR REPLACE TEMP TABLE _judged AS
SELECT t.*, "lk_ord"."ord_order_purchase_timestamp" AS "ord_order_purchase_timestamp", "lk_ord"."ord_order_status" AS "ord_order_status", "lk_ord"."_hit" AS "_hit__ord",
  CASE
    WHEN t."_raw__order_id" IS NOT NULL AND t."order_id" IS NULL THEN 'cast_order_id'
    WHEN t."_raw__order_item_id" IS NOT NULL AND t."order_item_id" IS NULL THEN 'cast_order_item_id'
    WHEN NOT t."_key_ok" THEN 'null_key'
    WHEN t."_raw__product_id" IS NOT NULL AND t."product_id" IS NULL THEN 'cast_product_id'
    WHEN t."_raw__seller_id" IS NOT NULL AND t."seller_id" IS NULL THEN 'cast_seller_id'
    WHEN t."_raw__shipping_limit_date" IS NOT NULL AND t."shipping_limit_date" IS NULL THEN 'cast_shipping_limit_date'
    WHEN t."_raw__price" IS NOT NULL AND t."price" IS NULL THEN 'cast_price'
    WHEN t."_raw__freight_value" IS NOT NULL AND t."freight_value" IS NULL THEN 'cast_freight_value'
    WHEN NOT t."_is_del" AND t."order_id" IS NOT NULL AND lk_ord."_hit" IS NULL THEN 'missing_ord'
  END AS "_reason",
  NULL AS "_anomaly",
  NULL AS "_hard"
FROM _typed t
LEFT JOIN (SELECT "order_id" AS "_k_order_id", "order_purchase_timestamp" AS "ord_order_purchase_timestamp", "order_status" AS "ord_order_status", TRUE AS "_hit" FROM "silver_orders" WHERE NOT "_is_deleted") "lk_ord" ON t."order_id" = "lk_ord"."_k_order_id";

-- @step outcome
CREATE OR REPLACE TEMP TABLE _outcome AS
WITH r AS (
  SELECT *,
    CASE WHEN "_key_ok" THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_sk" ORDER BY "shipping_limit_date" DESC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_all",
    CASE WHEN "_key_ok" AND "_reason" IS NULL
         THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_reason" IS NULL, "_sk" ORDER BY "shipping_limit_date" DESC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_good"
  FROM _judged),
k AS (
  SELECT "_sk", bool_or("_reason" IS NULL) AS any_good,
         bool_or("_rank_all" = 1 AND "_reason" IS NULL) AS newest_good
  FROM r WHERE "_key_ok" GROUP BY "_sk")
SELECT r.*,
  CASE WHEN NOT r."_key_ok" OR r."_reason" IS NOT NULL THEN 'dead_letter'
       WHEN NOT k.any_good THEN 'dead_letter'
       WHEN r."_rank_good" = 1 THEN 'survivor'
       ELSE 'duplicate' END AS "_outcome",
  CASE WHEN r."_reason" IS NOT NULL THEN r."_reason"
       WHEN NOT k.any_good THEN 'key_rejected' END AS "_dl_reason"
FROM r LEFT JOIN k ON r."_sk" = k."_sk" AND r."_key_ok";

-- @step final
CREATE OR REPLACE TEMP TABLE _final AS
WITH i AS (SELECT "order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value", "ord_order_purchase_timestamp", "ord_order_status", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM _outcome WHERE "_outcome" = 'survivor'),
o AS (SELECT "order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value", "ord_order_purchase_timestamp", "ord_order_status", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM i)
SELECT "order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value", "ord_order_purchase_timestamp", "ord_order_status", "_sk", md5(to_json(struct_pack("order_id" := "order_id", "order_item_id" := "order_item_id", "product_id" := "product_id", "seller_id" := "seller_id", "shipping_limit_date" := "shipping_limit_date", "price" := "price", "freight_value" := "freight_value", "ord_order_purchase_timestamp" := "ord_order_purchase_timestamp", "ord_order_status" := "ord_order_status"))) AS "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", dwh_now() AS "_loaded_at", FALSE AS "_is_deleted"
FROM o
ORDER BY "_sk";

-- @step deadletter
DELETE FROM silver_dead_letter WHERE entity = 'order_items' AND src = (SELECT src FROM _scope) AND batch_id = (SELECT batch_id FROM _scope);
INSERT INTO silver_dead_letter SELECT 'order_items', o."_src", o."_batch_id", o."_batch_version", o."_source_file", o."_row_number", o."_dl_reason", o."_anomaly", dwh_now(), json_object('order_id', "__raw"."order_id", 'order_item_id', "__raw"."order_item_id", 'product_id', "__raw"."product_id", 'seller_id', "__raw"."seller_id", 'shipping_limit_date', "__raw"."shipping_limit_date", 'price', "__raw"."price", 'freight_value', "__raw"."freight_value")
FROM _outcome o JOIN "bronze_order_items" "__raw" ON "__raw"."_batch_id" = o."_batch_id" AND "__raw"."_batch_version" = o."_batch_version" AND "__raw"."_row_number" = o."_row_number"
WHERE o."_outcome" = 'dead_letter';
