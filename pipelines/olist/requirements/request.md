# Request — olist

*What was asked. Claude read this (and `source-README.md`) before proposing the intake answers;
nothing in the build reads it.*

## Who is asking, and why

Sandeep (data engineer, also acting as product owner, business-rule owner and governance for this
development build) wants a warehouse and dashboard over the Olist Brazilian e-commerce dataset to
exercise the dwh skills end to end.

## What was asked

> "set up dataware house for the dataset stored at /home/jacksandy/job_search_apply/braz_ecommerce/"
>
> "no need to load all the batches, 1 or 2 batches are enough"

## What the dashboard answers (proposed in the workbook, accepted by the owner)

- How many orders are placed each day, and from which states?
- How much is sold (GMV) and what is the average order value?
- Are orders delivered by the date promised (on-time delivery rate)?
- How satisfied are customers (average review score)?
- How many orders are canceled (cancellation rate)?

## The data

Nine CSV files per batch (orders, order items, payments, reviews, customers, products, sellers,
geolocation, category name translation), delivered in folders `batch_01` … `batch_13`. Development
uses batches 01 and 02. Supplier notes: `source-README.md`.

## Constraints

- Customer ids, zip codes and coordinates are personal data: hashed in silver.
- Reporting time zone: America/Sao_Paulo; currency BRL.
- Governance egress: `stats_only` — Claude sees counts, never data values.
