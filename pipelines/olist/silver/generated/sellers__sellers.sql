-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=a23bdf848dfc34ad body_sha=ef42d52f1e82cb5ed10636602099266c2513fbdfb22340fa096ba552d8ee7835
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step typed
CREATE OR REPLACE TEMP TABLE _typed AS
WITH b AS (SELECT * FROM "bronze_sellers" WHERE "_batch_id" = (SELECT batch_id FROM _scope) AND "_batch_version" = (SELECT batch_version FROM _scope)),
t AS (SELECT
  "_src",
  "_batch_id",
  "_batch_version",
  "_source_file",
  "_row_number",
  "seller_id" AS "_raw__seller_id",
  trim("seller_id") AS "seller_id",
  FALSE AS "_amb__seller_id",
  FALSE AS "_dom__seller_id",
  (lpad(seller_zip_code_prefix, 5, '0')) AS "_raw__seller_zip_code_prefix",
  (lpad(seller_zip_code_prefix, 5, '0')) AS "seller_zip_code_prefix",
  FALSE AS "_amb__seller_zip_code_prefix",
  FALSE AS "_dom__seller_zip_code_prefix",
  "seller_city" AS "_raw__seller_city",
  "seller_city" AS "seller_city",
  FALSE AS "_amb__seller_city",
  FALSE AS "_dom__seller_city",
  "seller_state" AS "_raw__seller_state",
  "seller_state" AS "seller_state",
  FALSE AS "_amb__seller_state",
  FALSE AS "_dom__seller_state"
FROM b)
SELECT t.*, md5(to_json(struct_pack(k0 := trim("seller_id")))) AS "_sk", md5(to_json(struct_pack("seller_id" := "seller_id", "seller_zip_code_prefix" := "seller_zip_code_prefix", "seller_city" := "seller_city", "seller_state" := "seller_state"))) AS "_content", ("seller_id" IS NOT NULL) AS "_key_ok", FALSE AS "_is_del"
FROM t;

-- @step judged
CREATE OR REPLACE TEMP TABLE _judged AS
SELECT t.*,
  CASE
    WHEN t."_raw__seller_id" IS NOT NULL AND t."seller_id" IS NULL THEN 'cast_seller_id'
    WHEN NOT t."_key_ok" THEN 'null_key'
    WHEN t."_raw__seller_zip_code_prefix" IS NOT NULL AND t."seller_zip_code_prefix" IS NULL THEN 'cast_seller_zip_code_prefix'
    WHEN t."_raw__seller_city" IS NOT NULL AND t."seller_city" IS NULL THEN 'cast_seller_city'
    WHEN t."_raw__seller_state" IS NOT NULL AND t."seller_state" IS NULL THEN 'cast_seller_state'
  END AS "_reason",
  NULL AS "_anomaly",
  NULL AS "_hard"
FROM _typed t;

-- @step outcome
CREATE OR REPLACE TEMP TABLE _outcome AS
WITH r AS (
  SELECT *,
    CASE WHEN "_key_ok" THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_sk" ORDER BY "seller_id" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_all",
    CASE WHEN "_key_ok" AND "_reason" IS NULL
         THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_reason" IS NULL, "_sk" ORDER BY "seller_id" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_good"
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
WITH i AS (SELECT "seller_id", "seller_zip_code_prefix", "seller_city", "seller_state", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM _outcome WHERE "_outcome" = 'survivor'),
o AS (SELECT "seller_id", "seller_zip_code_prefix", "seller_city", "seller_state", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM i)
SELECT "seller_id", "seller_zip_code_prefix", "seller_city", "seller_state", "_sk", md5(to_json(struct_pack("seller_id" := "seller_id", "seller_zip_code_prefix" := "seller_zip_code_prefix", "seller_city" := "seller_city", "seller_state" := "seller_state"))) AS "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", dwh_now() AS "_loaded_at", FALSE AS "_is_deleted"
FROM o
ORDER BY "_sk";

-- @step deadletter
DELETE FROM silver_dead_letter WHERE entity = 'sellers' AND src = (SELECT src FROM _scope) AND batch_id = (SELECT batch_id FROM _scope);
INSERT INTO silver_dead_letter SELECT 'sellers', o."_src", o."_batch_id", o."_batch_version", o."_source_file", o."_row_number", o."_dl_reason", o."_anomaly", dwh_now(), json_object('seller_id', "__raw"."seller_id", 'seller_zip_code_prefix', "__raw"."seller_zip_code_prefix", 'seller_city', "__raw"."seller_city", 'seller_state', "__raw"."seller_state")
FROM _outcome o JOIN "bronze_sellers" "__raw" ON "__raw"."_batch_id" = o."_batch_id" AND "__raw"."_batch_version" = o."_batch_version" AND "__raw"."_row_number" = o."_row_number"
WHERE o."_outcome" = 'dead_letter';
