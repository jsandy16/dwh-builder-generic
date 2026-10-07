-- dwh_core:generated v=1.2.0 template=gold/v1 template_sha=12b6468012dae72c spec_sha=f997838371ac18a1 body_sha=0fee4a6533bf007c9ead4f1c696ff557c06856775618f4a5b7784bd362f23b43
-- DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
-- @step build
CREATE OR REPLACE TABLE "gold_gmv_day" AS
SELECT CAST("ord_order_purchase_timestamp" AS DATE) AS "ord_order_purchase_timestamp",
  ROUND(SUM("price") FILTER (WHERE COALESCE((ord_order_status NOT IN ('canceled', 'unavailable')), FALSE) AND TRUE), 2) AS "gmv"
FROM "silver_order_items"
WHERE NOT "_is_deleted"
GROUP BY ALL
HAVING (COUNT(*) FILTER (WHERE COALESCE((ord_order_status NOT IN ('canceled', 'unavailable')), FALSE) AND TRUE) > 0)
ORDER BY 1;
