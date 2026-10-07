-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=d23bcd098d72f604 body_sha=7f84f5d28ebe07b76d7b906745b51956e2ebff5dfdd602826c939f1270f3aa97
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step create
CREATE TABLE IF NOT EXISTS "silver_products" AS SELECT "product_id", "product_name_lenght", "product_description_lenght", "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm", "product_category_name", "cat_product_category_name_english", "_sk", "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_loaded_at", "_is_deleted" FROM _final WHERE FALSE;

-- @step terms
CREATE OR REPLACE TEMP TABLE _withdraw AS SELECT NULL::VARCHAR AS "_sk" WHERE FALSE;
CREATE OR REPLACE TEMP TABLE _parts AS
SELECT DISTINCT CAST("_batch_id" AS VARCHAR) AS p FROM _outcome WHERE "_batch_id" IS NOT NULL;
CREATE OR REPLACE TEMP TABLE _terms AS
SELECT (SELECT COUNT(*) FROM _final) AS inserted, 0 AS updated, 0 AS stale, 0 AS already_present, 0 AS unchanged, 0 AS reactivated, 0 AS deleted, 
       (SELECT COUNT(*) FROM "silver_products" WHERE "_src" = (SELECT src FROM _scope)
          AND CAST("_batch_id" AS VARCHAR) IN (SELECT p FROM _parts)) AS removed;
CREATE OR REPLACE TEMP TABLE _terms AS SELECT x.*, (SELECT COUNT(*) FROM _withdraw) AS withdrawn FROM _terms x;

-- @step apply
DELETE FROM "silver_products" WHERE "_src" = (SELECT src FROM _scope)
  AND CAST("_batch_id" AS VARCHAR) IN (SELECT p FROM _parts);
INSERT INTO "silver_products" ("product_id", "product_name_lenght", "product_description_lenght", "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm", "product_category_name", "cat_product_category_name_english", "_sk", "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_loaded_at", "_is_deleted") SELECT "product_id", "product_name_lenght", "product_description_lenght", "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm", "product_category_name", "cat_product_category_name_english", "_sk", "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_loaded_at", "_is_deleted" FROM _final;
UPDATE "silver_products" SET "_is_deleted" = TRUE, "_loaded_at" = dwh_now() WHERE "_sk" IN (SELECT "_sk" FROM _withdraw);
