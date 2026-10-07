-- dwh_core:generated v=1.2.0 template=silver/v1 template_sha=58a4a6f67fd5c149 spec_sha=2a62eaa3a7db22a9 body_sha=2a70eb0da1b0ee954ba8590b61e05d174a44add91ccbea51478b2e7c7bccaed1
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step typed
CREATE OR REPLACE TEMP TABLE _typed AS
WITH b AS (SELECT * FROM "bronze_reviews" WHERE "_batch_id" = (SELECT batch_id FROM _scope) AND "_batch_version" = (SELECT batch_version FROM _scope)),
t AS (SELECT
  "_src",
  "_batch_id",
  "_batch_version",
  "_source_file",
  "_row_number",
  "review_id" AS "_raw__review_id",
  trim("review_id") AS "review_id",
  FALSE AS "_amb__review_id",
  FALSE AS "_dom__review_id",
  "order_id" AS "_raw__order_id",
  trim("order_id") AS "order_id",
  FALSE AS "_amb__order_id",
  FALSE AS "_dom__order_id",
  "review_score" AS "_raw__review_score",
  CASE WHEN regexp_matches(trim("review_score"), '^[+-]?[0-9]+$') THEN TRY_CAST(trim("review_score") AS BIGINT) END AS "review_score",
  FALSE AS "_amb__review_score",
  FALSE AS "_dom__review_score",
  "review_comment_title" AS "_raw__review_comment_title",
  "review_comment_title" AS "review_comment_title",
  FALSE AS "_amb__review_comment_title",
  FALSE AS "_dom__review_comment_title",
  "review_comment_message" AS "_raw__review_comment_message",
  "review_comment_message" AS "review_comment_message",
  FALSE AS "_amb__review_comment_message",
  FALSE AS "_dom__review_comment_message",
  "review_creation_date" AS "_raw__review_creation_date",
  TRY_STRPTIME("review_creation_date", '%Y-%m-%d %H:%M:%S') AS "review_creation_date",
  FALSE AS "_amb__review_creation_date",
  FALSE AS "_dom__review_creation_date",
  "review_answer_timestamp" AS "_raw__review_answer_timestamp",
  TRY_STRPTIME("review_answer_timestamp", '%Y-%m-%d %H:%M:%S') AS "review_answer_timestamp",
  FALSE AS "_amb__review_answer_timestamp",
  FALSE AS "_dom__review_answer_timestamp"
FROM b)
SELECT t.*, md5(to_json(struct_pack(k0 := trim("review_id"), k1 := trim("order_id")))) AS "_sk", md5(to_json(struct_pack("review_id" := "review_id", "order_id" := "order_id", "review_score" := "review_score", "review_comment_title" := "review_comment_title", "review_comment_message" := "review_comment_message", "review_creation_date" := "review_creation_date", "review_answer_timestamp" := "review_answer_timestamp"))) AS "_content", ("review_id" IS NOT NULL AND "order_id" IS NOT NULL) AS "_key_ok", FALSE AS "_is_del"
FROM t;

-- @step judged
CREATE OR REPLACE TEMP TABLE _judged AS
SELECT t.*,
  CASE
    WHEN t."_raw__review_id" IS NOT NULL AND t."review_id" IS NULL THEN 'cast_review_id'
    WHEN t."_raw__order_id" IS NOT NULL AND t."order_id" IS NULL THEN 'cast_order_id'
    WHEN NOT t."_key_ok" THEN 'null_key'
    WHEN t."_raw__review_score" IS NOT NULL AND t."review_score" IS NULL THEN 'cast_review_score'
    WHEN t."_raw__review_comment_title" IS NOT NULL AND t."review_comment_title" IS NULL THEN 'cast_review_comment_title'
    WHEN t."_raw__review_comment_message" IS NOT NULL AND t."review_comment_message" IS NULL THEN 'cast_review_comment_message'
    WHEN t."_raw__review_creation_date" IS NOT NULL AND t."review_creation_date" IS NULL THEN 'cast_review_creation_date'
    WHEN t."_raw__review_answer_timestamp" IS NOT NULL AND t."review_answer_timestamp" IS NULL THEN 'cast_review_answer_timestamp'
  END AS "_reason",
  NULL AS "_anomaly",
  NULL AS "_hard"
FROM _typed t;

-- @step outcome
CREATE OR REPLACE TEMP TABLE _outcome AS
WITH r AS (
  SELECT *,
    CASE WHEN "_key_ok" THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_sk" ORDER BY "review_answer_timestamp" DESC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_all",
    CASE WHEN "_key_ok" AND "_reason" IS NULL
         THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_reason" IS NULL, "_sk" ORDER BY "review_answer_timestamp" DESC NULLS LAST, "_batch_version" DESC, "_source_file" DESC, "_row_number" DESC) END AS "_rank_good"
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
WITH i AS (SELECT "review_id", "order_id", "review_score", "review_comment_title", "review_comment_message", "review_creation_date", "review_answer_timestamp", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM _outcome WHERE "_outcome" = 'survivor'),
o AS (SELECT "review_id", "order_id", "review_score", "review_creation_date", "review_answer_timestamp", "_sk", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_is_del" FROM i)
SELECT "review_id", "order_id", "review_score", "review_creation_date", "review_answer_timestamp", "_sk", md5(to_json(struct_pack("review_id" := "review_id", "order_id" := "order_id", "review_score" := "review_score", "review_creation_date" := "review_creation_date", "review_answer_timestamp" := "review_answer_timestamp"))) AS "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number", dwh_now() AS "_loaded_at", FALSE AS "_is_deleted"
FROM o
ORDER BY "_sk";

-- @step deadletter
DELETE FROM silver_dead_letter WHERE entity = 'reviews' AND src = (SELECT src FROM _scope) AND batch_id = (SELECT batch_id FROM _scope);
INSERT INTO silver_dead_letter SELECT 'reviews', o."_src", o."_batch_id", o."_batch_version", o."_source_file", o."_row_number", o."_dl_reason", o."_anomaly", dwh_now(), json_object('review_id', "__raw"."review_id", 'order_id', "__raw"."order_id", 'review_score', "__raw"."review_score", 'review_comment_title', md5(dwh_salt() || CAST("__raw"."review_comment_title" AS VARCHAR)), 'review_comment_message', md5(dwh_salt() || CAST("__raw"."review_comment_message" AS VARCHAR)), 'review_creation_date', "__raw"."review_creation_date", 'review_answer_timestamp', "__raw"."review_answer_timestamp")
FROM _outcome o JOIN "bronze_reviews" "__raw" ON "__raw"."_batch_id" = o."_batch_id" AND "__raw"."_batch_version" = o."_batch_version" AND "__raw"."_row_number" = o."_row_number"
WHERE o."_outcome" = 'dead_letter';
