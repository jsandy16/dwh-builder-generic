-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=3df0c43c9f8a434c body_sha=23cd1ab1fc698a59d7e634e569497aa9221915fe007f6c452a550dc9d2dd82da
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step typed
CREATE OR REPLACE TEMP TABLE _typed AS
WITH b AS (SELECT * FROM "bronze_payments" WHERE "_batch_id" = (SELECT batch_id FROM _scope) AND "_batch_version" = (SELECT batch_version FROM _scope)),
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
  "payment_sequential" AS "_raw__payment_sequential",
  CASE WHEN regexp_matches(trim("payment_sequential"), '^[+-]?[0-9]+$') THEN TRY_CAST(trim("payment_sequential") AS BIGINT) END AS "payment_sequential",
  FALSE AS "_amb__payment_sequential",
  FALSE AS "_dom__payment_sequential",
  "payment_type" AS "_raw__payment_type",
  "payment_type" AS "payment_type",
  FALSE AS "_amb__payment_type",
  FALSE AS "_dom__payment_type",
  "payment_installments" AS "_raw__payment_installments",
  CASE WHEN regexp_matches(trim("payment_installments"), '^[+-]?[0-9]+$') THEN TRY_CAST(trim("payment_installments") AS BIGINT) END AS "payment_installments",
  FALSE AS "_amb__payment_installments",
  FALSE AS "_dom__payment_installments",
  "payment_value" AS "_raw__payment_value",
  CASE WHEN TRY_CAST(trim("payment_value") AS DOUBLE) = TRY_CAST(TRY_CAST(trim("payment_value") AS DECIMAL(18,2)) AS DOUBLE) THEN TRY_CAST(trim("payment_value") AS DECIMAL(18,2)) END AS "payment_value",
  FALSE AS "_amb__payment_value",
  FALSE AS "_dom__payment_value"
FROM b)
SELECT t.*, md5(to_json(struct_pack(k0 := trim("order_id"), k1 := CAST("payment_sequential" AS VARCHAR)))) AS "_sk", md5(to_json(struct_pack("order_id" := "order_id", "payment_sequential" := "payment_sequential", "payment_type" := "payment_type", "payment_installments" := "payment_installments", "payment_value" := "payment_value"))) AS "_content", ("order_id" IS NOT NULL AND "payment_sequential" IS NOT NULL) AS "_key_ok", FALSE AS "_is_del"
FROM t;

-- @step judged
CREATE OR REPLACE TEMP TABLE _judged AS
SELECT t.*,
  CASE
    WHEN t."_raw__order_id" IS NOT NULL AND t."order_id" IS NULL THEN 'cast_order_id'
    WHEN t."_raw__payment_sequential" IS NOT NULL AND t."payment_sequential" IS NULL THEN 'cast_payment_sequential'
    WHEN NOT t."_key_ok" THEN 'null_key'
    WHEN t."_raw__payment_type" IS NOT NULL AND t."payment_type" IS NULL THEN 'cast_payment_type'
    WHEN t."_raw__payment_installments" IS NOT NULL AND t."payment_installments" IS NULL THEN 'cast_payment_installments'
    WHEN t."_raw__payment_value" IS NOT NULL AND t."payment_value" IS NULL THEN 'cast_payment_value'
  END AS "_reason",
  CASE WHEN COALESCE((payment_value = 0), FALSE) THEN 'zero_value' END AS "_anomaly",
  NULL AS "_hard"
FROM _typed t;

-- @step outcome
CREATE OR REPLACE TEMP TABLE _outcome AS
WITH r AS (
  SELECT *,
    CASE WHEN "_key_ok" THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_sk" ORDER BY "order_id" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_all",
    CASE WHEN "_key_ok" AND "_reason" IS NULL
         THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_reason" IS NULL, "_sk" ORDER BY "order_id" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_good"
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
WITH i AS (SELECT "order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM _outcome WHERE "_outcome" = 'survivor'),
o AS (SELECT "order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM i)
SELECT "order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value", "_sk", md5(to_json(struct_pack("order_id" := "order_id", "payment_sequential" := "payment_sequential", "payment_type" := "payment_type", "payment_installments" := "payment_installments", "payment_value" := "payment_value"))) AS "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", dwh_now() AS "_loaded_at", FALSE AS "_is_deleted"
FROM o
ORDER BY "_sk";

-- @step deadletter
DELETE FROM silver_dead_letter WHERE entity = 'payments' AND src = (SELECT src FROM _scope) AND batch_id = (SELECT batch_id FROM _scope);
INSERT INTO silver_dead_letter SELECT 'payments', o."_src", o."_batch_id", o."_batch_version", o."_source_file", o."_row_number", o."_dl_reason", o."_anomaly", dwh_now(), json_object('order_id', "__raw"."order_id", 'payment_sequential', "__raw"."payment_sequential", 'payment_type', "__raw"."payment_type", 'payment_installments', "__raw"."payment_installments", 'payment_value', "__raw"."payment_value")
FROM _outcome o JOIN "bronze_payments" "__raw" ON "__raw"."_batch_id" = o."_batch_id" AND "__raw"."_batch_version" = o."_batch_version" AND "__raw"."_row_number" = o."_row_number"
WHERE o."_outcome" = 'dead_letter';
