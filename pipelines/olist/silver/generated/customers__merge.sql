-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=98c79e9307c8a389 body_sha=12004a17df6c0706bdff0d1a58bbe5ae5c153f51e9bb0b00843f69334224aca5
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step create
CREATE TABLE IF NOT EXISTS "silver_customers" AS SELECT "customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state", "_sk", "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_loaded_at", "_is_deleted" FROM _final WHERE FALSE;

-- @step terms
CREATE OR REPLACE TEMP TABLE _withdraw AS SELECT NULL::VARCHAR AS "_sk" WHERE FALSE;
CREATE OR REPLACE TEMP TABLE _parts AS
SELECT DISTINCT CAST("_batch_id" AS VARCHAR) AS p FROM _outcome WHERE "_batch_id" IS NOT NULL;
CREATE OR REPLACE TEMP TABLE _terms AS
SELECT (SELECT COUNT(*) FROM _final) AS inserted, 0 AS updated, 0 AS stale, 0 AS already_present, 0 AS unchanged, 0 AS reactivated, 0 AS deleted, 
       (SELECT COUNT(*) FROM "silver_customers" WHERE "_src" = (SELECT src FROM _scope)
          AND CAST("_batch_id" AS VARCHAR) IN (SELECT p FROM _parts)) AS removed;
CREATE OR REPLACE TEMP TABLE _terms AS SELECT x.*, (SELECT COUNT(*) FROM _withdraw) AS withdrawn FROM _terms x;

-- @step apply
DELETE FROM "silver_customers" WHERE "_src" = (SELECT src FROM _scope)
  AND CAST("_batch_id" AS VARCHAR) IN (SELECT p FROM _parts);
INSERT INTO "silver_customers" ("customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state", "_sk", "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_loaded_at", "_is_deleted") SELECT "customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state", "_sk", "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_loaded_at", "_is_deleted" FROM _final;
UPDATE "silver_customers" SET "_is_deleted" = TRUE, "_loaded_at" = dwh_now() WHERE "_sk" IN (SELECT "_sk" FROM _withdraw);
