-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=d23bcd098d72f604 body_sha=ea66c555c808a30289da9fcb0d1f5e10fad19cc9ac0d78f4b422ba18dac258e8
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step typed
CREATE OR REPLACE TEMP TABLE _typed AS
WITH b AS (SELECT * FROM "bronze_products" WHERE "_batch_id" = (SELECT batch_id FROM _scope) AND "_batch_version" = (SELECT batch_version FROM _scope)),
t AS (SELECT
  "_src",
  "_batch_id",
  "_batch_version",
  "_source_file",
  "_row_number",
  "product_id" AS "_raw__product_id",
  trim("product_id") AS "product_id",
  FALSE AS "_amb__product_id",
  FALSE AS "_dom__product_id",
  "product_name_lenght" AS "_raw__product_name_lenght",
  TRY_CAST("product_name_lenght" AS DOUBLE) AS "product_name_lenght",
  FALSE AS "_amb__product_name_lenght",
  FALSE AS "_dom__product_name_lenght",
  "product_description_lenght" AS "_raw__product_description_lenght",
  TRY_CAST("product_description_lenght" AS DOUBLE) AS "product_description_lenght",
  FALSE AS "_amb__product_description_lenght",
  FALSE AS "_dom__product_description_lenght",
  "product_photos_qty" AS "_raw__product_photos_qty",
  TRY_CAST("product_photos_qty" AS DOUBLE) AS "product_photos_qty",
  FALSE AS "_amb__product_photos_qty",
  FALSE AS "_dom__product_photos_qty",
  "product_weight_g" AS "_raw__product_weight_g",
  TRY_CAST("product_weight_g" AS DOUBLE) AS "product_weight_g",
  FALSE AS "_amb__product_weight_g",
  FALSE AS "_dom__product_weight_g",
  "product_length_cm" AS "_raw__product_length_cm",
  TRY_CAST("product_length_cm" AS DOUBLE) AS "product_length_cm",
  FALSE AS "_amb__product_length_cm",
  FALSE AS "_dom__product_length_cm",
  "product_height_cm" AS "_raw__product_height_cm",
  TRY_CAST("product_height_cm" AS DOUBLE) AS "product_height_cm",
  FALSE AS "_amb__product_height_cm",
  FALSE AS "_dom__product_height_cm",
  "product_width_cm" AS "_raw__product_width_cm",
  TRY_CAST("product_width_cm" AS DOUBLE) AS "product_width_cm",
  FALSE AS "_amb__product_width_cm",
  FALSE AS "_dom__product_width_cm",
  "product_category_name" AS "_raw__product_category_name",
  "product_category_name" AS "product_category_name",
  FALSE AS "_amb__product_category_name",
  FALSE AS "_dom__product_category_name"
FROM b)
SELECT t.*, md5(to_json(struct_pack(k0 := trim("product_id")))) AS "_sk", md5(to_json(struct_pack("product_id" := "product_id", "product_name_lenght" := "product_name_lenght", "product_description_lenght" := "product_description_lenght", "product_photos_qty" := "product_photos_qty", "product_weight_g" := "product_weight_g", "product_length_cm" := "product_length_cm", "product_height_cm" := "product_height_cm", "product_width_cm" := "product_width_cm", "product_category_name" := "product_category_name"))) AS "_content", ("product_id" IS NOT NULL) AS "_key_ok", FALSE AS "_is_del"
FROM t;

-- @step judged
CREATE OR REPLACE TEMP TABLE _judged AS
SELECT t.*, "lk_cat"."cat_product_category_name_english" AS "cat_product_category_name_english", "lk_cat"."_hit" AS "_hit__cat",
  CASE
    WHEN t."_raw__product_id" IS NOT NULL AND t."product_id" IS NULL THEN 'cast_product_id'
    WHEN NOT t."_key_ok" THEN 'null_key'
    WHEN t."_raw__product_name_lenght" IS NOT NULL AND t."product_name_lenght" IS NULL THEN 'cast_product_name_lenght'
    WHEN t."_raw__product_description_lenght" IS NOT NULL AND t."product_description_lenght" IS NULL THEN 'cast_product_description_lenght'
    WHEN t."_raw__product_photos_qty" IS NOT NULL AND t."product_photos_qty" IS NULL THEN 'cast_product_photos_qty'
    WHEN t."_raw__product_weight_g" IS NOT NULL AND t."product_weight_g" IS NULL THEN 'cast_product_weight_g'
    WHEN t."_raw__product_length_cm" IS NOT NULL AND t."product_length_cm" IS NULL THEN 'cast_product_length_cm'
    WHEN t."_raw__product_height_cm" IS NOT NULL AND t."product_height_cm" IS NULL THEN 'cast_product_height_cm'
    WHEN t."_raw__product_width_cm" IS NOT NULL AND t."product_width_cm" IS NULL THEN 'cast_product_width_cm'
    WHEN t."_raw__product_category_name" IS NOT NULL AND t."product_category_name" IS NULL THEN 'cast_product_category_name'
  END AS "_reason",
  NULL AS "_anomaly",
  NULL AS "_hard"
FROM _typed t
LEFT JOIN (SELECT "product_category_name" AS "_k_product_category_name", "product_category_name_english" AS "cat_product_category_name_english", TRUE AS "_hit" FROM "silver_categories" WHERE NOT "_is_deleted") "lk_cat" ON t."product_category_name" = "lk_cat"."_k_product_category_name";

-- @step outcome
CREATE OR REPLACE TEMP TABLE _outcome AS
WITH r AS (
  SELECT *,
    CASE WHEN "_key_ok" THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_sk" ORDER BY "product_id" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_all",
    CASE WHEN "_key_ok" AND "_reason" IS NULL
         THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_reason" IS NULL, "_sk" ORDER BY "product_id" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_good"
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
WITH i AS (SELECT "product_id", "product_name_lenght", "product_description_lenght", "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm", "product_category_name", "cat_product_category_name_english", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM _outcome WHERE "_outcome" = 'survivor'),
o AS (SELECT "product_id", "product_name_lenght", "product_description_lenght", "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm", "product_category_name", "cat_product_category_name_english", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM i)
SELECT "product_id", "product_name_lenght", "product_description_lenght", "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm", "product_category_name", "cat_product_category_name_english", "_sk", md5(to_json(struct_pack("product_id" := "product_id", "product_name_lenght" := "product_name_lenght", "product_description_lenght" := "product_description_lenght", "product_photos_qty" := "product_photos_qty", "product_weight_g" := "product_weight_g", "product_length_cm" := "product_length_cm", "product_height_cm" := "product_height_cm", "product_width_cm" := "product_width_cm", "product_category_name" := "product_category_name", "cat_product_category_name_english" := "cat_product_category_name_english"))) AS "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", dwh_now() AS "_loaded_at", FALSE AS "_is_deleted"
FROM o
ORDER BY "_sk";

-- @step deadletter
DELETE FROM silver_dead_letter WHERE entity = 'products' AND src = (SELECT src FROM _scope) AND batch_id = (SELECT batch_id FROM _scope);
INSERT INTO silver_dead_letter SELECT 'products', o."_src", o."_batch_id", o."_batch_version", o."_source_file", o."_row_number", o."_dl_reason", o."_anomaly", dwh_now(), json_object('product_id', "__raw"."product_id", 'product_name_lenght', "__raw"."product_name_lenght", 'product_description_lenght', "__raw"."product_description_lenght", 'product_photos_qty', "__raw"."product_photos_qty", 'product_weight_g', "__raw"."product_weight_g", 'product_length_cm', "__raw"."product_length_cm", 'product_height_cm', "__raw"."product_height_cm", 'product_width_cm', "__raw"."product_width_cm", 'product_category_name', "__raw"."product_category_name")
FROM _outcome o JOIN "bronze_products" "__raw" ON "__raw"."_batch_id" = o."_batch_id" AND "__raw"."_batch_version" = o."_batch_version" AND "__raw"."_row_number" = o."_row_number"
WHERE o."_outcome" = 'dead_letter';
