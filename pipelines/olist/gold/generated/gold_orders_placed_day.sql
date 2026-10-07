-- dwh_core:generated v=1.2.0 template=gold/v1 template_sha=12b6468012dae72c spec_sha=5d2888a21c8cc728 body_sha=be52ceb1f9a1134a7e4070cf8e70167a9ae6631b041920d4a3298b8c04742793
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step build
CREATE OR REPLACE TABLE "gold_orders_placed_day" AS
SELECT CAST("order_purchase_timestamp" AS DATE) AS "order_purchase_timestamp", "cust_customer_state",
  COUNT(*) FILTER (WHERE TRUE AND TRUE) AS "orders_placed"
FROM "silver_orders"
WHERE NOT "_is_deleted"
GROUP BY ALL
HAVING (COUNT(*) FILTER (WHERE TRUE AND TRUE) > 0)
ORDER BY 1, 2;
