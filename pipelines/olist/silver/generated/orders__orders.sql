-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=27c8828089334a08 body_sha=6106d4d479e384b5e1d1dc03157e423b9d900cac02caf39d757fd274893325c9
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step typed
CREATE OR REPLACE TEMP TABLE _typed AS
WITH b AS (SELECT * FROM "bronze_orders" WHERE "_batch_id" = (SELECT batch_id FROM _scope) AND "_batch_version" = (SELECT batch_version FROM _scope)),
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
  "customer_id" AS "_raw__customer_id",
  "customer_id" AS "customer_id",
  FALSE AS "_amb__customer_id",
  FALSE AS "_dom__customer_id",
  "order_status" AS "_raw__order_status",
  "order_status" AS "order_status",
  FALSE AS "_amb__order_status",
  FALSE AS "_dom__order_status",
  "order_purchase_timestamp" AS "_raw__order_purchase_timestamp",
  TRY_STRPTIME("order_purchase_timestamp", '%Y-%m-%d %H:%M:%S') AS "order_purchase_timestamp",
  FALSE AS "_amb__order_purchase_timestamp",
  FALSE AS "_dom__order_purchase_timestamp",
  "order_approved_at" AS "_raw__order_approved_at",
  TRY_STRPTIME("order_approved_at", '%Y-%m-%d %H:%M:%S') AS "order_approved_at",
  FALSE AS "_amb__order_approved_at",
  FALSE AS "_dom__order_approved_at",
  "order_delivered_carrier_date" AS "_raw__order_delivered_carrier_date",
  TRY_STRPTIME("order_delivered_carrier_date", '%Y-%m-%d %H:%M:%S') AS "order_delivered_carrier_date",
  FALSE AS "_amb__order_delivered_carrier_date",
  FALSE AS "_dom__order_delivered_carrier_date",
  "order_delivered_customer_date" AS "_raw__order_delivered_customer_date",
  TRY_STRPTIME("order_delivered_customer_date", '%Y-%m-%d %H:%M:%S') AS "order_delivered_customer_date",
  FALSE AS "_amb__order_delivered_customer_date",
  FALSE AS "_dom__order_delivered_customer_date",
  "order_estimated_delivery_date" AS "_raw__order_estimated_delivery_date",
  TRY_STRPTIME("order_estimated_delivery_date", '%Y-%m-%d %H:%M:%S') AS "order_estimated_delivery_date",
  FALSE AS "_amb__order_estimated_delivery_date",
  FALSE AS "_dom__order_estimated_delivery_date"
FROM b)
SELECT t.*, md5(to_json(struct_pack(k0 := trim("order_id")))) AS "_sk", md5(to_json(struct_pack("order_id" := "order_id", "customer_id" := "customer_id", "order_status" := "order_status", "order_purchase_timestamp" := "order_purchase_timestamp", "order_approved_at" := "order_approved_at", "order_delivered_carrier_date" := "order_delivered_carrier_date", "order_delivered_customer_date" := "order_delivered_customer_date", "order_estimated_delivery_date" := "order_estimated_delivery_date"))) AS "_content", ("order_id" IS NOT NULL) AS "_key_ok", FALSE AS "_is_del"
FROM t;

-- @step judged
CREATE OR REPLACE TEMP TABLE _judged AS
SELECT t.*, "lk_cust"."cust_customer_state" AS "cust_customer_state", "lk_cust"."_hit" AS "_hit__cust",
  CASE
    WHEN t."_raw__order_id" IS NOT NULL AND t."order_id" IS NULL THEN 'cast_order_id'
    WHEN NOT t."_key_ok" THEN 'null_key'
    WHEN t."_raw__customer_id" IS NOT NULL AND t."customer_id" IS NULL THEN 'cast_customer_id'
    WHEN t."_raw__order_status" IS NOT NULL AND t."order_status" IS NULL THEN 'cast_order_status'
    WHEN t."_raw__order_purchase_timestamp" IS NOT NULL AND t."order_purchase_timestamp" IS NULL THEN 'cast_order_purchase_timestamp'
    WHEN t."_raw__order_approved_at" IS NOT NULL AND t."order_approved_at" IS NULL THEN 'cast_order_approved_at'
    WHEN t."_raw__order_delivered_carrier_date" IS NOT NULL AND t."order_delivered_carrier_date" IS NULL THEN 'cast_order_delivered_carrier_date'
    WHEN t."_raw__order_delivered_customer_date" IS NOT NULL AND t."order_delivered_customer_date" IS NULL THEN 'cast_order_delivered_customer_date'
    WHEN t."_raw__order_estimated_delivery_date" IS NOT NULL AND t."order_estimated_delivery_date" IS NULL THEN 'cast_order_estimated_delivery_date'
    WHEN NOT t."_is_del" AND COALESCE((order_delivered_carrier_date < order_approved_at), FALSE) THEN 'carrier_before_approval'
    WHEN NOT t."_is_del" AND COALESCE((order_status = 'delivered' AND order_delivered_customer_date IS NULL), FALSE) THEN 'delivered_without_date'
  END AS "_reason",
  NULL AS "_anomaly",
  CASE WHEN COALESCE((order_delivered_carrier_date < order_approved_at), FALSE) THEN 'carrier_before_approval' WHEN COALESCE((order_status = 'delivered' AND order_delivered_customer_date IS NULL), FALSE) THEN 'delivered_without_date' END AS "_hard"
FROM _typed t
LEFT JOIN (SELECT "customer_id" AS "_k_customer_id", "customer_state" AS "cust_customer_state", TRUE AS "_hit" FROM "silver_customers" WHERE NOT "_is_deleted") "lk_cust" ON md5(dwh_salt() || CAST(t."customer_id" AS VARCHAR)) = "lk_cust"."_k_customer_id";

-- @step outcome
CREATE OR REPLACE TEMP TABLE _outcome AS
WITH r AS (
  SELECT *,
    CASE WHEN "_key_ok" THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_sk" ORDER BY "order_purchase_timestamp" DESC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_all",
    CASE WHEN "_key_ok" AND "_reason" IS NULL
         THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_reason" IS NULL, "_sk" ORDER BY "order_purchase_timestamp" DESC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_good"
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
WITH i AS (SELECT "order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date", "cust_customer_state", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM _outcome WHERE "_outcome" = 'survivor'),
o AS (SELECT "order_id", md5(dwh_salt() || CAST("customer_id" AS VARCHAR)) AS "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date", "cust_customer_state", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM i)
SELECT "order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date", "cust_customer_state", "_sk", md5(to_json(struct_pack("order_id" := "order_id", "customer_id" := "customer_id", "order_status" := "order_status", "order_purchase_timestamp" := "order_purchase_timestamp", "order_approved_at" := "order_approved_at", "order_delivered_carrier_date" := "order_delivered_carrier_date", "order_delivered_customer_date" := "order_delivered_customer_date", "order_estimated_delivery_date" := "order_estimated_delivery_date", "cust_customer_state" := "cust_customer_state"))) AS "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", dwh_now() AS "_loaded_at", FALSE AS "_is_deleted"
FROM o
ORDER BY "_sk";

-- @step deadletter
DELETE FROM silver_dead_letter WHERE entity = 'orders' AND src = (SELECT src FROM _scope) AND batch_id = (SELECT batch_id FROM _scope);
INSERT INTO silver_dead_letter SELECT 'orders', o."_src", o."_batch_id", o."_batch_version", o."_source_file", o."_row_number", o."_dl_reason", o."_anomaly", dwh_now(), json_object('order_id', "__raw"."order_id", 'customer_id', md5(dwh_salt() || CAST("__raw"."customer_id" AS VARCHAR)), 'order_status', "__raw"."order_status", 'order_purchase_timestamp', "__raw"."order_purchase_timestamp", 'order_approved_at', "__raw"."order_approved_at", 'order_delivered_carrier_date', "__raw"."order_delivered_carrier_date", 'order_delivered_customer_date', "__raw"."order_delivered_customer_date", 'order_estimated_delivery_date', "__raw"."order_estimated_delivery_date")
FROM _outcome o JOIN "bronze_orders" "__raw" ON "__raw"."_batch_id" = o."_batch_id" AND "__raw"."_batch_version" = o."_batch_version" AND "__raw"."_row_number" = o."_row_number"
WHERE o."_outcome" = 'dead_letter';
