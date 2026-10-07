-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=a1a30dd22b662d14 body_sha=fb173e6a9141bf119e677a939b5a5216f79fd4b71b5c15339f5d9a5a4eb3f448
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step typed
CREATE OR REPLACE TEMP TABLE _typed AS
WITH b AS (SELECT * FROM "bronze_categories" WHERE "_batch_id" = (SELECT batch_id FROM _scope) AND "_batch_version" = (SELECT batch_version FROM _scope)),
t AS (SELECT
  "_src",
  "_batch_id",
  "_batch_version",
  "_source_file",
  "_row_number",
  "product_category_name" AS "_raw__product_category_name",
  trim("product_category_name") AS "product_category_name",
  FALSE AS "_amb__product_category_name",
  FALSE AS "_dom__product_category_name",
  "product_category_name_english" AS "_raw__product_category_name_english",
  "product_category_name_english" AS "product_category_name_english",
  FALSE AS "_amb__product_category_name_english",
  FALSE AS "_dom__product_category_name_english"
FROM b)
SELECT t.*, md5(to_json(struct_pack(k0 := trim("product_category_name")))) AS "_sk", md5(to_json(struct_pack("product_category_name" := "product_category_name", "product_category_name_english" := "product_category_name_english"))) AS "_content", ("product_category_name" IS NOT NULL) AS "_key_ok", FALSE AS "_is_del"
FROM t;

-- @step judged
CREATE OR REPLACE TEMP TABLE _judged AS
SELECT t.*,
  CASE
    WHEN t."_raw__product_category_name" IS NOT NULL AND t."product_category_name" IS NULL THEN 'cast_product_category_name'
    WHEN NOT t."_key_ok" THEN 'null_key'
    WHEN t."_raw__product_category_name_english" IS NOT NULL AND t."product_category_name_english" IS NULL THEN 'cast_product_category_name_english'
  END AS "_reason",
  NULL AS "_anomaly",
  NULL AS "_hard"
FROM _typed t;

-- @step outcome
CREATE OR REPLACE TEMP TABLE _outcome AS
WITH r AS (
  SELECT *,
    CASE WHEN "_key_ok" THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_sk" ORDER BY "product_category_name" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_all",
    CASE WHEN "_key_ok" AND "_reason" IS NULL
         THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_reason" IS NULL, "_sk" ORDER BY "product_category_name" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_good"
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
WITH i AS (SELECT "product_category_name", "product_category_name_english", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM _outcome WHERE "_outcome" = 'survivor'),
o AS (SELECT "product_category_name", "product_category_name_english", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM i)
SELECT "product_category_name", "product_category_name_english", "_sk", md5(to_json(struct_pack("product_category_name" := "product_category_name", "product_category_name_english" := "product_category_name_english"))) AS "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", dwh_now() AS "_loaded_at", FALSE AS "_is_deleted"
FROM o
ORDER BY "_sk";

-- @step deadletter
DELETE FROM silver_dead_letter WHERE entity = 'categories' AND src = (SELECT src FROM _scope) AND batch_id = (SELECT batch_id FROM _scope);
INSERT INTO silver_dead_letter SELECT 'categories', o."_src", o."_batch_id", o."_batch_version", o."_source_file", o."_row_number", o."_dl_reason", o."_anomaly", dwh_now(), json_object('product_category_name', "__raw"."product_category_name", 'product_category_name_english', "__raw"."product_category_name_english")
FROM _outcome o JOIN "bronze_categories" "__raw" ON "__raw"."_batch_id" = o."_batch_id" AND "__raw"."_batch_version" = o."_batch_version" AND "__raw"."_row_number" = o."_row_number"
WHERE o."_outcome" = 'dead_letter';
