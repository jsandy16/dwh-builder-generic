# Lineage

*Generated from the registrations in `governance/lineage.yaml`.*

```mermaid
flowchart LR
    src_categories["categories (csv)"]
    src_customers["customers (csv)"]
    src_geolocation["geolocation (csv)"]
    src_order_items["order_items (csv)"]
    src_orders["orders (csv)"]
    src_payments["payments (csv)"]
    src_products["products (csv)"]
    src_reviews["reviews (csv)"]
    src_sellers["sellers (csv)"]
    bronze_categories["bronze_categories"]
    bronze_customers["bronze_customers"]
    bronze_geolocation["bronze_geolocation"]
    bronze_order_items["bronze_order_items"]
    bronze_orders["bronze_orders"]
    bronze_payments["bronze_payments"]
    bronze_products["bronze_products"]
    bronze_reviews["bronze_reviews"]
    bronze_sellers["bronze_sellers"]
    src_categories -->|land as received| bronze_categories
    src_customers -->|land as received| bronze_customers
    src_geolocation -->|land as received| bronze_geolocation
    src_order_items -->|land as received| bronze_order_items
    src_orders -->|land as received| bronze_orders
    src_payments -->|land as received| bronze_payments
    src_products -->|land as received| bronze_products
    src_reviews -->|land as received| bronze_reviews
    src_sellers -->|land as received| bronze_sellers
    silver_categories["silver_categories"]
    silver_customers["silver_customers"]
    silver_geolocation["silver_geolocation"]
    silver_order_items["silver_order_items"]
    silver_orders["silver_orders"]
    silver_payments["silver_payments"]
    silver_products["silver_products"]
    silver_reviews["silver_reviews"]
    silver_sellers["silver_sellers"]
    dead_letter["dead_letter"]
    bronze_categories -->|type · judge · merge| silver_categories
    bronze_categories -->|rejected rows| dead_letter
    bronze_customers -->|type · judge · merge| silver_customers
    bronze_customers -->|rejected rows| dead_letter
    bronze_geolocation -->|type · judge · merge| silver_geolocation
    bronze_geolocation -->|rejected rows| dead_letter
    bronze_order_items -->|type · judge · merge| silver_order_items
    bronze_order_items -->|rejected rows| dead_letter
    silver_orders -->|lookup ord| silver_order_items
    bronze_orders -->|type · judge · merge| silver_orders
    bronze_orders -->|rejected rows| dead_letter
    silver_customers -->|lookup cust| silver_orders
    bronze_payments -->|type · judge · merge| silver_payments
    bronze_payments -->|rejected rows| dead_letter
    bronze_products -->|type · judge · merge| silver_products
    bronze_products -->|rejected rows| dead_letter
    silver_categories -->|lookup cat| silver_products
    bronze_reviews -->|type · judge · merge| silver_reviews
    bronze_reviews -->|rejected rows| dead_letter
    bronze_sellers -->|type · judge · merge| silver_sellers
    bronze_sellers -->|rejected rows| dead_letter
    gold_avg_order_value_day["gold_avg_order_value_day"]
    gold_avg_review_score_day["gold_avg_review_score_day"]
    gold_cancellation_rate_day["gold_cancellation_rate_day"]
    gold_gmv_day["gold_gmv_day"]
    gold_on_time_delivery_rate_day["gold_on_time_delivery_rate_day"]
    gold_orders_placed_day["gold_orders_placed_day"]
    silver_order_items -->|avg_order_value| gold_avg_order_value_day
    silver_reviews -->|avg_review_score| gold_avg_review_score_day
    silver_orders -->|cancellation_rate| gold_cancellation_rate_day
    silver_order_items -->|gmv| gold_gmv_day
    silver_orders -->|on_time_delivery_rate| gold_on_time_delivery_rate_day
    silver_orders -->|orders_placed| gold_orders_placed_day
    style src_categories fill:#cfe8ff
    style src_customers fill:#cfe8ff
    style src_geolocation fill:#cfe8ff
    style src_order_items fill:#cfe8ff
    style src_orders fill:#cfe8ff
    style src_payments fill:#cfe8ff
    style src_products fill:#cfe8ff
    style src_reviews fill:#cfe8ff
    style src_sellers fill:#cfe8ff
    style bronze_categories fill:#ffd9b3
    style bronze_customers fill:#ffd9b3
    style bronze_geolocation fill:#ffd9b3
    style bronze_order_items fill:#ffd9b3
    style bronze_orders fill:#ffd9b3
    style bronze_payments fill:#ffd9b3
    style bronze_products fill:#ffd9b3
    style bronze_reviews fill:#ffd9b3
    style bronze_sellers fill:#ffd9b3
    style silver_categories fill:#e0e0e0
    style silver_customers fill:#e0e0e0
    style silver_geolocation fill:#e0e0e0
    style silver_order_items fill:#e0e0e0
    style silver_orders fill:#e0e0e0
    style silver_payments fill:#e0e0e0
    style silver_products fill:#e0e0e0
    style silver_reviews fill:#e0e0e0
    style silver_sellers fill:#e0e0e0
    style dead_letter fill:#ffb3b3
    style gold_avg_order_value_day fill:#fff3b0
    style gold_avg_review_score_day fill:#fff3b0
    style gold_cancellation_rate_day fill:#fff3b0
    style gold_gmv_day fill:#fff3b0
    style gold_on_time_delivery_rate_day fill:#fff3b0
    style gold_orders_placed_day fill:#fff3b0
```
