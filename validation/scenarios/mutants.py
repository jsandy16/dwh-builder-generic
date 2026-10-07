"""Mutation-kill matrix (V33). Each mutant is a plausible mistake — a wrong spec answer recorded by
the right owner (so the intake gate cannot simply refuse it), a bad file, or a hand edit — applied
to a copy of a finished, passing project. A mutant is KILLED when a gate refuses, a build fails
verification, or the harness content oracle (V32: frozen pack output) detects the difference."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import PACK_SILVER, RUNS, Fail, duck, dwh, lay, loc, say  # noqa: E402

D1 = RUNS / "d1"
D2 = RUNS / "d2"
OUT = RUNS / "mutants"


def clone(base: Path, name: str) -> Path:
    dst = OUT / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(base, dst, symlinks=True)
    for f in ("lock.json",):
        (dst / ".dwh" / f).unlink(missing_ok=True)
    dwh(dst, "doctor")  # re-point the wrappers at the copy
    return dst


def pack_oracle(root: Path) -> bool:
    """V32: silver content equals the pack's executed output (order-insensitive)."""
    import duckdb
    con = duckdb.connect()
    want = set(con.execute("SELECT event_id, account_id, region, CAST(event_date AS VARCHAR), plan_name, "
                           "ROUND(mrr_amount, 2), seats, status FROM read_parquet(?)", [str(PACK_SILVER)]).fetchall())
    got = set(duck(root, "SELECT event_id, account_id, region, CAST(event_date AS VARCHAR), plan_name, "
                         "ROUND(CAST(mrr_amount AS DOUBLE), 2), seats, status FROM silver_events"))
    return want == got


def d1_mutants():
    sme, po, de = "sam", "priya", "dana"
    return {
        "region_swap": lambda r: say(r, "silver.entities.events.mapping", {"events": {
            "region": "CASE region WHEN 'EMEA' THEN 'APAC' WHEN 'APAC' THEN 'EMEA' ELSE region END"}}, de),
        "date_plus_1": lambda r: say(r, "silver.entities.events.mapping", {"events": {
            "event_date": "strftime(CAST(COALESCE(TRY_STRPTIME(event_date, '%Y-%m-%d'), "
                          "TRY_STRPTIME(event_date, '%d/%m/%Y'), TRY_STRPTIME(event_date, '%b %d %Y')) AS DATE) + 1, "
                          "'%Y-%m-%d')"}}, de),
        "trialing_in_denominator": lambda r: (
            say(r, "metrics.churn_rate.denominator.include.values", ["active", "churned", "trialing"], po),
            say(r, "metrics.churn_rate.denominator.exclude.values", "none", po)),
        "ambiguous_format_cascade": lambda r: say(r, "silver.entities.events.columns.event_date.formats",
                                                  ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d %Y"], de),
        "ambiguous_format_prefer_first": lambda r: (
            say(r, "silver.entities.events.columns.event_date.formats",
                ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d %Y"], de),
            say(r, "silver.entities.events.date_ambiguity", {"event_date": "prefer_first"}, sme)),
        "flipped_tiebreaker": lambda r: say(r, "silver.entities.events.tiebreaker", ["account_id ASC"], de),
        "dropped_filter": lambda r: say(r, "metrics.daily_mrr.numerator.filter", "none", po),
        "key_column_swap": lambda r: say(r, "silver.entities.events.natural_key", ["account_id"], de),
        "money_as_double": lambda r: say(r, "silver.entities.events.columns.mrr_amount.type", "DOUBLE", de),
        "null_policy_keep": lambda r: say(r, "silver.entities.events.null_policy.mrr_amount", "keep", sme),
        "refund_conflict": lambda r: say(r, "silver.entities.events.hard_rejects",
                                         {"negative": {"predicate": "mrr_amount < 0", "reason": "negative_mrr"}}, sme),
        "refund_deleted_as_dirt": lambda r: (
            say(r, "silver.entities.events.valid_anomalies", "none", sme),
            say(r, "silver.entities.events.hard_rejects",
                {"negative": {"predicate": "mrr_amount < 0", "reason": "negative_mrr"}}, sme),
            dwh(r, "intake", "readback", "events"),
            say(r, "silver.entities.events.readback_confirmed", "yes", sme)),
        "zero_denominator_as_zero": lambda r: say(r, "metrics.churn_rate.zero_denominator", "zero", po),
        "hand_edited_sql": lambda r: _edit(lay(r).generated("gold/gold_churn_rate.sql"), "'churned'", "'active'"),
        "upstream_file_corrupted": lambda r: _corrupt_snapshot(r),
    }


def d2_mutants():
    return {
        "wrong_reporting_timezone": lambda r: say(r, "policies.timezone.reporting", "Asia/Kolkata", "priya"),
        "join_fan_out": lambda r: (
            say(r, "silver.entities.zones.natural_key", ["location_id", "zone"], "dana"),
            _append(r / "data/raw/zones.csv", "5,Queens,Duplicate Zone,Boro Zone\n"),
            dwh(r, "build", "bronze")),
        "imputed_input_without_population": lambda r: say(r, "metrics.tip_rate.population", "NA", "priya"),
        "structural_null_imputed": lambda r: (
            say(r, "silver.entities.trips.null_policy.airport_fee", "impute:0", "sam"),
            say(r, "silver.entities.trips.structural_nulls", {"airport_fee|source=green": "defect"}, "sam")),
    }


def _edit(p: Path, a: str, b: str):
    p.write_text(p.read_text().replace(a, b, 1))


def _append(p: Path, line: str):
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(line)


def _corrupt_snapshot(r: Path):
    cur = (loc(r, "serving") / "CURRENT").read_text().strip()
    f = next((loc(r, "serving") / cur).glob("*.parquet"))
    data = bytearray(f.read_bytes())
    data[len(data) // 2] ^= 0xFF
    f.write_bytes(bytes(data))


def attempt(root: Path, domain: str) -> tuple[bool, str]:
    """Run the pipeline after the mutation; return (killed, by what)."""
    if (loc(root, "serving") / "CURRENT").exists() and "upstream_file_corrupted" in root.name:
        rc, out = dwh(root, "serve", "--check", expect=None)
        return rc != 0, "V42 snapshot manifest hash check (serve --check)"
    for layer in ("silver", "gold"):
        rc, out = dwh(root, "build", layer, expect=None)
        if rc != 0:
            if rc == 2:
                items = [l.strip()[2:] for l in out.splitlines() if l.strip().startswith("- `")]
                first = items[0] if items else next((l for l in out.splitlines() if l.strip()), "")
                return True, f"{layer} intake gate — {first[:140]}"
            import json as _j
            res = _j.loads(lay(root).report(f"{layer}-verify", "json").read_text())
            fails = [f"{c['id']} ({c['name'].split(': ', 1)[-1]})" for c in res["checks"] if not c["passed"] and c["fatal"]]
            return True, f"{layer} verification — " + "; ".join(fails[:3])[:160]
    if domain == "d1" and not pack_oracle(root):
        return True, "harness content oracle (V32): silver differs from the executed pack output"
    return False, "SURVIVED"


def run(log: list) -> list:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for domain, base, muts in (("d1", D1, d1_mutants()), ("d2", D2, d2_mutants())):
        for name, apply in muts.items():
            root = clone(base, name)
            try:
                apply(root)
                killed, how = attempt(root, domain)
            except Fail as e:
                killed, how = True, f"refused while recording the mutation: {str(e).splitlines()[-1][:150]}"
            rows.append((domain, name, killed, how))
            log.append(("PASS" if killed else "FAIL", f"mutant {domain}/{name}: {'killed by ' + how if killed else how}"))
    return rows


if __name__ == "__main__":
    log: list = []
    run(log)
    for s, m in log:
        print(f"[{s}] {m}")
    sys.exit(0 if all(s == "PASS" for s, _ in log) else 1)
