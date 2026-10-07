"""Domain 2 — taxi-style warehouse (the plan's second acceptance domain), synthetic data.

yellow trips (CSV, monthly batches) + green trips (Parquet, different column names, no airport
fee) → one conformed `trips` entity with a zone lookup; zones (CSV, full refresh) → reference.
Exercises: multi-source conformance, mapping NULL → structural-null decision, imputation +
population statements, lookups with missing codes, flags, valid anomalies vs hard rejects,
planted-truth scoring (V21), a hand-made edge batch, re-delivery (partition replace), every
bronze ingress gate, retry, fault injection (V17), an independent pandas oracle and determinism.
"""
from __future__ import annotations

import glob
import hashlib
import json
import shutil
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import RUNS, Fail, check, duck, dwh, install, loc, results, say  # noqa: E402

TS = "%Y-%m-%d %H:%M:%S"
YCOLS = ["VendorID", "tpep_pickup_datetime", "tpep_dropoff_datetime", "passenger_count", "trip_distance",
         "PULocationID", "DOLocationID", "payment_type", "fare_amount", "tip_amount", "total_amount", "airport_fee"]
TYPES = {"VendorID": "INTEGER", "passenger_count": "INTEGER", "trip_distance": "DOUBLE", "PULocationID": "INTEGER",
         "DOLocationID": "INTEGER", "payment_type": "INTEGER", "fare_amount": "DECIMAL(10,2)",
         "tip_amount": "DECIMAL(10,2)", "total_amount": "DECIMAL(10,2)", "airport_fee": "DECIMAL(10,2)"}
PAY = ["1", "2", "3", "4", "5", "6"]


def schema(prefix: str, airport: bool) -> dict:
    cols = {}
    for c in YCOLS:
        if c == "airport_fee" and not airport:
            continue
        name = c.replace("tpep_", prefix)
        t = "TIMESTAMP" if "datetime" in c else TYPES[c]
        spec = {"type": t, "required": "yes" if c not in ("airport_fee",) else "no"}
        if c == "payment_type":
            spec["allowed_values"] = PAY
        cols[name] = spec
    return cols


def answers(root: Path) -> None:
    say(root, "people", {"dana": {"name": "Dana", "roles": ["DE"]}, "priya": {"name": "Priya", "roles": ["PO"]},
                         "sam": {"name": "Sam", "roles": ["SME"]}, "gina": {"name": "Gina", "roles": ["GOV"]}}, "dana")
    for k, v in (("name", "nyc-taxi-test"), ("profile", "fast"), ("builder", "dana")):
        say(root, f"project.{k}", v, "dana")
    say(root, "policies.compliance", "none", "gina")
    say(root, "policies.egress", "stats_only", "gina")
    for k, v in (("timezone.reporting", "America/New_York"), ("calendar.type", "gregorian"),
                 ("calendar.week_start", "monday"), ("money.scale", "2")):
        say(root, f"policies.{k}", v, "priya")
    common = {"connector": "local_file", "freshness": {"basis": "batch_token", "token_format": "%Y-%m",
                                                       "window_days": "1200"},
              "volume": {"min_rows": "NA", "max_rows": "NA"}, "retry_attempts": "3", "credentials_env": "NA",
              "drift_policy": "land_and_log", "profile_split_by": "NA", "redelivery_policy": "replace",
              "load_type": "incremental_append", "role": "fact"}
    say(root, "sources.yellow", {**common, "location": "data/raw/yellow_{batch}.csv", "format": "csv",
                                 "csv": {"delimiter": ",", "header": "yes", "quote": '"', "escape": '"',
                                         "encoding": "utf-8", "null_tokens": "NA"},
                                 "schema": {"columns": schema("tpep_", True)}}, "dana")
    say(root, "sources.green", {**common, "location": "data/raw/green_{batch}.parquet", "format": "parquet",
                                "schema": {"columns": schema("lpep_", False)}}, "dana")
    say(root, "sources.zones", {"role": "reference", "connector": "local_file", "location": "data/raw/zones.csv",
                                "format": "csv", "csv": {"delimiter": ",", "header": "yes", "quote": '"',
                                                         "escape": '"', "encoding": "utf-8", "null_tokens": "NA"},
                                "schema": {"columns": {"LocationID": {"type": "INTEGER", "required": "yes", "key": "yes"},
                                                       "Borough": {"type": "VARCHAR", "required": "yes"},
                                                       "Zone": {"type": "VARCHAR", "required": "yes"},
                                                       "service_zone": {"type": "VARCHAR", "required": "yes"}}},
                                "load_type": "full_refresh", "freshness": {"basis": "none"},
                                "volume": {"min_rows": "10", "max_rows": "300", "threshold_source": "owner"},
                                "retry_attempts": "default", "credentials_env": "NA", "drift_policy": "reject",
                                "profile_split_by": "NA"}, "dana")
    for s, cols in (("yellow", schema("tpep_", True)), ("green", schema("lpep_", False)),
                    ("zones", {"LocationID": 1, "Borough": 1, "Zone": 1, "service_zone": 1})):
        for c in cols:
            say(root, f"sources.{s}.schema.columns.{c}.classification", "internal", "gina")
    # ---- silver: zones reference, trips conformed from two sources
    say(root, "silver.entities.zones", {
        "sources": ["zones"],
        "columns": {"location_id": {"type": "INTEGER"}, "borough": {"type": "VARCHAR"},
                    "zone": {"type": "VARCHAR"}, "service_zone": {"type": "VARCHAR"}},
        "mapping": {"zones": {"location_id": "LocationID", "borough": "Borough", "zone": "Zone",
                              "service_zone": "service_zone"}},
        "natural_key": ["location_id"], "tiebreaker": ["zone ASC"],
        "merge": {"strategy": "partition_replace", "partition_column": "NA"},
        "flags": "NA", "lookups": "NA", "drop_columns": "NA", "target_table": "NA"}, "dana")
    canon = {"vendor_id": "VendorID", "pickup_ts": "tpep_pickup_datetime", "dropoff_ts": "tpep_dropoff_datetime",
             "passenger_count": "passenger_count", "trip_distance": "trip_distance", "pu_zone": "PULocationID",
             "do_zone": "DOLocationID", "payment_type": "payment_type", "fare_amount": "fare_amount",
             "tip_amount": "tip_amount", "total_amount": "total_amount", "airport_fee": "airport_fee"}
    ccols = {}
    for c, src in canon.items():
        t = "TIMESTAMP" if c.endswith("_ts") else TYPES[src]
        ccols[c] = {"type": t}
        if t == "TIMESTAMP":
            ccols[c].update(formats=[TS], source_timezone="America/New_York")
    green_map = {c: v.replace("tpep_", "lpep_") for c, v in canon.items()}
    green_map["airport_fee"] = "NULL"
    say(root, "silver.entities.trips", {
        "sources": ["yellow", "green"], "columns": ccols,
        "mapping": {"yellow": canon, "green": green_map},
        "natural_key": ["vendor_id", "pickup_ts", "dropoff_ts", "pu_zone", "do_zone"],
        "tiebreaker": ["total_amount DESC"],
        "merge": {"strategy": "partition_replace", "partition_column": "NA"},
        "lookups": {"pu": {"reference": "zones", "on": {"pu_zone": "location_id"}, "columns": ["borough"]}},
        "drop_columns": "NA", "target_table": "silver_trips"}, "dana")
    say(root, "silver.entities.trips.lookups.pu.missing", "reject", "sam")
    say(root, "silver.entities.trips.flags", {"is_airport_trip": "pu_zone IN (1, 132, 138)"}, "sam")
    sme = "sam"
    for e, pol in (("zones", "keep_last_good"), ("trips", "keep_last_good")):
        say(root, f"silver.entities.{e}.rejected_survivor_policy", pol, sme)
    say(root, "silver.entities.zones.null_policy", {"location_id": "drop", "borough": "keep", "zone": "keep",
                                                    "service_zone": "keep"}, sme)
    say(root, "silver.entities.trips.null_policy", {
        "vendor_id": "drop", "pickup_ts": "drop", "dropoff_ts": "drop", "passenger_count": "impute:1",
        "trip_distance": "keep", "pu_zone": "drop", "do_zone": "drop", "payment_type": "keep",
        "fare_amount": "drop", "tip_amount": "impute:0", "total_amount": "drop", "airport_fee": "keep"}, sme)
    say(root, "silver.entities.trips.structural_nulls", {"airport_fee|source=green": "structural"}, sme)
    say(root, "silver.entities.zones.valid_anomalies", "none", sme)
    say(root, "silver.entities.zones.hard_rejects", "none", sme)
    say(root, "silver.entities.trips.valid_anomalies",
        {"refund": {"predicate": "total_amount < 0", "reason": "voided or refunded trips carry negative amounts"}}, sme)
    say(root, "silver.entities.trips.hard_rejects",
        {"impossible_time": {"predicate": "dropoff_ts < pickup_ts", "reason": "dropoff_before_pickup"},
         "absurd_distance": {"predicate": "trip_distance > 500", "reason": "distance_over_500mi"}}, sme)
    for e in ("zones", "trips"):
        say(root, f"silver.entities.{e}.dead_letter_tolerance_pct", "12", "priya")
        say(root, f"silver.entities.{e}.tolerance_source", "synthetic", "priya")
    # ---- gold
    base = {"entity": "trips", "date_basis": "pickup_ts", "cadence": "daily", "version": "1.0.0",
            "effective_from": "2024-01-01", "precision": "2"}
    say(root, "metrics.trips", {**base, "plain_definition": "Completed trips per pickup day and borough.",
                                "unit": "count", "precision": "0", "additivity": "additive", "population": "NA",
                                "valid_range": {"min": "0", "max": "none"},
                                "reconciliation": {"control": "count", "excluded_by": "none", "max_excluded_pct": "0"},
                                "target_table": "gold_daily_borough"}, "dana")
    say(root, "metrics.revenue", {**base, "plain_definition": "Total amount charged per pickup day and borough.",
                                  "unit": "currency:USD", "additivity": "additive", "population": "NA",
                                  "valid_range": {"min": "none", "max": "none"},
                                  "reconciliation": {"control": "sum:total_amount", "excluded_by": "none",
                                                     "max_excluded_pct": "0"},
                                  "target_table": "gold_daily_borough"}, "dana")
    say(root, "metrics.tip_rate", {**base, "plain_definition": "Share of card trips with a tip, per pickup day.",
                                   "unit": "percent", "additivity": "non_additive",
                                   "valid_range": {"min": "0", "max": "100"},
                                   "reconciliation": {"control": "count",
                                                      "excluded_by": "payment_type IS NULL OR payment_type <> 1",
                                                      "max_excluded_pct": "90"},
                                   "target_table": "gold_tip_rate"}, "dana")
    po = "priya"
    for m, mt, num, flt, filters, grain in (
            ("trips", "count", "count", "none", "none", ["pickup_ts", "pu_borough"]),
            ("revenue", "sum", "sum:total_amount", "none", "none", ["pickup_ts", "pu_borough"]),
            ("tip_rate", "ratio", "count", "tip_amount > 0", "payment_type IS NOT NULL", ["pickup_ts"])):
        say(root, f"metrics.{m}.metric_type", mt, po)
        say(root, f"metrics.{m}.numerator.measure", num, po)
        say(root, f"metrics.{m}.numerator.filter", flt, po)
        say(root, f"metrics.{m}.filters", filters, po)
        say(root, f"metrics.{m}.grain", grain, po)
        say(root, f"metrics.{m}.time_grain", "day", po)
        say(root, f"metrics.{m}.dispute_owner", "priya", po)
    say(root, "metrics.tip_rate.denominator.measure", "count", po)
    say(root, "metrics.tip_rate.denominator.include.column", "payment_type", po)
    say(root, "metrics.tip_rate.denominator.include.values", ["1"], po)
    say(root, "metrics.tip_rate.denominator.exclude.values", ["2", "3", "4", "5", "6"], po)
    say(root, "metrics.tip_rate.zero_denominator", "null", po)
    say(root, "serve", {"title": "NYC taxi (synthetic test)", "audience": "Ops review", "runtime": "streamlit",
                        "reference_clock": "replay",
                        "kpis": {"trips": {"metric": "trips", "label": "Trips"},
                                 "rev": {"metric": "revenue", "label": "Revenue"},
                                 "tips": {"metric": "tip_rate", "label": "Card trips with a tip"}},
                        "charts": {"trips_by_borough": {"type": "line", "metric": "trips", "x": "pickup_ts",
                                                        "color": "pu_borough", "title": "Trips by borough"},
                                   "tip_trend": {"type": "line", "metric": "tip_rate", "x": "pickup_ts",
                                                 "color": "NA"}},
                        "filters": ["pu_borough"], "port": "NA", "auto_refresh_seconds": "NA"}, po)
    say(root, "serve.row_security", "none", "gina")
    # ---- synthetic data spec
    hint = {"VendorID": {"choices": ["1", "2"]}, "PULocationID": {"range": ["1", "30"]},
            "DOLocationID": {"range": ["1", "30"]}, "passenger_count": {"range": ["1", "4"]},
            "trip_distance": {"range": ["0.5", "25"]}, "fare_amount": {"range": ["3", "80"]},
            "tip_amount": {"range": ["0", "12"]}, "total_amount": {"range": ["-10", "120"]},
            "airport_fee": {"choices": ["0", "1.75"]}}
    yh = {**hint, "tpep_dropoff_datetime": {"after": "tpep_pickup_datetime", "minutes": ["2", "70"]}}
    gh = {k.replace("tpep_", "lpep_"): v for k, v in hint.items() if k != "airport_fee"}
    gh["lpep_dropoff_datetime"] = {"after": "lpep_pickup_datetime", "minutes": ["2", "70"]}
    say(root, "synthetic.sources", {
        "yellow": {"batches": ["2024-01", "2024-02"], "rows_per_batch": "1500", "seed": "7",
                   "defects": {"null": "2", "cast": "1", "domain": "1", "duplicate": "2"}, "columns": yh},
        "green": {"batches": ["2024-01", "2024-02"], "rows_per_batch": "400", "seed": "11",
                  "defects": {"null": "2", "domain": "1", "duplicate": "1"}, "columns": gh},
        "zones": {"batches": ["full"], "rows_per_batch": "30", "seed": "3", "defects": "none",
                  "columns": {"LocationID": {"sequence": "yes"},
                              "Borough": {"choices": ["Manhattan", "Queens", "Brooklyn", "Bronx", "EWR"]},
                              "service_zone": {"choices": ["Yellow Zone", "Boro Zone", "Airports"]}}}}, "dana")


EDGE = """VendorID,tpep_pickup_datetime,tpep_dropoff_datetime,passenger_count,trip_distance,PULocationID,DOLocationID,payment_type,fare_amount,tip_amount,total_amount,airport_fee
1,2024-03-01 08:00:00,2024-03-01 08:20:00,1,3.2,5,7,1,15.00,3.00,20.00,0
2,2024-03-01 09:00:00,2024-03-01 08:50:00,1,1.0,5,7,1,5.00,0,6.00,0
1,2024-03-02 10:00:00,2024-03-02 10:30:00,2,4.0,999,7,2,20.00,0,22.00,0
2,2024-03-02 11:00:00,2024-03-02 11:05:00,1,0.5,6,6,4,-5.00,0,-5.80,0
1,2024-03-01 08:00:00,2024-03-01 08:20:00,1,3.2,5,7,1,15.00,3.00,20.00,0
1,2024-03-01 08:00:00,2024-03-01 08:20:00,1,3.2,5,7,1,15.00,4.00,21.00,0
1,2024-03-03
1,2024-03-03 12:00:00,2024-03-03 12:10:00,,1.1,8,9,1,7.00,,9.00,0
2,2024-03-04 07:00:00,2024-03-04 07:45:00,1,18.0,1,10,1,60.00,10.00,75.00,1.75
1,03/05/2024 10:00,2024-03-05 10:20:00,1,2.0,4,4,1,9.00,1.00,11.00,0
"""
# expected for the edge batch: 11 records → 1 unparseable (bronze) + 10 landed;
# silver: dropoff_before_pickup 1, missing_pu 1, cast_pickup_ts 1 → 3 dead-lettered;
# duplicates 2 (rows 1 and 5 lose to row 6, total 21 > 20); survivors 5.


def oracle(root: Path) -> dict:
    """Independent pandas implementation of the trips entity and the three metric cards."""
    zones = pd.read_csv(root / "data/raw/zones.csv", dtype=str, keep_default_na=False).replace({"": None})
    zones["LocationID"] = pd.to_numeric(zones["LocationID"], errors="coerce")
    zmap = dict(zip(zones["LocationID"], zones["Borough"]))
    frames = []
    for f in sorted(glob.glob(str(root / "data/raw/yellow_*.csv"))):
        b = Path(f).stem.split("_", 1)[1]
        rows = []
        import csv as _csv
        with open(f, encoding="utf-8") as fh:
            rdr = _csv.reader(fh)
            header = next(rdr)
            for i, r in enumerate(rdr, start=1):
                if len(r) != len(header):
                    continue  # unparseable record (bronze parse dead-letter)
                rows.append(dict(zip(header, r)) | {"_row": i, "_file": Path(f).name, "_src": "yellow", "_b": b})
        frames.append(pd.DataFrame(rows))
    for f in sorted(glob.glob(str(root / "data/raw/green_*.parquet"))):
        g = pd.read_parquet(f)
        g = g.rename(columns=lambda c: c.replace("lpep_", "tpep_"))
        g["airport_fee"] = None
        g["_row"] = range(1, len(g) + 1)
        g["_file"] = Path(f).name
        g["_src"] = "green"
        g = g.astype(object).where(g.notna(), None)
        for c in g.columns:
            if c.endswith("datetime"):
                g[c] = g[c].map(lambda v: None if v is None else pd.Timestamp(v).strftime(TS))
            elif c not in ("_row",):
                g[c] = g[c].map(lambda v: None if v is None else (
                    format(v, "f") if isinstance(v, Decimal) else
                    str(int(v)) if isinstance(v, float) and v == int(v) and c in TYPES and TYPES[c] == "INTEGER"
                    else str(v)))
        frames.append(g)
    df = pd.concat(frames, ignore_index=True).replace({"": None})
    reason = pd.Series([None] * len(df), dtype=object)

    def setr(mask, r):
        m = mask & reason.isna()
        reason[m] = r

    num = {}
    for c, t in TYPES.items():
        num[c] = df[c].map(lambda v: _num(v, t))
    pick = pd.to_datetime(df["tpep_pickup_datetime"], format=TS, errors="coerce")
    drop = pd.to_datetime(df["tpep_dropoff_datetime"], format=TS, errors="coerce")
    key_cols = {"VendorID": "vendor_id", "tpep_pickup_datetime": "pickup_ts", "tpep_dropoff_datetime": "dropoff_ts",
                "PULocationID": "pu_zone", "DOLocationID": "do_zone"}
    typed = {"VendorID": num["VendorID"], "tpep_pickup_datetime": pick, "tpep_dropoff_datetime": drop,
             "PULocationID": num["PULocationID"], "DOLocationID": num["DOLocationID"]}
    for c, canon in key_cols.items():
        setr(df[c].notna() & typed[c].isna(), f"cast_{canon}")
    setr(pd.concat([typed[c].isna() for c in key_cols], axis=1).any(axis=1), "null_key")
    for c, canon in (("passenger_count", "passenger_count"), ("trip_distance", "trip_distance"),
                     ("payment_type", "payment_type"), ("fare_amount", "fare_amount"), ("tip_amount", "tip_amount"),
                     ("total_amount", "total_amount"), ("airport_fee", "airport_fee")):
        setr(df[c].notna() & num[c].isna(), f"cast_{canon}")
    setr(num["fare_amount"].isna(), "null_fare_amount")
    setr(num["total_amount"].isna(), "null_total_amount")
    setr(df["payment_type"].notna() & ~df["payment_type"].map(lambda v: str(v).strip() in PAY), "domain_payment_type")
    setr(drop < pick, "dropoff_before_pickup")
    setr(num["trip_distance"].map(lambda v: v is not None and v > 500), "distance_over_500mi")
    setr(num["PULocationID"].notna() & ~num["PULocationID"].map(lambda v: v in zmap), "missing_pu")
    df["_reason"] = reason
    df["_key"] = list(zip(num["VendorID"], pick, drop, num["PULocationID"], num["DOLocationID"]))
    df["_total"] = num["total_amount"]
    good = df[df["_reason"].isna()].copy()
    good["_tot_sort"] = good["_total"].map(lambda v: float(v))
    good = good.sort_values(["_tot_sort", "_file", "_row"], ascending=[False, False, False])
    surv = good.drop_duplicates("_key", keep="first").copy()
    surv["pickup_date"] = pick[surv.index].dt.date
    surv["borough"] = num["PULocationID"][surv.index].map(zmap)
    surv["total"] = num["total_amount"][surv.index]
    surv["tip"] = num["tip_amount"][surv.index].map(lambda v: Decimal(0) if v is None else v)
    surv["pay"] = num["payment_type"][surv.index]
    trips = surv.groupby(["pickup_date", "borough"]).size()
    revenue = surv.groupby(["pickup_date", "borough"])["total"].sum()
    tip = {}
    for d, x in surv.groupby("pickup_date"):
        den = (x["pay"] == 1).sum()
        n = ((x["pay"] == 1) & (x["tip"] > 0)).sum()
        tip[d] = None if den == 0 else round(100.0 * n / den, 2)
    return {"silver_rows": len(surv), "dl": df["_reason"].value_counts().to_dict(), "trips": trips,
            "revenue": revenue, "tip": tip}


def _num(v, t):
    if v is None:
        return None
    s = str(v).strip()
    try:
        if t.startswith("DECIMAL"):
            return Decimal(s).quantize(Decimal("0.01"))
        if t == "DOUBLE":
            return float(s)
        import re as _re
        return int(s) if _re.fullmatch(r"[+-]?[0-9]+", s) else None
    except Exception:
        return None


def golden(root: Path, O: dict) -> None:
    tk = sorted(O["trips"].index)
    picks = [tk[0], tk[len(tk) // 2], tk[-1]]
    say(root, "metrics.trips.golden_values",
        [{"key": {"pickup_ts": str(d), "pu_borough": b}, "value": str(int(O["trips"][(d, b)]))} for d, b in picks],
        "priya")
    say(root, "metrics.revenue.golden_values",
        [{"key": {"pickup_ts": str(d), "pu_borough": b}, "value": str(O["revenue"][(d, b)])} for d, b in picks],
        "priya")
    days = sorted(O["tip"])
    say(root, "metrics.tip_rate.golden_values",
        [{"key": {"pickup_ts": str(d)}, "value": "null" if O["tip"][d] is None else str(O["tip"][d])}
         for d in (days[0], days[len(days) // 2], days[-1])], "priya")
    say(root, "metrics.tip_rate.population",
        "Card trips (payment_type 1) with a known payment type; missing tips were imputed as 0 and count as no tip.",
        "priya")


def content_hash(root: Path, table: str) -> str:
    rows = duck(root, f"SELECT md5(string_agg(h, ',' ORDER BY h)) FROM (SELECT md5(CAST(to_json(t) AS VARCHAR)) h "
                      f"FROM \"{table}\" t)")
    return rows[0][0]


def run(root: Path, log: list, threads: str | None = None) -> dict:
    extra = {"DWH_THREADS": threads} if threads else None
    install(root)
    answers(root)
    rc, out = dwh(root, "synth", extra_env=extra)
    check("planted" in out, "synthetic files generated from bronze's declared schema with a truth ledger", log)
    (root / "data/raw/yellow_2024-03.csv").write_text(EDGE, encoding="utf-8")
    # retry path (V11): two transient failures, third attempt succeeds
    dwh(root, "build", "bronze", extra_env={**(extra or {}), "DWH_FAULT_FETCH": "2"})
    retries = [json.loads(l) for l in (root / ".dwh/actions.jsonl").read_text().splitlines() if '"bronze.retry"' in l]
    check(len(retries) >= 2 and retries[1]["wait"] > retries[0]["wait"],
          f"retry fired {len(retries)}× with exponential backoff, then succeeded (V11)", log)
    b = results(root, "bronze-verify")
    check(b["passed"], "bronze verification passed incl. records = landed + parse rejects (V09)", log)
    led = json.loads((root / ".dwh/ledger/bronze.json").read_text())
    check(led["yellow|2024-03"]["parse_rejects"] == 1 and led["yellow|2024-03"]["landed"] == 9,
          "edge batch: 1 unparseable record dead-lettered at parse, 9 landed", log)
    rc, out = dwh(root, "build", "bronze", extra_env=extra)
    check("skipped (same content): 6" in out, "re-run skips every batch by content (V08)", log)
    # ingress gates: each bad file rejected, nothing landed, no checkpoint
    before = duck(root, "SELECT COUNT(*) FROM bronze_yellow")[0][0]
    hdr = EDGE.splitlines()[0]
    (root / "data/raw/yellow_2024-04.csv").write_text(hdr + "\n", encoding="utf-8")             # zero rows
    (root / "data/raw/yellow_2024-05.csv").write_text(hdr.replace(",total_amount", "") + "\n" +   # missing required
                                                      "1,2024-05-01 08:00:00,2024-05-01 08:20:00,1,3.2,5,7,1,15.00,3.00,0\n")
    (root / "data/raw/yellow_2019-01.csv").write_text(EDGE.replace("2024-03", "2019-01"), encoding="utf-8")  # stale
    g = pd.read_parquet(root / "data/raw/green_2024-01.parquet")
    g["passenger_count"] = g["passenger_count"].astype(str)
    g.to_parquet(root / "data/raw/green_2024-06.parquet")                                          # type change
    rc, out = dwh(root, "build", "bronze", extra_env=extra)
    rej = pd.read_csv(loc(root, "dead_letter") / "rejected_files.csv")
    reasons = dict(zip(rej["batch"].astype(str), rej["reason"]))
    check(reasons.get("2024-04") == "zero_rows" and reasons.get("2024-05") == "missing_required_columns"
          and reasons.get("2019-01") == "stale_batch" and reasons.get("2024-06") == "type_change",
          f"ingress gates reject zero-row, missing-column, stale and type-changed files ({reasons})", log)
    after = duck(root, "SELECT COUNT(*) FROM bronze_yellow")[0][0]
    led = json.loads((root / ".dwh/ledger/bronze.json").read_text())
    check(after == before and not any(k in led for k in ("yellow|2024-04", "yellow|2024-05", "green|2024-06")),
          "rejected files wrote no rows and no checkpoint", log)
    for f in ("yellow_2024-04.csv", "yellow_2024-05.csv", "yellow_2019-01.csv", "green_2024-06.parquet"):
        (root / "data/raw" / f).unlink()
    # gate B: structural nulls + read-back
    rc, out = dwh(root, "build", "silver", expect=2, extra_env=extra)
    check("readback_confirmed" in out, "silver blocked until the SME confirms the read-back", log)
    rc, out = dwh(root, "intake", "readback", "trips")
    check("dropoff_ts < pickup_ts" in out and "| 1 |" in out, "read-back shows each rule with its match count", log)
    say(root, "silver.entities.trips.readback_confirmed", "yes", "sam")
    # V17: a fault after the merge leaves silver untouched
    rc, out = dwh(root, "build", "silver", expect=1, extra_env={**(extra or {}), "DWH_FAULT": "after_merge"})
    check(duck(root, "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'silver_trips'")[0][0] == 0
          or duck(root, "SELECT COUNT(*) FROM silver_trips")[0][0] == 0,
          "injected fault after merge → transaction rolled back, nothing committed (V17)", log)
    rc, out = dwh(root, "build", "silver", expect=1, extra_env=extra)
    check("TOL-trips/yellow/2024-03" in out,
          "dead-letter tolerance stops the build on the 33%-defect edge batch; earlier batches stay committed", log)
    say(root, "silver.entities.trips.dead_letter_tolerance_pct", "35", "priya")
    say(root, "silver.entities.trips.tolerance_source", "owner", "priya")
    rc, out = dwh(root, "build", "silver", extra_env=extra)
    s = results(root, "silver-verify")
    check(s["passed"], "silver verification passed for every batch of both sources", log)
    O = oracle(root)
    n = duck(root, "SELECT COUNT(*) FROM silver_trips")[0][0]
    check(n == O["silver_rows"], f"silver_trips {n} rows = independent pandas oracle {O['silver_rows']}", log)
    dl = dict(duck(root, "SELECT reason, COUNT(*) FROM silver_dead_letter WHERE entity = 'trips' GROUP BY 1"))
    check(dl == {k: v for k, v in O["dl"].items()}, f"dead-letter reasons {dl} = oracle", log)
    sn = duck(root, "SELECT COUNT(*) FROM silver_trips WHERE _src = 'green' AND airport_fee IS NOT NULL")[0][0]
    check(sn == 0, "structural NULL (green has no airport fee) stays NULL, never imputed", log)
    imp = duck(root, "SELECT COUNT(*) FROM silver_trips WHERE is_passenger_count_imputed AND passenger_count = 1")[0][0]
    check(imp > 0, f"{imp} missing passenger counts imputed and flagged", log)
    edge = duck(root, "SELECT total_amount FROM silver_trips WHERE _batch_id = '2024-03' AND vendor_id = 1 "
                      "AND pickup_ts = TIMESTAMP '2024-03-01 08:00:00'")
    check(edge == [(Decimal("21.00"),)], "within-batch correction: the tiebreaker kept total 21.00 over 20.00", log)
    air = duck(root, "SELECT COUNT(*) FROM silver_trips WHERE is_airport_trip")[0][0]
    check(air >= 1, "business flag is_airport_trip computed", log)
    rc, out = dwh(root, "synth", "--score")
    check(results(root, "synthetic-score")["passed"],
          "planted-truth score: every planted defect dead-lettered with the right reason, no false positives (V21)", log)
    # gold — golden values are typed in by the owner (computed by hand / independently)
    golden(root, O)
    dwh(root, "build", "gold", extra_env=extra)
    gres = results(root, "gold-verify")
    check(gres["passed"], "gold verification passed (golden values, reconciliation, population V26)", log)
    got = {(str(d), b): int(v) for d, b, v in duck(root, "SELECT pickup_ts, pu_borough, trips FROM gold_daily_borough")}
    want = {(str(d), b): int(v) for (d, b), v in O["trips"].items()}
    check(got == want, "every trips value equals the oracle", log)
    gotr = {(str(d), b): Decimal(str(v)) for d, b, v in duck(root, "SELECT pickup_ts, pu_borough, revenue FROM gold_daily_borough")}
    wantr = {(str(d), b): v for (d, b), v in O["revenue"].items()}
    check(gotr == wantr, "every revenue value equals the oracle (exact DECIMAL)", log)
    gott = {str(d): v for d, v in duck(root, "SELECT pickup_ts, tip_rate FROM gold_tip_rate")}
    check(gott == {str(d): v for d, v in O["tip"].items()}, "every tip_rate value equals the oracle", log)
    hashes = {t: content_hash(root, t) for t in ("silver_trips", "silver_zones", "gold_daily_borough", "gold_tip_rate")}
    # re-delivery: corrected January file → new version replaces the partition
    p = root / "data/raw/yellow_2024-01.csv"
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines[:-50]) + "\n", encoding="utf-8")
    dwh(root, "build", "bronze", extra_env=extra)
    led = json.loads((root / ".dwh/ledger/bronze.json").read_text())
    check(led["yellow|2024-01"]["version"] == 2 and led["yellow|2024-01"]["redelivery"],
          "re-delivered batch with new content landed as version 2 (V08)", log)
    rc, out = dwh(root, "build", "gold", expect=2, extra_env=extra)
    check("silver" in out, "gold refuses to build on stale silver", log)
    before = content_hash(root, "silver_trips")
    dwh(root, "build", "silver", expect=1, extra_env={**(extra or {}), "DWH_FAULT": "after_merge"})
    check(content_hash(root, "silver_trips") == before and
          json.loads((root / ".dwh/ledger/silver.json").read_text())["trips"]["sources"]["yellow"]["2024-01"]["version"] == 1,
          "fault injected mid-merge of the re-delivery → silver content and ledger unchanged (V17)", log)
    dwh(root, "build", "silver", extra_env=extra)
    O2 = oracle_after_redelivery(root)
    n2 = duck(root, "SELECT COUNT(*) FROM silver_trips")[0][0]
    v2 = duck(root, "SELECT COUNT(*) FROM silver_trips WHERE _src='yellow' AND _batch_id='2024-01' AND _batch_version=2")[0][0]
    check(n2 == O2["silver_rows"] and v2 > 0 and duck(root, "SELECT COUNT(*) FROM silver_trips WHERE _src='yellow' "
                                                           "AND _batch_id='2024-01' AND _batch_version=1")[0][0] == 0,
          f"partition replaced: silver {n2} rows = oracle after re-delivery, no version-1 rows left", log)
    golden(root, O2)
    dwh(root, "build", "gold", extra_env=extra)
    dwh(root, "publish")
    rc, out = dwh(root, "serve", "--check", expect=None)
    check(results(root, "serve-check")["passed"], "serve --check passes on the re-delivered data", log)
    gotr = {(str(d), b): Decimal(str(v)) for d, b, v in duck(root, "SELECT pickup_ts, pu_borough, revenue FROM gold_daily_borough")}
    check(gotr == {(str(d), b): v for (d, b), v in O2["revenue"].items()},
          "after re-delivery every revenue value equals the oracle", log)
    hashes2 = {t: content_hash(root, t) for t in ("silver_trips", "silver_zones", "gold_daily_borough", "gold_tip_rate")}
    return {"hashes": hashes, "hashes_after": hashes2}


def oracle_after_redelivery(root: Path) -> dict:
    return oracle(root)


if __name__ == "__main__":
    log: list = []
    root = Path(sys.argv[1] if len(sys.argv) > 1 else RUNS / "d2").resolve()
    try:
        out = run(root, log)
        print(json.dumps(out, indent=1))
    except Fail as e:
        log.append(("FAIL", str(e)))
    for s, m in log:
        print(f"[{s}] {m}")
    sys.exit(0 if all(s == "PASS" for s, _ in log) else 1)
