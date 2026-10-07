"""Independent golden values for the Olist KPIs — reads the RAW batch_01 CSVs with pandas.

    python gold/checks/golden_independent.py data/raw/batch_01 gold/checks/golden_values.csv

Uses none of the warehouse's code, SQL or cleaning: the KPI definitions are re-implemented here
from the metric cards' plain-language definitions. The output is evidence for the PO, who decided
the golden values recorded in gold/specs/metrics/*.yaml (golden_values)."""
import sys
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd

D = sys.argv[1]
orders = pd.read_csv(f"{D}/olist_orders_dataset.csv", dtype=str)
items = pd.read_csv(f"{D}/olist_order_items_dataset.csv", dtype=str)
cust = pd.read_csv(f"{D}/olist_customers_dataset.csv", dtype=str)
rev = pd.read_csv(f"{D}/olist_order_reviews_dataset.csv", dtype=str)
for c in ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
          "order_delivered_customer_date", "order_estimated_delivery_date"]:
    orders[c] = pd.to_datetime(orders[c])
# business rules from the Data quality tab (impossible rows are not part of any KPI)
bad = ((orders.order_delivered_carrier_date < orders.order_approved_at) |
       ((orders.order_status == "delivered") & orders.order_delivered_customer_date.isna()))
print(f"orders rejected by the two rules: {int(bad.sum())}")
orders = orders[~bad].copy()
orders["day"] = orders.order_purchase_timestamp.dt.strftime("%Y-%m-%d")
orders = orders.merge(cust[["customer_id", "customer_state"]], on="customer_id", how="left")
items = items[items.order_id.isin(orders.order_id)].merge(orders[["order_id", "day", "order_status"]], on="order_id")
items["price"] = items.price.astype(float)

def r(x, n):
    return str(Decimal(str(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))

out = []
# orders_placed: count per (purchase day, customer state)
op = orders.groupby(["day", "customer_state"]).size().sort_values(ascending=False)
top_day = orders.day.value_counts().idxmax()
picks = [(top_day, "SP"), (top_day, "RJ"), (orders.day.value_counts().index[10], "MG")]
for d, s in picks:
    out.append(("orders_placed", f"order_purchase_timestamp={d}; cust_customer_state={s}", str(int(op.get((d, s), 0))),
                f"count of orders purchased on {d} by customers in {s}"))
# gmv / avg_order_value: items of orders not canceled/unavailable, by purchase day
ok = items[~items.order_status.isin(["canceled", "unavailable"])]
g = ok.groupby("day").agg(gmv=("price", "sum"), n=("order_id", "nunique"))
days = list(g.sort_values("gmv", ascending=False).index)
for d in (days[0], days[len(days) // 2], days[-5]):
    out.append(("gmv", f"ord_order_purchase_timestamp={d}", r(g.loc[d, "gmv"], 2),
                f"sum of item price for {g.loc[d, 'n']} orders purchased {d}, canceled/unavailable excluded"))
    out.append(("avg_order_value", f"ord_order_purchase_timestamp={d}", r(g.loc[d, "gmv"] / g.loc[d, "n"], 2),
                f"{r(g.loc[d, 'gmv'], 2)} ÷ {g.loc[d, 'n']} orders"))
# on_time_delivery_rate: delivered orders delivered on/before estimate ÷ delivered orders, by purchase day
dl = orders[orders.order_status == "delivered"].copy()
dl["ontime"] = dl.order_delivered_customer_date <= dl.order_estimated_delivery_date
t = dl.groupby("day").agg(n=("ontime", "size"), k=("ontime", "sum"))
late_days = list(t[t.k < t.n].sort_values("n", ascending=False).index)
for d in (late_days[0], late_days[1], late_days[len(late_days) // 2]):
    out.append(("on_time_delivery_rate", f"order_purchase_timestamp={d}", r(100 * t.loc[d, "k"] / t.loc[d, "n"], 1),
                f"{int(t.loc[d, 'k'])} on time of {int(t.loc[d, 'n'])} delivered orders purchased {d}, ×100"))
# avg_review_score: by review creation day
rev["day"] = pd.to_datetime(rev.review_creation_date).dt.strftime("%Y-%m-%d")
rev["review_score"] = rev.review_score.astype(int)
a = rev.groupby("day").agg(s=("review_score", "sum"), n=("review_score", "size")).sort_values("n", ascending=False)
for d in (a.index[0], a.index[5], a.index[20]):
    out.append(("avg_review_score", f"review_creation_date={d}", r(a.loc[d, "s"] / a.loc[d, "n"], 2),
                f"{int(a.loc[d, 's'])} points ÷ {int(a.loc[d, 'n'])} reviews created {d}"))
# cancellation_rate: canceled ÷ all orders, by purchase day
c = orders.groupby("day").agg(n=("order_status", "size"), k=("order_status", lambda s: (s == "canceled").sum()))
cd = list(c[c.k > 0].sort_values("n", ascending=False).index)
for d in (cd[0], cd[1], c.sort_values("n", ascending=False).index[0] if c.sort_values("n", ascending=False).index[0] not in cd[:2] else cd[2]):
    out.append(("cancellation_rate", f"order_purchase_timestamp={d}", r(100 * c.loc[d, "k"] / c.loc[d, "n"], 1),
                f"{int(c.loc[d, 'k'])} canceled of {int(c.loc[d, 'n'])} orders purchased {d}, ×100"))
pd.DataFrame(out, columns=["kpi", "key", "value", "how"]).to_csv(sys.argv[2], index=False)
for row in out:
    print(" | ".join(row))
