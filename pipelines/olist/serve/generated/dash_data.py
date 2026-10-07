# dwh_core:generated v=1.2.0 template=serve/v1 template_sha=e85d92d4cec5f923 spec_sha=393c5d2223f8ea46 body_sha=c14c06757b44238ef070a86343c1c32d54d6885295eeaad55676c5d389999b84
# DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
"""Dashboard data access: pure functions, testable without Streamlit."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

CONFIG = json.loads('{\n "audience": "Sandeep (developer) and product review",\n "auto_refresh_seconds": null,\n "cards": {\n  "avg_order_value": {\n   "additivity": "non_additive",\n   "date_basis": "ord_order_purchase_timestamp",\n   "grain": [\n    "ord_order_purchase_timestamp"\n   ],\n   "name": "avg_order_value",\n   "precision": 2,\n   "ratio": true,\n   "scale": 1,\n   "table": "gold_avg_order_value_day",\n   "time_grain": "day",\n   "unit": "currency:brl"\n  },\n  "avg_review_score": {\n   "additivity": "non_additive",\n   "date_basis": "review_creation_date",\n   "grain": [\n    "review_creation_date"\n   ],\n   "name": "avg_review_score",\n   "precision": 2,\n   "ratio": true,\n   "scale": 1,\n   "table": "gold_avg_review_score_day",\n   "time_grain": "day",\n   "unit": "score"\n  },\n  "cancellation_rate": {\n   "additivity": "non_additive",\n   "date_basis": "order_purchase_timestamp",\n   "grain": [\n    "order_purchase_timestamp"\n   ],\n   "name": "cancellation_rate",\n   "precision": 1,\n   "ratio": true,\n   "scale": 100,\n   "table": "gold_cancellation_rate_day",\n   "time_grain": "day",\n   "unit": "percent"\n  },\n  "gmv": {\n   "additivity": "additive",\n   "date_basis": "ord_order_purchase_timestamp",\n   "grain": [\n    "ord_order_purchase_timestamp"\n   ],\n   "name": "gmv",\n   "precision": 2,\n   "ratio": false,\n   "scale": 1,\n   "table": "gold_gmv_day",\n   "time_grain": "day",\n   "unit": "currency:brl"\n  },\n  "on_time_delivery_rate": {\n   "additivity": "non_additive",\n   "date_basis": "order_purchase_timestamp",\n   "grain": [\n    "order_purchase_timestamp"\n   ],\n   "name": "on_time_delivery_rate",\n   "precision": 1,\n   "ratio": true,\n   "scale": 100,\n   "table": "gold_on_time_delivery_rate_day",\n   "time_grain": "day",\n   "unit": "percent"\n  },\n  "orders_placed": {\n   "additivity": "additive",\n   "date_basis": "order_purchase_timestamp",\n   "grain": [\n    "order_purchase_timestamp",\n    "cust_customer_state"\n   ],\n   "name": "orders_placed",\n   "precision": 0,\n   "ratio": false,\n   "scale": 1,\n   "table": "gold_orders_placed_day",\n   "time_grain": "day",\n   "unit": "count"\n  }\n },\n "charts": [\n  {\n   "color": null,\n   "metric": "orders_placed",\n   "name": "orders_by_state",\n   "title": "Orders by customer state",\n   "type": "bar",\n   "x": "cust_customer_state"\n  },\n  {\n   "color": null,\n   "metric": "orders_placed",\n   "name": "orders_trend",\n   "title": "Orders per day",\n   "type": "line",\n   "x": "order_purchase_timestamp"\n  },\n  {\n   "color": null,\n   "metric": "gmv",\n   "name": "gmv_trend",\n   "title": "GMV per day",\n   "type": "line",\n   "x": "ord_order_purchase_timestamp"\n  },\n  {\n   "color": null,\n   "metric": "on_time_delivery_rate",\n   "name": "on_time_trend",\n   "title": "On-time delivery per day",\n   "type": "line",\n   "x": "order_purchase_timestamp"\n  }\n ],\n "clock": "replay",\n "filters": [\n  "cust_customer_state"\n ],\n "kpis": [\n  {\n   "label": "Orders placed",\n   "metric": "orders_placed",\n   "name": "orders"\n  },\n  {\n   "label": "GMV (BRL)",\n   "metric": "gmv",\n   "name": "gmv"\n  },\n  {\n   "label": "Average order value (BRL)",\n   "metric": "avg_order_value",\n   "name": "aov"\n  },\n  {\n   "label": "On-time delivery",\n   "metric": "on_time_delivery_rate",\n   "name": "on_time"\n  },\n  {\n   "label": "Average review score",\n   "metric": "avg_review_score",\n   "name": "review"\n  },\n  {\n   "label": "Cancellations",\n   "metric": "cancellation_rate",\n   "name": "cancel"\n  }\n ],\n "port": 8501,\n "stale_after_hours": null,\n "title": "Olist marketplace \\u2014 development (batch 01)"\n}')
POINTER = __import__("os").environ.get("DWH_SERVE_POINTER", "CURRENT")
ROOT = next(p for p in Path(__file__).resolve().parents if (p / "dwh-project.yaml").exists())
SERVING = ROOT / '.dwh/serving'


class SnapshotError(RuntimeError):
    pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def current_snapshot(root=ROOT, pointer=None):
    serving = SERVING if Path(root) == ROOT else Path(root) / '.dwh/serving'
    ptr = serving / (pointer or POINTER)
    if not ptr.exists():
        raise SnapshotError("Nothing has been published yet. Run `dwh publish` after a passing gold build.")
    snap = serving / ptr.read_text(encoding="utf-8").strip()
    mf = snap / "manifest.json"
    if not mf.exists():
        raise SnapshotError(f"{snap.name} has no manifest (incomplete publish).")
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    for t, info in manifest["tables"].items():
        f = snap / info["file"]
        if not f.exists() or _sha256(f) != info["sha256"]:
            raise SnapshotError(f"{t}: file does not match the snapshot manifest; refusing to show it.")
    return snap, manifest


def load_tables(snap, manifest):
    out = {}
    for t, info in manifest["tables"].items():
        df = pd.read_parquet(Path(snap) / info["file"])
        for c in CONFIG["cards"].values():
            if c["table"] == t:
                df[c["date_basis"]] = pd.to_datetime(df[c["date_basis"]])
                for col in [c["name"], c["name"] + "__num", c["name"] + "__den"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
        out[t] = df
    return out


def card(name):
    return CONFIG["cards"][name]


def date_bounds(tables):
    lo = hi = None
    for c in CONFIG["cards"].values():
        s = tables[c["table"]][c["date_basis"]]
        if len(s):
            lo = s.min() if lo is None else min(lo, s.min())
            hi = s.max() if hi is None else max(hi, s.max())
    return (lo.date() if lo is not None else None), (hi.date() if hi is not None else None)


def frame(tables, name, start=None, end=None, filters=None):
    c = card(name)
    df = tables[c["table"]]
    if start is not None:
        df = df[df[c["date_basis"]] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df[c["date_basis"]] <= pd.Timestamp(end)]
    for col, vals in (filters or {}).items():
        if col in df.columns and vals:
            df = df[df[col].astype(str).isin([str(v) for v in vals])]
    return df


def filter_values(tables, col):
    vals = set()
    for c in CONFIG["cards"].values():
        df = tables[c["table"]]
        if col in df.columns:
            vals |= set(df[col].dropna().astype(str))
    return sorted(vals)


def _ratio(c, num, den):
    if not den:
        return None
    return round(c["scale"] * float(num) / float(den), c["precision"])


def kpi(tables, name, start=None, end=None, filters=None):
    """(value, note). Ratios: sum(numerator) / sum(denominator) over the selection, never an average."""
    c = card(name)
    df = frame(tables, name, start, end, filters)
    if df.empty:
        return None, "no data for this selection"
    if c["ratio"]:
        return _ratio(c, df[name + "__num"].sum(), df[name + "__den"].sum()), "recomputed from numerator and denominator"
    if c["additivity"] == "additive":
        return round(float(df[name].sum()), c["precision"]), ""
    latest = df[c["date_basis"]].max()
    return round(float(df.loc[df[c["date_basis"]] == latest, name].sum()), c["precision"]), \
        f"latest {c['time_grain']} ({latest.date()}) — this metric cannot be summed over time"


def chart_frame(tables, chart, start=None, end=None, filters=None):
    name = chart["metric"]
    c = card(name)
    df = frame(tables, name, start, end, filters)
    keys = [chart["x"]] + ([chart["color"]] if chart.get("color") else [])
    if df.empty:
        return pd.DataFrame()
    if c["additivity"] == "semi_additive" and c["date_basis"] not in keys:
        df = df[df[c["date_basis"]] == df[c["date_basis"]].max()]
    if c["ratio"]:
        g = df.groupby(keys, dropna=False)[[name + "__num", name + "__den"]].sum().reset_index()
        g[name] = [_ratio(c, n, d) for n, d in zip(g[name + "__num"], g[name + "__den"])]
    else:
        g = df.groupby(keys, dropna=False)[name].sum(min_count=1).reset_index()
    if chart.get("color"):
        out = g.pivot_table(index=chart["x"], columns=chart["color"], values=name, aggfunc="first", dropna=False)
        if not c["ratio"] and c["additivity"] == "additive":
            out = out.fillna(0)  # nothing recorded = 0 for an additive metric; a ratio stays undefined
    else:
        out = g.set_index(chart["x"])[[name]]
    return out.sort_index()


def freshness(tables, manifest, now=None):
    """(status, text) using the reference clock the owner chose."""
    clock = CONFIG["clock"]
    now = now or datetime.now(timezone.utc)
    if clock == "replay":
        return "replay", "Replayed/historical data — freshness is not alarmed."
    limit = float(CONFIG.get("stale_after_hours") or 0)
    if clock == "load":
        published = datetime.fromisoformat(manifest["published_at"])
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age = (now - published).total_seconds() / 3600
        what = f"published {age:.1f} h ago"
    else:
        lo, hi = date_bounds(tables)
        if hi is None:
            return "stale", "No data."
        age = (now.date() - hi).days * 24
        what = f"newest data {hi} ({age / 24:.0f} days ago)"
    if limit and age > limit:
        return "stale", f"STALE — {what}; expected within {limit:.0f} h."
    return "fresh", f"Fresh — {what}."


def fmt(name, v):
    c = card(name)
    if v is None:
        return "—"
    p = c["precision"]
    if c["unit"] == "percent":
        return f"{v:,.{p}f}%"
    if c["unit"].startswith("currency:"):
        return f"{c['unit'].split(':', 1)[1].upper()} {v:,.{p}f}"
    return f"{v:,.{p}f}"
