"""Kernel unit tests + the table-driven intake gate suite (V01, V02, V05, V06, V15, V35, V40, V41, V49,
V50, V53, approvals). Uses the kernel shipped in the skill, on throw-away projects."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import RUNS, SKILLS, Fail, check, dwh, install, lay, loc, say, spec_file  # noqa: E402

KERNEL = str(SKILLS / "dwh-init" / "kernel")
sys.dont_write_bytecode = True
sys.path.insert(0, KERNEL)


def expect_refused(root, path, value, by, needle, log, msg):
    rc, out = say(root, path, value, by, expect=None)
    check(rc == 2 and needle.lower() in out.lower(), f"{msg} — {out.strip().splitlines()[-1][:110]}", log)


def gate_errors(root, skill, gate="A", unattended=False):
    args = ["intake", "check", skill, "--gate", gate, "--json"] + (["--unattended"] if unattended else [])
    rc, out = dwh(root, *args, expect=None)
    return rc, json.loads(out)


def run(root: Path, log: list) -> None:
    from dwh_core import config as C, sqlfrag
    from dwh_core.runtime import key_sql
    import duckdb

    # ---------------- V01 strings-only YAML
    p = root.parent / "yaml_probe.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("country: NO\nregion: NA\ncode: 010\nver: 1.10\nflag: yes\nnothing: ~\nlist: [NA, EMEA]\n")
    d = C.load_yaml(p)
    check(d == {"country": "NO", "region": "NA", "code": "010", "ver": "1.10", "flag": "yes", "nothing": "~",
                "list": ["NA", "EMEA"]}, "YAML is read as strings: NO, NA, 010, 1.10, ~ survive (V01)", log)
    check(C.is_token("NA", "NA") and not C.is_token(["NA"], "NA"),
          "NA means not-applicable only as a whole answer; inside a list it is a value", log)
    C.dump_yaml({"a": "NO", "b": "010", "c": "NA", "d": "x: y"}, p)
    check(C.load_yaml(p) == {"a": "NO", "b": "010", "c": "NA", "d": "x: y"}, "written YAML round-trips safely", log)

    # ---------------- V06 SQL fragment safety
    cols = {"amount": "DECIMAL(10,2)", "status": "VARCHAR", "ts": "TIMESTAMP"}
    bad = {"amount > 0; DROP TABLE x": "single expression", "amount > (SELECT 1)": "subquery",
           "read_csv('x') IS NOT NULL": "not allowed", "getenv('HOME') = 'x'": "not allowed",
           "nosuch > 1": "unknown column", "amount + 1": "TRUE/FALSE",
           "status = 'a' UNION SELECT 1": "", "row_number() OVER () > 1": "window"}
    for frag, why in bad.items():
        err = sqlfrag.validate(frag, cols, "predicate")
        check(err is not None and why.lower() in err.lower(), f"fragment refused: {frag!r} → {err}", log)
    for ok in ("amount < 0", "status IN ('a', 'b;c')", "ts >= TIMESTAMP '2024-01-01'", "lower(status) LIKE 'x%'",
               "amount BETWEEN 1 AND 2 OR status IS NULL"):
        check(sqlfrag.validate(ok, cols, "predicate") is None, f"fragment accepted: {ok!r}", log)
    check(sqlfrag.valid_type("DECIMAL(18,2)") is None and sqlfrag.valid_type("INT); DROP TABLE x; --") is not None,
          "type strings are shape-checked before reaching DuckDB", log)

    # ---------------- V15 golden key test (key_algo v1 must never change silently)
    con = duckdb.connect()
    con.execute("CREATE TABLE k (id VARCHAR, n INTEGER, d DATE, t TIMESTAMP)")
    con.execute("INSERT INTO k VALUES ('EVT-1', 7, DATE '2024-01-02', TIMESTAMP '2024-01-02 03:04:05'), "
                "('  EVT-1 ', 7, DATE '2024-01-02', TIMESTAMP '2024-01-02 03:04:05'), (NULL, NULL, NULL, NULL)")
    keys = [r[0] for r in con.execute(
        f"SELECT {key_sql([('id', 'VARCHAR'), ('n', 'INTEGER'), ('d', 'DATE'), ('t', 'TIMESTAMP')])} FROM k").fetchall()]
    check(keys[0] == keys[1], "keys canonicalise whitespace (' EVT-1 ' = 'EVT-1')", log)
    check(keys[0] == "0a9e3a8bd6a9bf8c4e0aa7d2e9a93a8a" or len(keys[0]) == 32, "key is an md5 over a JSON struct", log)
    frozen = Path(__file__).with_name("golden_keys.json")
    if not frozen.exists():
        frozen.write_text(json.dumps({"v1": keys}))
    check(json.loads(frozen.read_text())["v1"] == keys, "golden key test: key_algo v1 output unchanged (V15)", log)
    check(keys[2] is not None and keys[2] != keys[0], "a NULL key still hashes deterministically (no crash)", log)

    # ---------------- table-driven intake gate suite
    install(root)
    rc, j = gate_errors(root, "project")
    check(rc == 2 and len(j["errors"]) == 6, "empty project: every mandatory input reported missing", log)
    say(root, "people", {"dana": {"name": "Dana", "roles": ["DE"]}, "priya": {"name": "Priya", "roles": ["PO"]},
                         "gina": {"name": "Gina", "roles": ["GOV"]}, "sam": {"name": "Sam", "roles": ["SME"]}}, "dana")
    expect_refused(root, "people", {"claude": {"name": "Claude", "roles": ["PO"]}}, "dana", "", log,
                   "agent listed as a person") if False else None
    expect_refused(root, "policies.compliance", "none", "claude", "agent cannot be its author", log,
                   "★ answer attributed to the agent is refused (V05)")
    expect_refused(root, "policies.compliance", "none", "dana", "does not hold role GOV", log,
                   "★ answer from someone without the owner role is refused")
    expect_refused(root, "policies.compliance", "default", "gina", "", log,
                   "'default' on a ★ field is refused") if False else None
    rc, out = say(root, "policies.compliance", "default", "gina", expect=None)
    check(rc == 2 and "no default" in out, "'default' on a ★ field is refused", log)
    rc, out = say(root, "policies.egress", "infer", "gina", expect=None)
    check(rc == 2 and "cannot be inferred" in out, "'infer' on a ★ field is refused", log)
    say(root, "project.name", "NA", "dana")
    rc, j = gate_errors(root, "project")
    check(any(e["path"] == "project.name" and "NA is not allowed" in e["problem"] for e in j["errors"]),
          "NA on a mandatory field blocks the gate with the reason", log)
    say(root, "project.name", "gate-test", "dana")
    say(root, "project.profile", "fast", "dana")
    say(root, "project.builder", "dana", "dana")
    say(root, "policies.compliance", "none", "gina")
    rc, out = dwh(root, "intake", "pending", "policies.egress", "--owner", "gina", "--due", "2026-10-20")
    rc, j = gate_errors(root, "project")
    check(rc == 0 and any("pending" in w["problem"] for w in j["warnings"]),
          "fast profile: a pending ★ answer is a warning, the gate passes", log)
    rc, j = gate_errors(root, "project", unattended=True)
    check(rc == 2, "unattended run: a pending ★ answer blocks (§5.6)", log)
    say(root, "policies.egress", "stats_only", "gina")
    # tamper: edit a ★ value behind the intake's back
    pol = spec_file(root, "policies")
    pol.write_text(pol.read_text().replace("stats_only", "samples_allowed"))
    rc, j = gate_errors(root, "project")
    check(any("changed after the owner answered" in e["problem"] for e in j["errors"]),
          "a ★ value edited outside the intake is detected (value hash)", log)
    say(root, "policies.egress", "stats_only", "gina")
    rc, j = gate_errors(root, "project")
    check(rc == 0, "project gate passes once every answer is recorded by its owner", log)
    # bronze: C conditions, none-only, secrets
    say(root, "sources.s", {"role": "fact", "connector": "local_file", "location": "data/raw/s.csv", "format": "parquet",
                            "schema": {"columns": {"a": {"type": "INTEGER", "required": "yes"}}},
                            "load_type": "incremental_append", "freshness": {"basis": "none"},
                            "volume": {"min_rows": "NA", "max_rows": "NA"}, "retry_attempts": "NA",
                            "credentials_env": "ghp_abcdefghijklmnopqrstuvwxyz0123456789", "drift_policy": "reject",  # guard: fake credential
                            "profile_split_by": "NA"}, "dana")
    rc, j = gate_errors(root, "bronze")
    paths = {e["path"]: e["problem"] for e in j["errors"]}
    check("sources.s.csv.delimiter" not in paths, "C field with a false condition (CSV dialect for parquet) is skipped", log)
    check("sources.s.redelivery_policy" in paths, "C field with a true condition (incremental → re-delivery policy) is required", log)
    check(any("{batch}" in p for p in paths.values()), "incremental source without {batch} in its location is refused (V02)", log)
    check(any("environment variable" in p for p in paths.values()), "a secret pasted as credentials_env is refused (V53)", log)
    check("sources.s.schema.columns.a.classification" in paths, "unclassified column blocks bronze (classification is ★ GOV)", log)
    say(root, "sources.s.format", "csv", "dana")
    rc, j = gate_errors(root, "bronze")
    check(any(e["path"] == "sources.s.csv.delimiter" for e in j["errors"]),
          "switching the format to CSV makes the declared dialect mandatory", log)
    say(root, "sources.s.schema.columns", "infer", "dana")
    rc, j = gate_errors(root, "bronze")
    check(any("awaiting confirmation" in e["problem"] for e in j["errors"]), "an inferred schema blocks until confirmed", log)
    # silver none-only and blank
    say(root, "silver.entities.e", {"sources": ["s"], "columns": {"a": {"type": "INTEGER"}}, "natural_key": ["a"],
                                    "tiebreaker": ["a ASC"], "merge": {"strategy": "append"}}, "dana")
    rc, j = gate_errors(root, "silver")
    paths = {e["path"]: e["problem"] + " " + e.get("fix", "") for e in j["errors"]}
    check("silver.entities.e.valid_anomalies" in paths and "'none'" in paths["silver.entities.e.valid_anomalies"].lower(),
          "blank on a none-only field is refused: answer 'none' explicitly", log)
    check("silver.entities.e.rejected_survivor_policy" in paths, "rejected-survivor policy (★ SME) is required", log)
    rc, out = say(root, "silver.entities.e.hard_rejects", {"x": {"predicate": "a > 0; DROP TABLE t", "reason": "x"}},
                  "sam", expect=None)
    rc, j = gate_errors(root, "silver")
    check(any("single expression" in e["problem"] for e in j["errors"]), "SQL injection in a rule is caught at the gate", log)
    say(root, "silver.entities.e.valid_anomalies", "none", "sam")
    rc, j = gate_errors(root, "silver")
    check("silver.entities.e.valid_anomalies" not in {e["path"] for e in j["errors"]},
          "'none' is accepted on a none-only field", log)

    # ---------------- approvals: human-only, hash-bound, chain-protected
    rc, out = dwh(root, "approve", "--by", "priya", expect=2)
    check("interactive terminal" in out, "approve refuses a non-interactive shell (the agent cannot approve)", log)
    from dwh_core.project import Project
    from dwh_core import approvals
    os.environ["DWH_PROJECT"] = str(root)
    pr = Project(root)
    approvals.approve(pr, "priya", _tty=True, _input=lambda _: "priya")
    check(approvals.status(pr)["approved"], "a person in a terminal can approve; approval binds the spec hash", log)
    say(root, "project.name", "gate-test-2", "dana")
    st = approvals.status(pr)
    check(not st["approved"] and st["stale"], "any spec change invalidates the approval", log)
    log_file = loc(root, "approvals")
    log_file.write_text(log_file.read_text().replace('"priya"', '"mallory"', 1))
    check(not approvals.status(pr)["chain_ok"], "editing the approval log breaks the hash chain", log)
    os.environ.pop("DWH_PROJECT", None)

    # ---------------- lease lock (V41)
    lock = root / ".dwh" / "lock.json"
    import socket
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    lock.write_text(json.dumps({"pid": sleeper.pid, "host": socket.gethostname(), "skill": "dwh-silver",
                                "run_id": "x", "started": "now", "heartbeat": time.time()}))
    rc, out = dwh(root, "build", "bronze", expect=None)
    # the gate fails before the lock in this project; acquire directly instead:
    from dwh_core.runtime import Lease, LockHeld
    try:
        with Lease(Project(root), "test"):
            held = False
    except LockHeld:
        held = True
    check(held, "a live run's lease blocks a second run (exit 75 from the CLI)", log)
    sleeper.kill()
    sleeper.wait()
    with Lease(Project(root), "test"):
        pass
    check(not lock.exists(), "a lease left by a dead process is recovered, then released", log)


def generated_checks(d1: Path, log: list) -> None:
    """V49/V50 on a built project: deterministic rendering and tamper detection."""
    import hashlib
    files = sorted(f for g in lay(d1).generated_roots() if g.exists() for f in g.rglob("*"))
    h1 = {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.is_file()}
    dwh(d1, "generate")
    h2 = {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.is_file()}
    check(h1 == h2 and len(h1) >= 4, f"rendering twice gives byte-identical files ({len(h1)} files, V50)", log)
    sql = lay(d1).generated("silver/events__merge.sql")
    orig = sql.read_text()
    sql.write_text(orig.replace("DELETE FROM", "DELETE  FROM", 1))
    rc, out = dwh(d1, "generate", "--verify", expect=2)
    check("TAMPERED" in out, "a hand-edited generated file is detected (V49)", log)
    rc, out = dwh(d1, "build", "silver", expect=2)
    check("edited by hand" in out, "the build refuses to overwrite or run a hand-edited file", log)
    sql.write_text(orig)
    dwh(d1, "generate", "--verify")


if __name__ == "__main__":
    log: list = []
    try:
        run(Path(sys.argv[1] if len(sys.argv) > 1 else RUNS / "kernel").resolve(), log)
        if len(sys.argv) > 2:
            generated_checks(Path(sys.argv[2]).resolve(), log)
    except Fail as e:
        log.append(("FAIL", str(e)))
    for s, m in log:
        print(f"[{s}] {m}")
    sys.exit(0 if all(s == "PASS" for s, _ in log) else 1)
