"""Domain 1 — the Module 700 pack sample (SaaS subscription events), end to end through ./dwh.

Oracle (frozen from the executed pack sample, see 03-sample-project/artefacts):
  bronze 515 rows · 17 NULL mrr dead-lettered · 15 duplicate event_ids · silver 483
  gold_daily_mrr_by_plan 384 rows · churn_rate NULL on days with only trialing events
Golden values are computed independently in pandas from the raw CSV (not through the warehouse).
Documented delta vs the pack: money is DECIMAL(18,2) (pack used DOUBLE), so sums are exact.
"""
from __future__ import annotations

import shutil
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import PACK_SAMPLE, RUNS, Fail, check, duck, dwh, install, results, say  # noqa: E402

RAW = PACK_SAMPLE
FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%b %d %Y"]


def oracle() -> dict:
    """Independent pandas implementation of the pack's cleaning + metric cards."""
    df = pd.read_csv(RAW, dtype=str, keep_default_na=False)
    df = df.replace({"": None})

    def parse(v):
        for f in FORMATS:
            try:
                return pd.to_datetime(v, format=f).date()
            except (ValueError, TypeError):
                continue
        return None

    df["event_date"] = df["event_date"].map(parse)
    df = df[df["mrr_amount"].notna()].copy()
    df["account_id"] = df["account_id"].astype(int)
    df = df.sort_values(["event_id", "account_id"], ascending=[True, False]).drop_duplicates("event_id")
    df["mrr"] = df["mrr_amount"].map(Decimal)
    act = df[df["status"] == "active"]
    mrr = act.groupby(["event_date", "region", "plan_name"])["mrr"].sum()
    cnt = act.groupby(["event_date", "region", "plan_name"])["event_id"].nunique()
    g = df.groupby("event_date")
    churn = {}
    for d, x in g:
        den = (x["status"].isin(["active", "churned"])).sum()
        num = (x["status"] == "churned").sum()
        churn[d] = None if den == 0 else round(100.0 * num / den, 2)
    return {"silver_rows": len(df), "mrr": mrr, "cnt": cnt, "churn": churn,
            "null_churn_days": sum(1 for v in churn.values() if v is None)}


def answers(root: Path, O: dict, golden: bool = True) -> None:
    # ---------------- people and project (DE), policies (GOV/PO)
    say(root, "people", {"dana": {"name": "Dana Engineer", "roles": ["DE"]},
                         "priya": {"name": "Priya Product", "roles": ["PO"]},
                         "sam": {"name": "Sam Steward", "roles": ["SME"]},
                         "gina": {"name": "Gina Governance", "roles": ["GOV"]}}, "dana")
    say(root, "project.name", "subscriptions-mrr", "dana")
    say(root, "project.profile", "fast", "dana")
    say(root, "project.builder", "dana", "dana")
    say(root, "policies.compliance", "none", "gina")
    say(root, "policies.egress", "stats_only", "gina")
    say(root, "policies.timezone.reporting", "UTC", "priya")
    say(root, "policies.calendar.type", "gregorian", "priya")
    say(root, "policies.calendar.week_start", "monday", "priya")
    say(root, "policies.money.scale", "2", "priya")
    # ---------------- bronze (DE) — classification is GOV's, recorded separately
    say(root, "sources.events", {
        "role": "fact", "connector": "local_file", "location": "data/raw/subscription_events_batch.csv",
        "format": "csv",
        "csv": {"delimiter": ",", "header": "yes", "quote": '"', "escape": '"', "encoding": "utf-8",
                "null_tokens": "NA"},
        "schema": {"columns": {
            "event_id": {"type": "VARCHAR", "required": "yes", "key": "yes"},
            "account_id": {"type": "INTEGER", "required": "yes", "key": "no"},
            "region": {"type": "VARCHAR", "required": "yes", "allowed_values": ["NA", "EMEA", "APAC", "LATAM"]},
            "event_date": {"type": "DATE", "required": "yes"},
            "plan_name": {"type": "VARCHAR", "required": "yes",
                          "allowed_values": ["Starter", "Growth", "Scale", "Enterprise"]},
            "mrr_amount": {"type": "DECIMAL(18,2)", "required": "yes"},
            "seats": {"type": "INTEGER", "required": "yes"},
            "status": {"type": "VARCHAR", "required": "yes", "allowed_values": ["active", "churned", "trialing"]},
        }},
        "load_type": "full_refresh", "freshness": {"basis": "none"},
        "volume": {"min_rows": "NA", "max_rows": "NA"}, "retry_attempts": "default",
        "credentials_env": "NA", "drift_policy": "land_and_log", "profile_split_by": "NA"}, "dana")
    for c in ["event_id", "account_id", "region", "event_date", "plan_name", "mrr_amount", "seats", "status"]:
        say(root, f"sources.events.schema.columns.{c}.classification",
            "public" if c in ("region", "plan_name") else "internal", "gina")
    # ---------------- silver (DE structure, SME rules, PO tolerance)
    say(root, "silver.entities.events", {
        "sources": ["events"],
        "columns": {"event_id": {"type": "VARCHAR"}, "account_id": {"type": "INTEGER"},
                    "region": {"type": "VARCHAR"},
                    "event_date": {"type": "DATE", "formats": FORMATS},
                    "plan_name": {"type": "VARCHAR"}, "mrr_amount": {"type": "DECIMAL(18,2)"},
                    "seats": {"type": "INTEGER"}, "status": {"type": "VARCHAR"}},
        "natural_key": ["event_id"], "tiebreaker": ["account_id DESC"],
        "merge": {"strategy": "partition_replace", "partition_column": "NA"},
        "flags": "NA", "lookups": "NA", "drop_columns": "NA", "target_table": "NA"}, "dana")
    say(root, "silver.entities.events.rejected_survivor_policy", "keep_last_good", "sam")
    say(root, "silver.entities.events.null_policy",
        {"event_id": "drop", "account_id": "keep", "region": "keep", "event_date": "drop",
         "plan_name": "keep", "mrr_amount": "drop", "seats": "keep", "status": "keep"}, "sam")
    say(root, "silver.entities.events.valid_anomalies",
        {"refund": {"predicate": "mrr_amount < 0", "reason": "negative MRR is a refund or credit"}}, "sam")
    say(root, "silver.entities.events.hard_rejects", "none", "sam")
    say(root, "silver.entities.events.dead_letter_tolerance_pct", "5", "priya")
    say(root, "silver.entities.events.tolerance_source", "real", "priya")
    # ---------------- gold metric cards (PO; DE for structure)
    base = {"entity": "events", "date_basis": "event_date", "cadence": "daily",
            "version": "1.0.0", "effective_from": "2024-01-01", "population": "NA"}
    say(root, "metrics.daily_mrr", {**base, "plain_definition": "Recurring revenue from active subscription "
                                    "events, per day, region and plan.",
                                    "unit": "currency:USD", "precision": "2", "additivity": "additive",
                                    "valid_range": {"min": "none", "max": "100000"},
                                    "reconciliation": {"control": "sum:mrr_amount",
                                                       "excluded_by": "status <> 'active'",
                                                       "max_excluded_pct": "60"},
                                    "target_table": "gold_daily_mrr_by_plan"}, "dana")
    say(root, "metrics.active_events", {**base, "plain_definition": "Number of distinct active events.",
                                        "unit": "count", "precision": "0", "additivity": "additive",
                                        "valid_range": {"min": "0", "max": "none"},
                                        "reconciliation": {"control": "count", "excluded_by": "status <> 'active'",
                                                           "max_excluded_pct": "60"},
                                        "target_table": "gold_daily_mrr_by_plan"}, "dana")
    say(root, "metrics.churn_rate", {**base, "plain_definition": "Share of active+churned events that are churn "
                                     "(trialing excluded), per day.",
                                     "unit": "percent", "precision": "2", "additivity": "non_additive",
                                     "valid_range": {"min": "0", "max": "100"},
                                     "reconciliation": {"control": "count",
                                                        "excluded_by": "status NOT IN ('active', 'churned')",
                                                        "max_excluded_pct": "60"},
                                     "target_table": "gold_churn_rate"}, "dana")
    po = "priya"
    for m, mt, num, flt, grain in (("daily_mrr", "sum", "sum:mrr_amount", "status = 'active'",
                                    ["event_date", "region", "plan_name"]),
                                   ("active_events", "distinct_count", "count_distinct:event_id",
                                    "status = 'active'", ["event_date", "region", "plan_name"]),
                                   ("churn_rate", "ratio", "count", "status = 'churned'", ["event_date"])):
        say(root, f"metrics.{m}.metric_type", mt, po)
        say(root, f"metrics.{m}.numerator.measure", num, po)
        say(root, f"metrics.{m}.numerator.filter", flt, po)
        say(root, f"metrics.{m}.filters", "none", po)
        say(root, f"metrics.{m}.grain", grain, po)
        say(root, f"metrics.{m}.time_grain", "day", po)
        say(root, f"metrics.{m}.dispute_owner", "priya", po)
    say(root, "metrics.churn_rate.denominator.measure", "count", po)
    say(root, "metrics.churn_rate.denominator.include.column", "status", po)
    say(root, "metrics.churn_rate.denominator.include.values", ["active", "churned"], po)
    say(root, "metrics.churn_rate.denominator.exclude.values", ["trialing"], po)
    say(root, "metrics.churn_rate.zero_denominator", "null", po)
    if golden:
        record_golden(root, O)
    # ---------------- serve
    say(root, "serve", {"title": "Subscription MRR", "audience": "Revenue team weekly review",
                        "runtime": "streamlit", "reference_clock": "replay",
                        "kpis": {"mrr": {"metric": "daily_mrr", "label": "MRR (selection)"},
                                 "events": {"metric": "active_events", "label": "Active events"},
                                 "churn": {"metric": "churn_rate", "label": "Churn rate"}},
                        "charts": {"mrr_by_region": {"type": "line", "metric": "daily_mrr", "x": "event_date",
                                                     "color": "region"},
                                   "churn_trend": {"type": "bar", "metric": "churn_rate", "x": "event_date",
                                                   "color": "NA"}},
                        "filters": ["region", "plan_name"], "port": "NA", "auto_refresh_seconds": "NA"}, "priya")
    say(root, "serve.row_security", "none", "gina")


def golden_keys(O: dict) -> dict:
    mrr_keys = sorted(O["mrr"].index)[:: max(1, len(O["mrr"]) // 3)][:3]
    churn_days = sorted(O["churn"])
    null_day = next(d for d in churn_days if O["churn"][d] is None)
    nonnull = [d for d in churn_days if O["churn"][d] not in (None,) and 0 < O["churn"][d] < 100][:2]
    return {"mrr": mrr_keys, "churn": [null_day] + nonnull}


def record_golden(root: Path, O: dict, tamper: dict | None = None) -> None:
    keys = golden_keys(O)
    gv = []
    for k in keys["mrr"]:
        v = O["mrr"][k]
        if tamper and tamper.get("daily_mrr"):
            v = v + Decimal("1.00")
        gv.append({"key": {"event_date": str(k[0]), "region": k[1], "plan_name": k[2]}, "value": str(v)})
    say(root, "metrics.daily_mrr.golden_values", gv, "priya")
    say(root, "metrics.active_events.golden_values",
        [{"key": {"event_date": str(k[0]), "region": k[1], "plan_name": k[2]}, "value": str(int(O["cnt"][k]))}
         for k in keys["mrr"]], "priya")
    say(root, "metrics.churn_rate.golden_values",
        [{"key": {"event_date": str(d)}, "value": "null" if O["churn"][d] is None else str(O["churn"][d])}
         for d in keys["churn"]], "priya")


def run(root: Path, log: list) -> dict:
    O = oracle()
    install(root)
    (root / "data" / "raw").mkdir(parents=True, exist_ok=True)
    shutil.copy(RAW, root / "data" / "raw" / RAW.name)
    answers(root, O)
    rc, out = dwh(root, "intake", "check", "all", expect=None)
    check("silver" in out, "intake check all reports every skill", log)
    # Gate B blocks silver until the SME confirms the rule read-back
    dwh(root, "build", "bronze")
    bres = results(root, "bronze-verify")
    check(bres["passed"], "bronze verification passed", log)
    check(duck(root, "SELECT COUNT(*) FROM bronze_events")[0][0] == 515, "bronze landed all 515 rows as received", log)
    check(duck(root, "SELECT COUNT(*) FROM bronze_events WHERE region = 'NA'")[0][0] > 0,
          "region 'NA' survives as a value (not read as missing)", log)
    rc, out = dwh(root, "build", "silver", expect=2)
    check("readback_confirmed" in out, "silver BLOCKED until the SME confirms the rule read-back (V07)", log)
    check("date_ambiguity.event_date" in out,
          "silver BLOCKED until the SME rules on dates that read differently day-first vs month-first (V12)", log)
    say(root, "silver.entities.events.date_ambiguity", {"event_date": "prefer_first"}, "sam",
        quote="slash dates are day-first, as in the source system")
    rc, out = dwh(root, "intake", "readback", "events")
    check("mrr_amount < 0" in out, "read-back renders the refund rule with its match count", log)
    say(root, "silver.entities.events.readback_confirmed", "yes", "sam")
    dwh(root, "build", "silver")
    sres = results(root, "silver-verify")
    check(sres["passed"], "silver verification passed (row law, ties, cast loss, tolerance)", log)
    n = duck(root, "SELECT COUNT(*) FROM silver_events")[0][0]
    check(n == O["silver_rows"] == 483, f"silver rows {n} = 515 − 17 − 15 = 483 (pack oracle)", log)
    dl = dict(duck(root, "SELECT reason, COUNT(*) FROM silver_dead_letter GROUP BY 1"))
    check(dl == {"null_mrr_amount": 17}, f"dead letters by reason {dl} == 17 null mrr", log)
    refunds = duck(root, "SELECT COUNT(*) FROM silver_events WHERE mrr_amount < 0")[0][0]
    check(refunds > 0, f"{refunds} refund rows kept as valid anomalies", log)
    dwh(root, "build", "gold")
    gres = results(root, "gold-verify")
    check(gres["passed"], "gold verification passed (grain, golden values, reconciliation, population)", log)
    g1 = duck(root, "SELECT COUNT(*) FROM gold_daily_mrr_by_plan")[0][0]
    check(g1 == 384 == len(O["mrr"]), f"gold_daily_mrr_by_plan {g1} rows = 384 (pack oracle)", log)
    nulls = duck(root, "SELECT COUNT(*) FROM gold_churn_rate WHERE churn_rate IS NULL")[0][0]
    check(nulls == O["null_churn_days"], f"{nulls} NULL churn days (zero denominator → null) = oracle", log)
    # full content comparison with the independent oracle
    got = {(str(a), b, c): Decimal(str(v)) for a, b, c, v in
           duck(root, "SELECT event_date, region, plan_name, daily_mrr FROM gold_daily_mrr_by_plan")}
    want = {(str(k[0]), k[1], k[2]): v for k, v in O["mrr"].items()}
    check(got == want, "every daily_mrr value equals the independent pandas oracle (content, not counts)", log)
    gotc = {str(d): v for d, v in duck(root, "SELECT event_date, churn_rate FROM gold_churn_rate")}
    wantc = {str(d): v for d, v in O["churn"].items()}
    check(gotc == wantc, "every churn_rate value equals the oracle", log)
    dwh(root, "publish")
    rc, out = dwh(root, "publish", "--target", "consumers", expect=2)
    check("not approved" in out or "pending" in out, "consumer release refused without an approval", log)
    rc, out = dwh(root, "serve", "--check", expect=None)
    sc = results(root, "serve-check")
    check(sc["passed"], "serve --check: snapshot hashes, KPI parity, charts, headless health", log)
    return {"oracle": O}


if __name__ == "__main__":
    log: list = []
    root = Path(sys.argv[1] if len(sys.argv) > 1 else RUNS / "d1").resolve()
    try:
        run(root, log)
    except Fail as e:
        log.append(("FAIL", str(e)))
    for s, m in log:
        print(f"[{s}] {m}")
    sys.exit(0 if all(s == "PASS" for s, _ in log) else 1)
