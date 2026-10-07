# Interviewing the product owner for a metric card

Ask in this order; each question maps to one card field. Read back the card at the end
(`artefacts/metric-cards.md` after the build, or your own summary before it).

1. **In one sentence, what does this number tell you?** → `plain_definition`
2. **Is it a total, a count of rows, a count of distinct things, a rate, or an average?**
   → `metric_type` (sum / count / distinct_count / ratio / average)
3. **What exactly is added up or counted?** → `numerator.measure` (`sum:mrr_amount`, `count`,
   `count_distinct:account_id`). **Which rows count?** → `numerator.filter` (`status = 'churned'`, or `none`)
4. *(rates)* **Out of what?** → `denominator.measure`. **Which values of which column are in the
   "out of" population?** → `denominator.include.column` + `include.values`. **Which values are
   deliberately left out, and why?** → `exclude.values` (reason into `plain_definition`).
   Every value must be in one list or the other; a new value stops the build until classified.
5. **Are any rows excluded from the metric entirely?** → `filters` (or `none`)
6. **One row per what?** → `grain` (e.g. `[event_date, region, plan_name]`), **bucketed by day /
   week / month?** → `time_grain`, **using which date?** → `date_basis`
7. **When nothing is in the denominator, show blank, zero, or leave the row out?** →
   `zero_denominator` (null / zero / omit). Pooled churn 11.58% vs 10.75% when empty days count
   as 0 — this choice moves headlines.
8. **Can it be summed across rows?** → `additivity`. Totals and counts of unique events: additive.
   Rates and distinct counts across overlapping groups: non_additive. Balances: semi_additive
   (not across time).
9. **Unit and decimals?** → `unit` (count / percent / currency:EUR), `precision`
10. **Lowest and highest plausible values?** → `valid_range` (`none` for an open side)
11. **Who decides if this number is disputed?** → `dispute_owner` (a person in people.yaml)
12. **Give me at least three values you worked out by hand from the raw data** → `golden_values`.
    Suggest keys that exercise edge cases: a refund, a day with only excluded statuses, a small group.
13. *(if any input column is imputed or structurally NULL)* **Which rows count?** → `population`

DE fields: `reconciliation.control` is the silver total the metric ties back to (`sum:<col>` for
sums, `count` for counts and for a ratio's denominator); `excluded_by` is the exact complement of
the metric's filters (`status <> 'active'`), remembering NULLs; `max_excluded_pct` bounds it.

## Worked card (daily MRR)
```yaml
entity: events
plain_definition: Recurring revenue from active subscription events, per day, region and plan.
metric_type: sum                       # ★ PO
numerator: {measure: "sum:mrr_amount", filter: "status = 'active'"}   # ★ PO
filters: none                          # ★ PO
grain: [event_date, region, plan_name] # ★ PO
time_grain: day                        # ★ PO
date_basis: event_date
unit: currency:USD
precision: "2"
additivity: additive
valid_range: {min: none, max: "100000"}
cadence: daily
dispute_owner: priya                   # ★ PO
golden_values:                         # ★ PO, hand-computed
  - {key: {event_date: "2024-01-01", region: APAC, plan_name: Enterprise}, value: "939.52"}
  - {key: {event_date: "2024-05-06", region: LATAM, plan_name: Enterprise}, value: "996.89"}
  - {key: {event_date: "2024-09-10", region: APAC, plan_name: Starter}, value: "29.42"}
version: 1.0.0
effective_from: 2024-01-01
reconciliation: {control: "sum:mrr_amount", excluded_by: "status <> 'active'", max_excluded_pct: "60"}
target_table: gold_daily_mrr_by_plan
```
