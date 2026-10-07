-- dwh_core:generated v=1.2.0 template=gold/v1 template_sha=12b6468012dae72c spec_sha=39c5d86a5b87e73b body_sha=011c36cb807460a8a4ba91ddd31a18d3c1d09cba445d34e4dde12b76c513b979
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step build
CREATE OR REPLACE TABLE "gold_avg_order_value_day" AS
SELECT CAST("ord_order_purchase_timestamp" AS DATE) AS "ord_order_purchase_timestamp",
  SUM("price") FILTER (WHERE COALESCE((ord_order_status NOT IN ('canceled', 'unavailable')), FALSE) AND TRUE) AS "avg_order_value__num",
  COUNT(DISTINCT "order_id") FILTER (WHERE COALESCE((ord_order_status NOT IN ('canceled', 'unavailable')), FALSE) AND TRUE) AS "avg_order_value__den",
  ROUND(1 * CAST(SUM("price") FILTER (WHERE COALESCE((ord_order_status NOT IN ('canceled', 'unavailable')), FALSE) AND TRUE) AS DOUBLE) / NULLIF(COALESCE(COUNT(DISTINCT "order_id") FILTER (WHERE COALESCE((ord_order_status NOT IN ('canceled', 'unavailable')), FALSE) AND TRUE), 0), 0), 2) AS "avg_order_value"
FROM "silver_order_items"
WHERE NOT "_is_deleted"
GROUP BY ALL
HAVING (COUNT(*) FILTER (WHERE COALESCE((ord_order_status NOT IN ('canceled', 'unavailable')), FALSE)) > 0)
ORDER BY 1;
