-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=f76dce2d06ff0989 body_sha=9b205b1b34ba95b24cbbb0e94dfb61c9a2aeef71be68dbe81865ec8aa3494164
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step typed
CREATE OR REPLACE TEMP TABLE _typed AS
WITH b AS (SELECT * FROM "bronze_geolocation" WHERE "_batch_id" = (SELECT batch_id FROM _scope) AND "_batch_version" = (SELECT batch_version FROM _scope)),
t AS (SELECT
  "_src",
  "_batch_id",
  "_batch_version",
  "_source_file",
  "_row_number",
  (lpad(geolocation_zip_code_prefix, 5, '0')) AS "_raw__geolocation_zip_code_prefix",
  trim((lpad(geolocation_zip_code_prefix, 5, '0'))) AS "geolocation_zip_code_prefix",
  FALSE AS "_amb__geolocation_zip_code_prefix",
  FALSE AS "_dom__geolocation_zip_code_prefix",
  "geolocation_lat" AS "_raw__geolocation_lat",
  TRY_CAST("geolocation_lat" AS DOUBLE) AS "geolocation_lat",
  FALSE AS "_amb__geolocation_lat",
  FALSE AS "_dom__geolocation_lat",
  "geolocation_lng" AS "_raw__geolocation_lng",
  TRY_CAST("geolocation_lng" AS DOUBLE) AS "geolocation_lng",
  FALSE AS "_amb__geolocation_lng",
  FALSE AS "_dom__geolocation_lng",
  "geolocation_city" AS "_raw__geolocation_city",
  trim("geolocation_city") AS "geolocation_city",
  FALSE AS "_amb__geolocation_city",
  FALSE AS "_dom__geolocation_city",
  "geolocation_state" AS "_raw__geolocation_state",
  trim("geolocation_state") AS "geolocation_state",
  FALSE AS "_amb__geolocation_state",
  FALSE AS "_dom__geolocation_state"
FROM b)
SELECT t.*, md5(to_json(struct_pack(k0 := trim("geolocation_zip_code_prefix"), k1 := CAST("geolocation_lat" AS VARCHAR), k2 := CAST("geolocation_lng" AS VARCHAR), k3 := trim("geolocation_city"), k4 := trim("geolocation_state")))) AS "_sk", md5(to_json(struct_pack("geolocation_zip_code_prefix" := "geolocation_zip_code_prefix", "geolocation_lat" := "geolocation_lat", "geolocation_lng" := "geolocation_lng", "geolocation_city" := "geolocation_city", "geolocation_state" := "geolocation_state"))) AS "_content", ("geolocation_zip_code_prefix" IS NOT NULL AND "geolocation_lat" IS NOT NULL AND "geolocation_lng" IS NOT NULL AND "geolocation_city" IS NOT NULL AND "geolocation_state" IS NOT NULL) AS "_key_ok", FALSE AS "_is_del"
FROM t;

-- @step judged
CREATE OR REPLACE TEMP TABLE _judged AS
SELECT t.*,
  CASE
    WHEN t."_raw__geolocation_zip_code_prefix" IS NOT NULL AND t."geolocation_zip_code_prefix" IS NULL THEN 'cast_geolocation_zip_code_prefix'
    WHEN t."_raw__geolocation_lat" IS NOT NULL AND t."geolocation_lat" IS NULL THEN 'cast_geolocation_lat'
    WHEN t."_raw__geolocation_lng" IS NOT NULL AND t."geolocation_lng" IS NULL THEN 'cast_geolocation_lng'
    WHEN t."_raw__geolocation_city" IS NOT NULL AND t."geolocation_city" IS NULL THEN 'cast_geolocation_city'
    WHEN t."_raw__geolocation_state" IS NOT NULL AND t."geolocation_state" IS NULL THEN 'cast_geolocation_state'
    WHEN NOT t."_key_ok" THEN 'null_key'
    WHEN NOT t."_is_del" AND COALESCE((geolocation_lat NOT BETWEEN -33.75 AND 5.27 OR geolocation_lng NOT BETWEEN -73.99 AND -34.79), FALSE) THEN 'outside_brazil'
  END AS "_reason",
  NULL AS "_anomaly",
  CASE WHEN COALESCE((geolocation_lat NOT BETWEEN -33.75 AND 5.27 OR geolocation_lng NOT BETWEEN -73.99 AND -34.79), FALSE) THEN 'outside_brazil' END AS "_hard"
FROM _typed t;

-- @step outcome
CREATE OR REPLACE TEMP TABLE _outcome AS
WITH r AS (
  SELECT *,
    CASE WHEN "_key_ok" THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_sk" ORDER BY "geolocation_zip_code_prefix" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_all",
    CASE WHEN "_key_ok" AND "_reason" IS NULL
         THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_reason" IS NULL, "_sk" ORDER BY "geolocation_zip_code_prefix" ASC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_good"
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
WITH i AS (SELECT "geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng", "geolocation_city", "geolocation_state", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM _outcome WHERE "_outcome" = 'survivor'),
o AS (SELECT "geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng", "geolocation_city", "geolocation_state", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM i)
SELECT "geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng", "geolocation_city", "geolocation_state", "_sk", md5(to_json(struct_pack("geolocation_zip_code_prefix" := "geolocation_zip_code_prefix", "geolocation_lat" := "geolocation_lat", "geolocation_lng" := "geolocation_lng", "geolocation_city" := "geolocation_city", "geolocation_state" := "geolocation_state"))) AS "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", dwh_now() AS "_loaded_at", FALSE AS "_is_deleted"
FROM o
ORDER BY "_sk";

-- @step deadletter
DELETE FROM silver_dead_letter WHERE entity = 'geolocation' AND src = (SELECT src FROM _scope) AND batch_id = (SELECT batch_id FROM _scope);
INSERT INTO silver_dead_letter SELECT 'geolocation', o."_src", o."_batch_id", o."_batch_version", o."_source_file", o."_row_number", o."_dl_reason", o."_anomaly", dwh_now(), json_object('geolocation_zip_code_prefix', "__raw"."geolocation_zip_code_prefix", 'geolocation_lat', "__raw"."geolocation_lat", 'geolocation_lng', "__raw"."geolocation_lng", 'geolocation_city', "__raw"."geolocation_city", 'geolocation_state', "__raw"."geolocation_state")
FROM _outcome o JOIN "bronze_geolocation" "__raw" ON "__raw"."_batch_id" = o."_batch_id" AND "__raw"."_batch_version" = o."_batch_version" AND "__raw"."_row_number" = o."_row_number"
WHERE o."_outcome" = 'dead_letter';
