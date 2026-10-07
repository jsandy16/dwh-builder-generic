-- dwh_core:generated v=1.2.0 template=gold/v1 template_sha=12b6468012dae72c spec_sha=6090668a41443847 body_sha=d8743600deb0030db248d89e8784a75f1f480ec40fe0deb3a56b1e573c8e56af
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step build
CREATE OR REPLACE TABLE "gold_avg_review_score_day" AS
SELECT CAST("review_creation_date" AS DATE) AS "review_creation_date",
  SUM("review_score") FILTER (WHERE TRUE AND TRUE) AS "avg_review_score__num",
  COUNT("review_score") FILTER (WHERE TRUE AND TRUE) AS "avg_review_score__den",
  ROUND(1 * CAST(SUM("review_score") FILTER (WHERE TRUE AND TRUE) AS DOUBLE) / NULLIF(COALESCE(COUNT("review_score") FILTER (WHERE TRUE AND TRUE), 0), 0), 2) AS "avg_review_score"
FROM "silver_reviews"
WHERE NOT "_is_deleted"
GROUP BY ALL
HAVING (COUNT(*) FILTER (WHERE TRUE) > 0)
ORDER BY 1;
