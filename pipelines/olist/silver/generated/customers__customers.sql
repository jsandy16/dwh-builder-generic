-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=98c79e9307c8a389 body_sha=537adad71ebcf87a88573757bf7b20b1520c683908ace9e4283dc09c1a96cadc
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step typed
CREATE OR REPLACE TEMP TABLE _typed AS
WITH b AS (SELECT * FROM "bronze_customers" WHERE "_batch_id" = (SELECT batch_id FROM _scope) AND "_batch_version" = (SELECT batch_version FROM _scope)),
t AS (SELECT
  "_src",
  "_batch_id",
  "_batch_version",
  "_source_file",
  "_row_number",
  "customer_id" AS "_raw__customer_id",
  trim("customer_id") AS "customer_id",
  FALSE AS "_amb__customer_id",
  FALSE AS "_dom__customer_id",
  "customer_unique_id" AS "_raw__customer_unique_id",
  "customer_unique_id" AS "customer_unique_id",
  FALSE AS "_amb__customer_unique_id",
  FALSE AS "_dom__customer_unique_id",
  (lpad(customer_zip_code_prefix, 5, '0')) AS "_raw__customer_zip_code_prefix",
  (lpad(customer_zip_code_prefix, 5, '0')) AS "customer_zip_code_prefix",
  FALSE AS "_amb__customer_zip_code_prefix",
  FALSE AS "_dom__customer_zip_code_prefix",
  "customer_city" AS "_raw__customer_city",
  "customer_city" AS "customer_city",
  FALSE AS "_amb__customer_city",
  FALSE AS "_dom__customer_city",
  "customer_state" AS "_raw__customer_state",
  "customer_state" AS "customer_state",
  FALSE AS "_amb__customer_state",
  FALSE AS "_dom__customer_state"
FROM b)
SELECT t.*, md5(dwh_salt() || to_json(struct_pack(k0 := trim("customer_id")))) AS "_sk", md5(to_json(struct_pack("customer_id" := "customer_id", "customer_unique_id" := "customer_unique_id", "customer_zip_code_prefix" := "customer_zip_code_prefix", "customer_city" := "customer_city", "customer_state" := "customer_state"))) AS "_content", ("customer_id" IS NOT NULL) AS "_key_ok", FALSE AS "_is_del"
FROM t;

-- @step judged
CREATE OR REPLACE TEMP TABLE _judged AS
SELECT t.*,
  CASE
    WHEN t."_raw__customer_id" IS NOT NULL AND t."customer_id" IS NULL THEN 'cast_customer_id'
    WHEN NOT t."_key_ok" THEN 'null_key'
    WHEN t."_raw__customer_unique_id" IS NOT NULL AND t."customer_unique_id" IS NULL THEN 'cast_customer_unique_id'
    WHEN t."_raw__customer_zip_code_prefix" IS NOT NULL AND t."customer_zip_code_prefix" IS NULL THEN 'cast_customer_zip_code_prefix'
    WHEN t."_raw__customer_city" IS NOT NULL AND t."customer_city" IS NULL THEN 'cast_customer_city'
    WHEN t."_raw__customer_state" IS NOT NULL AND t."customer_state" IS NULL THEN 'cast_customer_state'
  END AS "_reason",
  NULL AS "_anomaly",
  NULL AS "_hard"
FROM _typed t;

-- @step outcome
CREATE OR REPLACE TEMP TABLE _outcome AS
WITH r AS (
  SELECT *,
    CASE WHEN "_key_ok" THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_sk" ORDER BY "customer_id" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_all",
    CASE WHEN "_key_ok" AND "_reason" IS NULL
         THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_reason" IS NULL, "_sk" ORDER BY "customer_id" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_good"
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
WITH i AS (SELECT "customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM _outcome WHERE "_outcome" = 'survivor'),
o AS (SELECT md5(dwh_salt() || CAST("customer_id" AS VARCHAR)) AS "customer_id", md5(dwh_salt() || CAST("customer_unique_id" AS VARCHAR)) AS "customer_unique_id", md5(dwh_salt() || CAST("customer_zip_code_prefix" AS VARCHAR)) AS "customer_zip_code_prefix", "customer_city", "customer_state", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM i)
SELECT "customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state", "_sk", md5(to_json(struct_pack("customer_id" := "customer_id", "customer_unique_id" := "customer_unique_id", "customer_zip_code_prefix" := "customer_zip_code_prefix", "customer_city" := "customer_city", "customer_state" := "customer_state"))) AS "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", dwh_now() AS "_loaded_at", FALSE AS "_is_deleted"
FROM o
ORDER BY "_sk";

-- @step deadletter
DELETE FROM silver_dead_letter WHERE entity = 'customers' AND src = (SELECT src FROM _scope) AND batch_id = (SELECT batch_id FROM _scope);
INSERT INTO silver_dead_letter SELECT 'customers', o."_src", o."_batch_id", o."_batch_version", o."_source_file", o."_row_number", o."_dl_reason", o."_anomaly", dwh_now(), json_object('customer_id', md5(dwh_salt() || CAST("__raw"."customer_id" AS VARCHAR)), 'customer_unique_id', md5(dwh_salt() || CAST("__raw"."customer_unique_id" AS VARCHAR)), 'customer_zip_code_prefix', md5(dwh_salt() || CAST("__raw"."customer_zip_code_prefix" AS VARCHAR)), 'customer_city', "__raw"."customer_city", 'customer_state', "__raw"."customer_state")
FROM _outcome o JOIN "bronze_customers" "__raw" ON "__raw"."_batch_id" = o."_batch_id" AND "__raw"."_batch_version" = o."_batch_version" AND "__raw"."_row_number" = o."_row_number"
WHERE o."_outcome" = 'dead_letter';
