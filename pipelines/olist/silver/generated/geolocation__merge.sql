-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=f76dce2d06ff0989 body_sha=d0c37a255f2cb02115d90a887d2e15afb0ddfd2d4879f00370dee00658634952
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step create
CREATE TABLE IF NOT EXISTS "silver_geolocation" AS SELECT "geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng", "geolocation_city", "geolocation_state", "_sk", "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_loaded_at", "_is_deleted" FROM _final WHERE FALSE;

-- @step terms
CREATE OR REPLACE TEMP TABLE _withdraw AS SELECT NULL::VARCHAR AS "_sk" WHERE FALSE;
CREATE OR REPLACE TEMP TABLE _terms AS
SELECT COUNT(*) FILTER (WHERE t."_sk" IS NULL) AS inserted, 0 AS updated, 0 AS stale,
       COUNT(*) FILTER (WHERE t."_sk" IS NOT NULL) AS already_present, 0 AS unchanged, 0 AS reactivated,
       0 AS deleted, 0 AS removed
FROM _final f LEFT JOIN (SELECT DISTINCT "_sk" FROM "silver_geolocation") t ON f."_sk" = t."_sk";
CREATE OR REPLACE TEMP TABLE _terms AS SELECT x.*, (SELECT COUNT(*) FROM _withdraw) AS withdrawn FROM _terms x;

-- @step apply
INSERT INTO "silver_geolocation" ("geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng", "geolocation_city", "geolocation_state", "_sk", "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_loaded_at", "_is_deleted")
SELECT "geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng", "geolocation_city", "geolocation_state", "_sk", "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_loaded_at", "_is_deleted" FROM _final f WHERE NOT EXISTS (SELECT 1 FROM "silver_geolocation" x WHERE x."_sk" = f."_sk");
UPDATE "silver_geolocation" SET "_is_deleted" = TRUE, "_loaded_at" = dwh_now() WHERE "_sk" IN (SELECT "_sk" FROM _withdraw);
