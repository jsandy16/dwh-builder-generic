-- dwh_core:generated v=1.2.0 template=gold/v1 template_sha=12b6468012dae72c spec_sha=3280c35f36a7bae8 body_sha=2afe579edf7b4c08578e541718e524b05231989a7f7403be6110fee3cbf36b3e
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step build
CREATE OR REPLACE TABLE "gold_cancellation_rate_day" AS
SELECT CAST("order_purchase_timestamp" AS DATE) AS "order_purchase_timestamp",
  COUNT(*) FILTER (WHERE TRUE AND COALESCE((order_status = 'canceled'), FALSE) AND CAST("order_status" AS VARCHAR) IN ('created', 'approved', 'invoiced', 'processing', 'shipped', 'delivered', 'canceled', 'unavailable')) AS "cancellation_rate__num",
  COUNT(*) FILTER (WHERE TRUE AND CAST("order_status" AS VARCHAR) IN ('created', 'approved', 'invoiced', 'processing', 'shipped', 'delivered', 'canceled', 'unavailable')) AS "cancellation_rate__den",
  ROUND(100 * CAST(COUNT(*) FILTER (WHERE TRUE AND COALESCE((order_status = 'canceled'), FALSE) AND CAST("order_status" AS VARCHAR) IN ('created', 'approved', 'invoiced', 'processing', 'shipped', 'delivered', 'canceled', 'unavailable')) AS DOUBLE) / NULLIF(COALESCE(COUNT(*) FILTER (WHERE TRUE AND CAST("order_status" AS VARCHAR) IN ('created', 'approved', 'invoiced', 'processing', 'shipped', 'delivered', 'canceled', 'unavailable')), 0), 0), 1) AS "cancellation_rate"
FROM "silver_orders"
WHERE NOT "_is_deleted"
GROUP BY ALL
HAVING (COUNT(*) FILTER (WHERE TRUE) > 0)
ORDER BY 1;
