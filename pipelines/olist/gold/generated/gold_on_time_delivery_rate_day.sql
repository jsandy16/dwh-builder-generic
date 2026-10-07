-- dwh_core:generated v=1.2.0 template=gold/v1 template_sha=12b6468012dae72c spec_sha=69b5d8c16da66788 body_sha=de03edf111c327ee1545e91d7a6a47fb1842920e59e1cdf1554bc7d8860be443
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step build
CREATE OR REPLACE TABLE "gold_on_time_delivery_rate_day" AS
SELECT CAST("order_purchase_timestamp" AS DATE) AS "order_purchase_timestamp",
  COUNT(*) FILTER (WHERE TRUE AND COALESCE((order_delivered_customer_date <= order_estimated_delivery_date), FALSE) AND CAST("order_status" AS VARCHAR) IN ('delivered')) AS "on_time_delivery_rate__num",
  COUNT(*) FILTER (WHERE TRUE AND CAST("order_status" AS VARCHAR) IN ('delivered')) AS "on_time_delivery_rate__den",
  ROUND(100 * CAST(COUNT(*) FILTER (WHERE TRUE AND COALESCE((order_delivered_customer_date <= order_estimated_delivery_date), FALSE) AND CAST("order_status" AS VARCHAR) IN ('delivered')) AS DOUBLE) / NULLIF(COALESCE(COUNT(*) FILTER (WHERE TRUE AND CAST("order_status" AS VARCHAR) IN ('delivered')), 0), 0), 1) AS "on_time_delivery_rate"
FROM "silver_orders"
WHERE NOT "_is_deleted"
GROUP BY ALL
HAVING (COUNT(*) FILTER (WHERE TRUE) > 0)
ORDER BY 1;
