"""Merge-strategy fixtures: append, upsert_by_version, cdc_apply, snapshot_diff — with late and
out-of-order batches. Expected final states are written by hand here (the oracle)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import RUNS, Fail, check, duck, dwh, install, lay, loc, results, say, spec  # noqa: E402


def base(root: Path) -> None:
    say(root, "people", {"dana": {"name": "Dana", "roles": ["DE"]}, "priya": {"name": "Priya", "roles": ["PO"]},
                         "sam": {"name": "Sam", "roles": ["SME"]}, "gina": {"name": "Gina", "roles": ["GOV"]}}, "dana")
    for k, v in (("name", "merges"), ("profile", "fast"), ("builder", "dana")):
        say(root, f"project.{k}", v, "dana")
    say(root, "policies.compliance", "none", "gina")
    say(root, "policies.egress", "stats_only", "gina")
    say(root, "policies.timezone.reporting", "UTC", "priya")


def source(root: Path, name: str, cols: dict, load_type: str) -> None:
    say(root, f"sources.{name}", {
        "role": "fact", "connector": "local_file", "location": f"data/raw/{name}_{{batch}}.csv", "format": "csv",
        "csv": {"delimiter": ",", "header": "yes", "quote": '"', "escape": '"', "encoding": "utf-8", "null_tokens": "NA"},
        "schema": {"columns": {c: {"type": t, "required": "yes"} for c, t in cols.items()}},
        "load_type": load_type, "redelivery_policy": "replace", "freshness": {"basis": "none"},
        "volume": {"min_rows": "NA", "max_rows": "NA"}, "retry_attempts": "3", "credentials_env": "NA",
        "drift_policy": "reject", "profile_split_by": "NA"}, "dana")
    for c in cols:
        say(root, f"sources.{name}.schema.columns.{c}.classification", "internal", "gina")


def entity(root: Path, name: str, cols: dict, key: list, tb: list, merge: dict) -> None:
    say(root, f"silver.entities.{name}", {
        "sources": [name], "columns": {c: {"type": t} for c, t in cols.items()}, "natural_key": key,
        "tiebreaker": tb, "merge": merge, "flags": "NA", "lookups": "NA", "drop_columns": "NA", "target_table": "NA"},
        "dana")
    say(root, f"silver.entities.{name}.rejected_survivor_policy", "keep_last_good", "sam")
    say(root, f"silver.entities.{name}.null_policy", {c: "keep" if c not in key else "drop" for c in cols}, "sam")
    say(root, f"silver.entities.{name}.valid_anomalies", "none", "sam")
    say(root, f"silver.entities.{name}.hard_rejects", "none", "sam")
    say(root, f"silver.entities.{name}.dead_letter_tolerance_pct", "50", "priya")
    say(root, f"silver.entities.{name}.tolerance_source", "owner", "priya")


def write(root: Path, name: str, batch: str, header: str, rows: list[str]) -> None:
    p = root / "data" / "raw" / f"{name}_{batch}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def run(root: Path, log: list) -> None:
    install(root)
    base(root)
    # ---------------- upsert_by_version
    source(root, "acct", {"id": "VARCHAR", "version": "INTEGER", "plan": "VARCHAR"}, "incremental_append")
    entity(root, "acct", {"id": "VARCHAR", "version": "INTEGER", "plan": "VARCHAR"}, ["id"], ["version DESC"],
           {"strategy": "upsert_by_version", "version_column": "version"})
    # ---------------- cdc_apply
    source(root, "cust", {"id": "VARCHAR", "op": "VARCHAR", "seq": "INTEGER", "name": "VARCHAR"}, "cdc")
    entity(root, "cust", {"id": "VARCHAR", "op": "VARCHAR", "seq": "INTEGER", "name": "VARCHAR"}, ["id"], ["seq DESC"],
           {"strategy": "cdc_apply", "op_column": "op", "op_codes": {"insert": "I", "update": "U", "delete": "D"},
            "sequence_column": "seq"})
    say(root, "silver.entities.cust.null_policy", {"id": "drop", "op": "keep", "seq": "keep", "name": "drop"}, "sam")
    # ---------------- snapshot_diff
    source(root, "prod", {"sku": "VARCHAR", "price": "DECIMAL(10,2)"}, "snapshot")
    entity(root, "prod", {"sku": "VARCHAR", "price": "DECIMAL(10,2)"}, ["sku"], ["price DESC"],
           {"strategy": "snapshot_diff"})
    # ---------------- append
    source(root, "evt", {"eid": "VARCHAR", "kind": "VARCHAR"}, "incremental_append")
    entity(root, "evt", {"eid": "VARCHAR", "kind": "VARCHAR"}, ["eid"], ["kind ASC"], {"strategy": "append"})
    say(root, "sources.evt.redelivery_policy", "reject", "dana")
    for e in ("acct", "cust", "prod", "evt"):
        pass
    rc, out = dwh(root, "intake", "check", "silver", "--gate", "A", expect=None)
    check(rc == 0, "four merge-strategy entities pass the intake gate", log)

    write(root, "acct", "b1", "id,version,plan", ["A,1,basic", "B,1,basic"])
    write(root, "acct", "b2", "id,version,plan", ["A,2,pro", "B,0,legacy", "A,2,pro"])
    write(root, "cust", "b1", "id,op,seq,name", ["A,I,1,Ann", "B,I,2,Bob"])
    write(root, "cust", "b2", "id,op,seq,name", ["A,U,3,Annie", "B,D,4,"])
    write(root, "prod", "2024-01-01", "sku,price", ["A,1.00", "B,2.00", "C,3.00"])
    write(root, "prod", "2024-01-02", "sku,price", ["A,1.50", "C,3.00"])
    write(root, "prod", "2024-01-03", "sku,price", ["A,1.50", "B,2.00"])
    write(root, "evt", "b1", "eid,kind", ["e1,click", "e2,view"])
    write(root, "evt", "b2", "eid,kind", ["e2,view", "e3,click"])
    dwh(root, "build", "bronze")
    for e in ("acct", "cust", "prod", "evt"):
        dwh(root, "intake", "readback", e)
    dwh(root, "build", "silver")
    check(results(root, "silver-verify")["passed"], "row law holds for every strategy and batch", log)
    acct = dict(duck(root, "SELECT id, version || ':' || plan FROM silver_acct"))
    check(acct == {"A": "2:pro", "B": "1:basic"}, f"upsert: newer version wins, older B v0 is stale ({acct})", log)
    cust = {r[0]: (r[1], r[2]) for r in duck(root, "SELECT id, name, _is_deleted FROM silver_cust")}
    check(cust == {"A": ("Annie", False), "B": ("Bob", True)}, f"cdc: update applied, delete is a soft delete ({cust})", log)
    prod = {r[0]: (str(r[1]), r[2]) for r in duck(root, "SELECT sku, price, _is_deleted FROM silver_prod")}
    check(prod == {"A": ("1.50", False), "B": ("2.00", False), "C": ("3.00", True)},
          f"snapshot: B deleted on day 2 then reactivated on day 3, C deleted on day 3 ({prod})", log)
    evt = dict(duck(root, "SELECT eid, kind FROM silver_evt"))
    check(evt == {"e1": "click", "e2": "view", "e3": "click"}, "append: e2 already present is not duplicated", log)
    facts = results(root, "silver-verify")["facts"]
    check(facts["acct|acct|b2"]["stale"] == 1 and facts["acct|acct|b2"]["updated"] == 1
          and facts["acct|acct|b2"]["duplicates"] == 1,
          "upsert terms: 1 updated, 1 stale, 1 in-batch duplicate", log)
    check(facts["evt|evt|b2"]["already_present"] == 1, "append terms: 1 already present", log)
    # ---- late, older batches arriving after newer ones (V16 / V44)
    write(root, "acct", "b0", "id,version,plan", ["A,0,trial", "C,1,basic"])
    write(root, "cust", "b0", "id,op,seq,name", ["B,U,3,Bobby"])
    dwh(root, "build", "bronze")
    dwh(root, "build", "silver")
    acct = dict(duck(root, "SELECT id, version || ':' || plan FROM silver_acct"))
    check(acct == {"A": "2:pro", "B": "1:basic", "C": "1:basic"},
          f"late batch with an older version never overwrites newer data ({acct})", log)
    cust = {r[0]: (r[1], r[2]) for r in duck(root, "SELECT id, name, _is_deleted FROM silver_cust")}
    check(cust["B"] == ("Bob", True), "late CDC update older than the delete does not resurrect the row", log)
    # ---- a snapshot older than the last applied one replays history in order (V44), never blocks
    write(root, "prod", "2023-12-31", "sku,price", ["Z,9.00"])
    dwh(root, "build", "bronze")
    rc, out = dwh(root, "build", "silver")
    prod = {r[0]: (str(r[1]), r[2]) for r in duck(root, "SELECT sku, price, _is_deleted FROM silver_prod")}
    check(prod == {"A": ("1.50", False), "B": ("2.00", False), "C": ("3.00", True), "Z": ("9.00", True)},
          f"late older snapshot → entity replayed in date order; Z is deleted by the next snapshot ({prod})", log)
    acct_after = dict(duck(root, "SELECT id, version || ':' || plan FROM silver_acct"))
    check(acct_after == {"A": "2:pro", "B": "1:basic", "C": "1:basic"}, "other entities untouched by the replay", log)
    # ---- re-delivery with the reject policy
    write(root, "evt", "b1", "eid,kind", ["e1,CLICK", "e2,view"])
    dwh(root, "build", "bronze")
    rej = (loc(root, "dead_letter") / "rejected_files.csv").read_text()
    check("redelivery_rejected" in rej, "re-delivery policy 'reject' refuses a changed batch and logs it", log)


if __name__ == "__main__":
    log: list = []
    root = Path(sys.argv[1] if len(sys.argv) > 1 else RUNS / "merges").resolve()
    try:
        run(root, log)
    except Fail as e:
        log.append(("FAIL", str(e)))
    for s, m in log:
        print(f"[{s}] {m}")
    sys.exit(0 if all(s == "PASS" for s, _ in log) else 1)
