"""Regression tests for every finding of the independent review (C1–C3, H1–H8, M2–M8, L8) and the
'drafted' intake state added after the agent-behaviour evals."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import RUNS, SKILLS, TMP, Fail, check, duck, dwh, install, loc, results, say, spec  # noqa: E402
from merges import base, entity, source, write  # noqa: E402

PWNED = TMP / "dwh_regression_pwned.csv"


def gate(root, skill, g="A"):
    rc, out = dwh(root, "intake", "check", skill, "--gate", g, "--json", expect=None)
    return rc, json.loads(out)


def run(root: Path, log: list) -> None:
    install(root)
    base(root)
    # ---------------- C1: 'none' can never stand in for a mandatory list/map (schema, metrics…)
    source(root, "s1", {"id": "VARCHAR", "amount": "DECIMAL(10,2)", "qty": "INTEGER"}, "incremental_append")
    say(root, "sources.s1.schema.columns", "none", "dana")
    rc, j = gate(root, "bronze")
    check(rc == 2 and any(e["path"] == "sources.s1.schema.columns" for e in j["errors"]),
          "C1: schema answered 'none' is refused — the schema stays mandatory", log)
    say(root, "metrics", "none", "dana")
    rc, j = gate(root, "gold")
    check(rc == 2 and any(e["path"] == "metrics" for e in j["errors"]), "C1: metrics answered 'none' is refused", log)
    source(root, "s1", {"id": "VARCHAR", "amount": "DECIMAL(10,2)", "qty": "INTEGER"}, "incremental_append")
    # ---------------- drafted values block until a person confirms them
    say(root, "sources.s1.role", "fact", "dana", expect=0) if False else None
    rc, out = dwh(root, "intake", "set", "sources.s1.role", "dimension", "--by", "dana", "--drafted")
    rc, j = gate(root, "bronze")
    check(any(e["path"] == "sources.s1.role" and "drafted" in e["problem"] for e in j["errors"]),
          "a value the assistant chose (--drafted) blocks the gate", log)
    rc, out = dwh(root, "intake", "set", "policies.egress", "stats_only", "--by", "gina", "--drafted", expect=2)
    check("never drafted" in out, "★ answers can never be drafted", log)
    dwh(root, "intake", "confirm", "sources.s1.role", "--by", "dana")
    rc, j = gate(root, "bronze")
    check(rc == 0, "after the person confirms the draft, the gate passes", log)
    # ---------------- H1: the assistant cannot be added to people under another id
    rc, out = say(root, "people.helper", {"name": "Claude Helper", "roles": ["GOV"]}, "dana")
    rc, j = gate(root, "project")
    check(rc == 2 and any("assistant cannot be listed" in e["problem"] for e in j["errors"]),
          "H1: an assistant listed under another id or name is refused", log)
    rc, out = dwh(root, "intake", "set", "people", "--yaml",
                  "{dana: {name: Dana, roles: [DE]}, priya: {name: Priya, roles: [PO]}, sam: {name: Sam, roles: [SME]}, "
                  "gina: {name: Gina, roles: [GOV]}}", "--by", "dana")
    # ---------------- C2: SQL in a header name is data, never executed (land_and_log = the risky path)
    say(root, "sources.s1.drift_policy", "land_and_log", "dana")
    PWNED.unlink(missing_ok=True)
    evil = f'''id,amount,qty,"x"" VARCHAR); COPY (SELECT 1) TO '{PWNED}'; --"'''
    write(root, "s1", "b1", evil, ["A,1.00,1,z", "B,3.149,2,z", "C,2.00,3.7,z", "D,1.10,1,z", "E,2.20,2,z",
                                    "F,3.30,3,z", "G,4.40,4,z"])
    dwh(root, "build", "bronze")
    check(not PWNED.exists(), "C2: a header containing SQL is quoted, not executed (no side-effect file)", log)
    cols = [r[0] for r in duck(root, "DESCRIBE bronze_s1")]
    check(any("COPY" in c for c in cols), "C2: the odd header landed as an ordinary column name (drift logged)", log)
    # ---------------- C3: batch ids with quotes are refused
    write(root, "s1", "b2'x", "id,amount,qty", ["D,1.00,1"])
    dwh(root, "build", "bronze")
    rej = pd.read_csv(loc(root, "dead_letter") / "rejected_files.csv")
    check("bad_batch_id" in set(rej["reason"]), "C3: a batch id with a quote is rejected (bad_batch_id)", log)
    (root / "data/raw" / "s1_b2'x.csv").unlink()
    # ---------------- M6: no silent rounding
    entity(root, "s1", {"id": "VARCHAR", "amount": "DECIMAL(10,2)", "qty": "INTEGER"}, ["id"], ["amount DESC"],
           {"strategy": "partition_replace", "partition_column": "NA"})
    say(root, "silver.entities.s1.drop_columns", {[c for c in cols if "COPY" in c][0]: "test column"}, "dana")
    dwh(root, "build", "silver")
    dl = dict(duck(root, "SELECT reason, COUNT(*) FROM silver_dead_letter WHERE entity='s1' GROUP BY 1"))
    check(dl.get("cast_amount") == 1 and dl.get("cast_qty") == 1,
          f"M6: 3.149 → DECIMAL(10,2) and 3.7 → INTEGER are cast loss, not silent rounding ({dl})", log)
    # ---------------- H5: corrected re-delivery under upsert_by_version is applied (history replay)
    source(root, "acct", {"id": "VARCHAR", "version": "INTEGER", "plan": "VARCHAR"}, "incremental_append")
    entity(root, "acct", {"id": "VARCHAR", "version": "INTEGER", "plan": "VARCHAR"}, ["id"], ["version DESC"],
           {"strategy": "upsert_by_version", "version_column": "version"})
    write(root, "acct", "b1", "id,version,plan", ["A,1,basic"])
    write(root, "acct", "b2", "id,version,plan", ["A,2,pro"])
    dwh(root, "build", "bronze")
    dwh(root, "build", "silver")
    write(root, "acct", "b2", "id,version,plan", ["A,2,enterprise"])
    dwh(root, "build", "bronze")
    dwh(root, "build", "silver")
    check(dict(duck(root, "SELECT id, plan FROM silver_acct")) == {"A": "enterprise"},
          "H5: a corrected re-delivery (same version) is applied under upsert — incremental = rebuild", log)
    # ---------------- H6: reject_key withdraws a record whose newest version is rejected
    source(root, "rk", {"id": "VARCHAR", "version": "INTEGER", "amount": "DECIMAL(10,2)"}, "incremental_append")
    entity(root, "rk", {"id": "VARCHAR", "version": "INTEGER", "amount": "DECIMAL(10,2)"}, ["id"], ["version DESC"],
           {"strategy": "upsert_by_version", "version_column": "version"})
    say(root, "silver.entities.rk.rejected_survivor_policy", "reject_key", "sam")
    say(root, "silver.entities.rk.dead_letter_tolerance_pct", "100", "priya")
    say(root, "silver.entities.rk.hard_rejects", {"neg": {"predicate": "amount < 0", "reason": "negative_amount"}}, "sam")
    write(root, "rk", "b1", "id,version,amount", ["K,2,10.00", "L,1,5.00"])
    write(root, "rk", "b2", "id,version,amount", ["K,3,-1.00"])
    dwh(root, "build", "bronze")
    dwh(root, "intake", "readback", "rk")
    say(root, "silver.entities.rk.readback_confirmed", "yes", "sam")
    dwh(root, "build", "silver")
    rk = {r[0]: r[1] for r in duck(root, "SELECT id, _is_deleted FROM silver_rk")}
    check(rk == {"K": True, "L": False}, f"H6: reject_key withdraws K when its newest version is rejected ({rk})", log)
    # ---------------- H7 + H8: CDC op codes; protected values hashed in dead letters
    source(root, "cust", {"id": "VARCHAR", "op": "VARCHAR", "seq": "INTEGER", "email": "VARCHAR"}, "cdc")
    say(root, "sources.cust.schema.columns.email.classification", "pii", "gina")
    entity(root, "cust", {"id": "VARCHAR", "op": "VARCHAR", "seq": "INTEGER", "email": "VARCHAR"}, ["id"], ["seq DESC"],
           {"strategy": "cdc_apply", "op_column": "op", "op_codes": {"insert": "I", "update": "U", "delete": "D"},
            "sequence_column": "seq"})
    say(root, "silver.entities.cust.masking", {"email": "hash"}, "gina")
    say(root, "silver.entities.cust.dead_letter_tolerance_pct", "100", "priya")
    say(root, "silver.entities.cust.null_policy", {"id": "drop", "op": "keep", "seq": "keep", "email": "drop"}, "sam")
    write(root, "cust", "b1", "id,op,seq,email", ["A,I,1,ann@example.com", "B,I,2,bob@example.com"])
    write(root, "cust", "b2", "id,op,seq,email", ["B,D,3,", "A,X,4,evil@example.com", "C,,5,carl@example.com"])
    dwh(root, "build", "bronze")
    dwh(root, "build", "silver")
    dl = {r[0]: r[1] for r in duck(root, "SELECT reason, raw_row FROM silver_dead_letter WHERE entity='cust'")}
    check(set(dl) == {"unknown_op"} and len(duck(root, "SELECT 1 FROM silver_dead_letter WHERE entity='cust'")) == 2,
          "H7: rows with an unknown or NULL op code are dead-lettered unknown_op", log)
    check(all("@example.com" not in str(v) for v in dl.values()),
          "H8: a pii value is hashed in the dead-letter row (never stored in clear)", log)
    cust = {r[0]: (r[1], r[2]) for r in duck(root, "SELECT id, length(email), _is_deleted FROM silver_cust")}
    check(cust["B"][1] is True and cust["A"][0] == 32, "CDC delete applied; masked email is a 32-char hash", log)
    # ---------------- M2: batch ids that are dates are processed in date order
    source(root, "snap", {"sku": "VARCHAR", "price": "DECIMAL(10,2)"}, "snapshot")
    say(root, "sources.snap.freshness", {"basis": "batch_token", "token_format": "%d-%m-%Y", "window_days": "5000"}, "dana")
    say(root, "sources.snap.freshness.window_days", "5000", "priya")
    entity(root, "snap", {"sku": "VARCHAR", "price": "DECIMAL(10,2)"}, ["sku"], ["price DESC"], {"strategy": "snapshot_diff"})
    write(root, "snap", "31-01-2024", "sku,price", ["A,1.00", "B,2.00"])
    write(root, "snap", "01-02-2024", "sku,price", ["A,1.00"])
    dwh(root, "build", "bronze")
    dwh(root, "build", "silver")
    snap = {r[0]: r[1] for r in duck(root, "SELECT sku, _is_deleted FROM silver_snap")}
    check(snap == {"A": False, "B": True}, f"M2: 31-01-2024 is applied before 01-02-2024 (date order, not text) ({snap})", log)
    # ---------------- M3 + M4: CRLF + blank lines; cp1252
    source(root, "enc", {"id": "VARCHAR", "city": "VARCHAR"}, "incremental_append")
    say(root, "sources.enc.csv.encoding", "cp1252", "dana")
    p = root / "data/raw/enc_b1.csv"
    p.write_bytes("id,city\r\n1,Montréal\r\n\r\n2,Zürich\r\n\r\n".encode("cp1252"))
    rc, out = dwh(root, "build", "bronze")
    got = sorted(r[0] for r in duck(root, "SELECT city FROM bronze_enc"))
    check(got == ["Montréal", "Zürich"], f"M3/M4: cp1252 file with CRLF and blank lines lands correctly ({got})", log)
    # ---------------- other formats and connectors: xlsx (M5 header spaces), jsonl, http
    import socket, subprocess, time
    xl = root / "data/raw/xl_b1.xlsx"
    pd.DataFrame({" id ": ["X1", "X2"], "fare": ["1.50", "2.50"]}).to_excel(xl, index=False, sheet_name="trips")
    say(root, "sources.xl", {"role": "fact", "connector": "local_file", "location": "data/raw/xl_{batch}.xlsx",
                             "format": "xlsx", "xlsx": {"sheet": "trips", "header_row": "1"},
                             "schema": {"columns": {"id": {"type": "VARCHAR", "required": "yes"},
                                                    "fare": {"type": "DECIMAL(10,2)", "required": "yes"}}},
                             "load_type": "incremental_append", "redelivery_policy": "replace",
                             "freshness": {"basis": "none"}, "volume": {"min_rows": "NA", "max_rows": "NA"},
                             "retry_attempts": "3", "credentials_env": "NA", "drift_policy": "reject",
                             "profile_split_by": "NA"}, "dana")
    for c in ("id", "fare"):
        say(root, f"sources.xl.schema.columns.{c}.classification", "internal", "gina")
    (root / "data/raw/js_b1.jsonl").write_text('{"id": "J1", "n": 1}\n{"id": "J2", "n": 2}\n')
    say(root, "sources.js", {"role": "fact", "connector": "local_file", "location": "data/raw/js_{batch}.jsonl",
                             "format": "jsonl", "schema": {"columns": {"id": {"type": "VARCHAR", "required": "yes"},
                                                                       "n": {"type": "INTEGER", "required": "yes"}}},
                             "load_type": "incremental_append", "redelivery_policy": "replace",
                             "freshness": {"basis": "none"}, "volume": {"min_rows": "NA", "max_rows": "NA"},
                             "retry_attempts": "3", "credentials_env": "NA", "drift_policy": "reject",
                             "profile_split_by": "NA"}, "dana")
    for c in ("id", "n"):
        say(root, f"sources.js.schema.columns.{c}.classification", "internal", "gina")
    srv_dir = root.parent / "http_src"
    srv_dir.mkdir(exist_ok=True)
    (srv_dir / "h_2024-01.csv").write_text("id,v\nH1,1\nH2,2\n")
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], cwd=srv_dir,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    try:
        say(root, "sources.h", {"role": "fact", "connector": "http_file",
                                "location": f"http://127.0.0.1:{port}/h_{{batch}}.csv", "format": "csv",
                                "csv": {"delimiter": ",", "header": "yes", "quote": '"', "escape": '"',
                                        "encoding": "utf-8", "null_tokens": "NA"},
                                "schema": {"columns": {"id": {"type": "VARCHAR", "required": "yes"},
                                                       "v": {"type": "INTEGER", "required": "yes"}}},
                                "load_type": "incremental_append", "redelivery_policy": "replace",
                                "freshness": {"basis": "none"}, "volume": {"min_rows": "NA", "max_rows": "NA"},
                                "retry_attempts": "3", "credentials_env": "NA", "drift_policy": "reject",
                                "profile_split_by": "NA"}, "dana")
        for c in ("id", "v"):
            say(root, f"sources.h.schema.columns.{c}.classification", "internal", "gina")
        dwh(root, "build", "bronze", "--source", "xl")
        dwh(root, "build", "bronze", "--source", "js")
        dwh(root, "build", "bronze", "--source", "h", "--batch", "2024-01")
    finally:
        srv.terminate()
    check(sorted(duck(root, "SELECT id, fare FROM bronze_xl")) == [("X1", "1.50"), ("X2", "2.50")],
          "M5: Excel source with a padded header (' id ') lands its values", log)
    check(sorted(duck(root, "SELECT id, n FROM bronze_js")) == [("J1", "1"), ("J2", "2")], "JSON-lines source lands", log)
    check(sorted(duck(root, "SELECT id, v FROM bronze_h")) == [("H1", "1"), ("H2", "2")],
          "HTTP source lands with an explicit --batch", log)
    # ---------------- L8: rules cannot depend on today's date
    rc, out = say(root, "silver.entities.s1.hard_rejects", {"old": {"predicate": "today() > DATE '2020-01-01'",
                                                                    "reason": "x"}}, "sam")
    rc, j = gate(root, "silver")
    check(any("not allowed" in e["problem"] and "today" in e["problem"] for e in j["errors"]),
          "L8: clock-dependent functions are refused in rules (determinism)", log)
    say(root, "silver.entities.s1.hard_rejects", "none", "sam")


def gold_and_serve(d1: Path, log: list) -> None:
    """On a copy of the finished domain-1 project: M7, M8, H2, H3, H4."""
    import shutil
    root = d1.parent / "regress_d1"
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(d1, root, symlinks=True)
    shutil.rmtree(root / "dwh_core")
    shutil.copytree(SKILLS / "dwh-init" / "kernel" / "dwh_core", root / "dwh_core",
                    ignore=shutil.ignore_patterns("__pycache__"))
    dwh(root, "doctor")
    dwh(root, "build", "silver")
    # M7: a distinct count over a NON-unique column (accounts appear in several groups)
    say(root, "metrics.active_events.numerator.measure", "count_distinct:account_id", "priya")
    say(root, "metrics.active_events.reconciliation.control", "count_distinct:account_id", "dana")
    # M8: a golden value of 0 for a key with no active rows
    rows = duck(root, "SELECT CAST(event_date AS VARCHAR), region, plan_name FROM silver_events WHERE status <> 'active' "
                      "EXCEPT SELECT CAST(event_date AS VARCHAR), region, plan_name FROM silver_events WHERE status = 'active' "
                      "ORDER BY 1 LIMIT 1")
    d, r, pl = rows[0]
    gv = json.loads(json.dumps(duck(root, "SELECT 1")))  # noqa: F841
    import yaml
    cur = spec(root, "metrics")["daily_mrr"]["golden_values"]
    cur.append({"key": {"event_date": d, "region": r, "plan_name": pl}, "value": "0"})
    say(root, "metrics.daily_mrr.golden_values", cur, "priya")
    rc, out = dwh(root, "build", "gold", expect=None)
    res = results(root, "gold-verify")
    v27 = next(c for c in res["checks"] if c["id"] == "V27-active_events")
    check(v27["passed"], "M7: a distinct-count metric reconciles to the distinct count of non-excluded rows", log)
    g0 = [c for c in res["checks"] if c["id"].startswith("V25-daily_mrr")][-1]
    check(g0["passed"], "M8: golden value 0 for a key with no qualifying rows passes", log)
    # H4 + H2: row-level security is refused, and the dashboard refuses to run with its gate blocked
    say(root, "serve.row_security", "region", "gina")
    rc, out = dwh(root, "serve", "--check", expect=None)
    check(rc == 2 and "row-level security" in out, "H2/H4: RLS answer refused; serve --check blocked by its gate", log)
    say(root, "serve.row_security", "none", "gina")
    # H3: answers cannot inject code into the generated dashboard
    marker = TMP / "dwh_regression_injected"
    marker.unlink(missing_ok=True)
    say(root, "serve.title", f"x''' + __import__('pathlib').Path({str(marker)!r}).write_text('1') + '''", "priya")
    dwh(root, "publish")
    rc, out = dwh(root, "serve", "--check", expect=None)
    check(not marker.exists(), "H3: a title containing ''' and code is a string, never executed", log)


if __name__ == "__main__":
    log: list = []
    try:
        run(Path(sys.argv[1] if len(sys.argv) > 1 else RUNS / "regress").resolve(), log)
        if len(sys.argv) > 2:
            gold_and_serve(Path(sys.argv[2]).resolve(), log)
    except Fail as e:
        log.append(("FAIL", str(e)))
    for s, m in log:
        print(f"[{s}] {m}")
    sys.exit(0 if all(s == "PASS" for s, _ in log) else 1)
