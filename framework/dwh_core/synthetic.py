"""Synthetic source files generated FROM bronze's declared schema, with a planted-truth ledger.

    dwh synth            write the files + synthetic/truth_<source>.csv, flag the project as synthetic
    dwh synth --score    after silver: score every planted row against silver's outcome (V21)

Defect classes: null (empty value), cast (unparseable text in a typed column), domain (value
outside allowed_values), duplicate (exact copy of an earlier row). The score is a confusion
matrix; a planted defect that reached silver, or a clean row dead-lettered for a structural
reason, fails the check.
"""
from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from . import config as C
from .project import Project, audit, now_iso
from .runtime import Results, connect, table_exists

DEFECTS = ("null", "cast", "domain", "duplicate")
TYPED = ("INT", "BIGINT", "SMALLINT", "TINYINT", "DECIMAL", "DOUBLE", "FLOAT", "NUMERIC", "DATE", "TIMESTAMP",
         "BOOLEAN")


def _na(v) -> bool:
    return C.is_blank(v) or C.is_token(v, C.NA_TOKEN) or C.is_token(v, C.NONE_TOKEN)


def _period(src: dict, syn: dict, batch: str) -> tuple[date, date]:
    fr = src.get("freshness") or {}
    if str(fr.get("basis", "")).lower() == "batch_token" and fr.get("token_format"):
        try:
            start = datetime.strptime(batch, fr["token_format"]).date()
            fmt = fr["token_format"]
            if "%d" in fmt:
                return start, start
            nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            return start, nxt - timedelta(days=1)
        except ValueError:
            pass
    dr = syn.get("date_range")
    if isinstance(dr, list) and len(dr) == 2:
        return (datetime.strptime(dr[0], "%Y-%m-%d").date(), datetime.strptime(dr[1], "%Y-%m-%d").date())
    end = datetime.fromisoformat(now_iso()).date()
    return end - timedelta(days=30), end


def _value(rng: random.Random, col: str, cs: dict, hint: dict, i: int, batch: str, period, bi: int):
    t = str(cs.get("type", "VARCHAR")).upper()
    if hint.get("null_rate") and rng.random() * 100 < float(hint["null_rate"]):
        return None
    if C.as_bool(hint.get("sequence", "no") or "no"):
        return i + 1
    if isinstance(hint.get("choices"), list):
        return rng.choice(hint["choices"])
    av = cs.get("allowed_values")
    if isinstance(av, list) and av and not C.is_token(av, C.NA_TOKEN):
        return rng.choice(av)
    rg = hint.get("range") if isinstance(hint.get("range"), list) else None
    if C.as_bool(cs.get("key", "no") or "no"):
        if t.startswith(("INT", "BIGINT", "SMALLINT")):
            return bi * 1_000_000 + i + 1
        return f"{col[:3].upper()}-{batch}-{i + 1:07d}"
    if t.startswith(("INT", "BIGINT", "SMALLINT", "TINYINT")):
        lo, hi = (int(rg[0]), int(rg[1])) if rg else (1, 100)
        return rng.randint(lo, hi)
    if t.startswith(("DECIMAL", "DOUBLE", "FLOAT", "NUMERIC")):
        lo, hi = (float(rg[0]), float(rg[1])) if rg else (0.0, 500.0)
        return Decimal(str(round(rng.uniform(lo, hi), 2)))
    if t == "BOOLEAN":
        return rng.choice(["true", "false"])
    if t in ("DATE", "TIMESTAMP"):
        a, b = period
        d = a + timedelta(days=rng.randint(0, max(0, (b - a).days)))
        if t == "DATE":
            return d
        return datetime(d.year, d.month, d.day, rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59))
    return f"{col}_{rng.randint(1, 40)}"


def _text(v, cs: dict, hint: dict) -> str:
    if v is None:
        return ""
    t = str(cs.get("type", "")).upper()
    if t == "DATE" and isinstance(v, date):
        return v.strftime(hint.get("format") or "%Y-%m-%d")
    if t == "TIMESTAMP" and isinstance(v, datetime):
        return v.strftime(hint.get("format") or "%Y-%m-%d %H:%M:%S")
    return str(v)


def generate_source(project: Project, name: str, src: dict, syn: dict) -> dict:
    cols = (src.get("schema") or {}).get("columns") or {}
    hints = syn.get("columns") if isinstance(syn.get("columns"), dict) else {}
    defects = {} if _na(syn.get("defects")) else {k: float(v) for k, v in syn["defects"].items()}
    seed = C.as_int(syn.get("seed"))
    n = C.as_int(syn.get("rows_per_batch"))
    fmt = str(src.get("format")).lower()
    truth_rows, written = [], []
    for bi, batch in enumerate([str(b) for b in C.as_list(syn.get("batches"))]):
        rng = random.Random(f"{seed}|{name}|{batch}")
        period = _period(src, syn, batch)
        rows, truth = [], []
        keys = [c for c, cs in cols.items() if C.as_bool((cs or {}).get("key", "no") or "no")]
        for i in range(n):
            vals = {c: _value(rng, c, cs or {}, hints.get(c) or {}, i, batch, period, bi) for c, cs in cols.items()}
            for c, h in hints.items():  # {after: <col>, minutes: [lo, hi]} keeps event order realistic
                if isinstance(h, dict) and h.get("after") in vals and isinstance(vals[h["after"]], datetime):
                    lo, hi = (int(x) for x in (h.get("minutes") or [1, 60]))
                    vals[c] = vals[h["after"]] + timedelta(minutes=rng.randint(lo, hi), seconds=rng.randint(0, 59))
            cls, col = "clean", ""
            roll = rng.random() * 100
            acc = 0.0
            for d in ("null", "cast", "domain"):
                acc += defects.get(d, 0)
                if roll < acc:
                    cand = [c for c, cs in cols.items() if c not in keys and (
                        d == "null" or (d == "cast" and fmt == "csv" and str((cs or {}).get("type", "")).upper().startswith(TYPED))
                        or (d == "domain" and isinstance((cs or {}).get("allowed_values"), list)))]
                    if cand:
                        col = rng.choice(sorted(cand))
                        cls = d
                        numeric = str((cols[col] or {}).get("type", "")).upper().startswith(TYPED)
                        vals[col] = None if d == "null" else ("#ERR" if d == "cast" else
                                                              ("987654" if numeric else "ZZZ_UNKNOWN"))
                    break
            rows.append(vals)
            truth.append({"row": i + 1, "class": cls, "column": col, "dup_of": ""})
        ndup = int(round(n * defects.get("duplicate", 0) / 100))
        clean_idx = [k for k, t in enumerate(truth) if t["class"] == "clean"]
        for _ in range(ndup if clean_idx else 0):
            j = rng.choice(clean_idx)
            rows.append(dict(rows[j]))
            truth.append({"row": len(rows), "class": "duplicate", "column": "", "dup_of": j + 1})
        loc = src["location"].replace("{batch}", batch)
        path = project.p(loc)
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "csv":
            c = src.get("csv") or {}
            with open(path, "w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh, delimiter=c.get("delimiter", ","), quotechar=c.get("quote", '"'),
                               lineterminator="\n")
                if C.as_bool(c.get("header", "yes")):
                    w.writerow(list(cols))
                for r in rows:
                    w.writerow([_text(r[col], cols[col] or {}, hints.get(col) or {}) for col in cols])
        elif fmt == "parquet":
            import pandas as pd
            df = pd.DataFrame(rows, columns=list(cols))
            con = connect(project)
            try:
                con.register("_syn", df)
                sel = ", ".join(f'TRY_CAST("{c}" AS {(cs or {}).get("type", "VARCHAR")}) AS "{c}"' for c, cs in cols.items())
                con.execute(f"COPY (SELECT {sel} FROM _syn) TO '{path.as_posix()}' (FORMAT PARQUET)")
                con.unregister("_syn")
            finally:
                con.close()
        else:
            raise ValueError(f"synthetic generation supports csv and parquet, not {fmt}")
        for t in truth:
            truth_rows.append({"source": name, "batch": batch, "file": path.name, **t})
        written.append(str(path.relative_to(project.root)))
    out = project.loc("synthetic_truth") / f"truth_{name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["source", "batch", "file", "row", "class", "column", "dup_of"])
        w.writeheader()
        w.writerows(truth_rows)
    return {"files": written, "truth": str(out.relative_to(project.root)), "rows": len(truth_rows),
            "planted": {d: sum(1 for t in truth_rows if t["class"] == d) for d in DEFECTS}}


def run(project: Project) -> int:
    from .intake import check
    rep = check(project, "synthetic", "A")
    if not rep.ok:
        print("BLOCKED — the synthetic generator needs these inputs first:\n\n" + rep.render())
        return 2
    doc = project.document()
    report = {}
    for name, syn in (C.get_path(doc, "synthetic.sources") or {}).items():
        report[name] = generate_source(project, name, doc["sources"][name], syn)
    C.atomic_write_json(project.state / "synthetic.json", {"generated_at": now_iso(), "sources": report})
    audit(project, "synth.generate", sources=list(report))
    for name, r in report.items():
        print(f"{name}: {len(r['files'])} file(s), {r['rows']} rows, planted {r['planted']} → truth ledger {r['truth']}")
    print("note: the project is now flagged SYNTHETIC — dashboards show a banner; thresholds tuned here must be "
          "re-confirmed on real data.")
    return 0


# ================================================================ scoring (V21)
def _expected(doc: dict, entity: str, source: str, cls: str, col: str) -> tuple[str, str]:
    """(expected outcome, expected reason) for a planted row."""
    from .silver import Plan
    P = Plan(doc, entity)
    canon = None
    for c in P.types:
        if P.raw_source_column(source, c) == col:
            canon = c
            break
    if cls == "clean" or cls == "duplicate":
        return "kept", ""
    if canon is None:
        return "kept", ""  # the column is dropped in silver: the defect cannot matter
    if cls == "cast":
        return "dead_letter", f"cast_{canon}"
    if cls == "domain":
        return "dead_letter", f"domain_{canon}"
    if cls == "null":
        if canon in P.key:
            return "dead_letter", "null_key"
        pol = P.null_policy.get(canon, "keep").lower()
        if pol == "drop" and P.structural_cond(source, canon) != "TRUE":
            return "dead_letter", f"null_{canon}"
        return "kept", ""
    return "kept", ""


def score(project: Project) -> int:
    from .silver import DL_TABLE, entities
    doc = project.document()
    res = Results("synthetic", "planted truth vs silver")
    con = connect(project, read_only=False)
    matrix: dict = {}
    try:
        for e, spec in entities(doc).items():
            for s in C.as_list((spec or {}).get("sources")):
                tf = project.loc("synthetic_truth") / f"truth_{s}.csv"
                if not tf.exists() or not table_exists(con, DL_TABLE):
                    continue
                dl = {(r[0], int(r[1])): r[2] for r in con.execute(
                    f"SELECT source_file, row_number, reason FROM {DL_TABLE} WHERE entity = ? AND src = ?",
                    [e, s]).fetchall()}
                with open(tf, encoding="utf-8") as fh:
                    truth = list(csv.DictReader(fh))
                missed, false_pos, wrong_reason, rule_rejects = 0, 0, 0, 0
                for t in truth:
                    exp, why = _expected(doc, e, s, t["class"], t["column"])
                    got = dl.get((t["file"], int(t["row"])))
                    outcome = "dead_letter" if got else "kept"
                    key = (t["class"], exp, outcome)
                    matrix[key] = matrix.get(key, 0) + 1
                    if exp == "dead_letter" and not got:
                        missed += 1
                    elif exp == "dead_letter" and got != why:
                        wrong_reason += 1
                    elif exp == "kept" and got:
                        if got.startswith(("cast_", "null_", "domain_")):
                            false_pos += 1
                        else:
                            rule_rejects += 1
                planted = sum(1 for t in truth if t["class"] not in ("clean", "duplicate"))
                if planted:
                    res.check(f"V21-{e}-{s}-missed", f"{e}/{s}: every planted defect was dead-lettered", missed == 0,
                              0, missed, evaluated=planted)
                    res.check(f"V21-{e}-{s}-reason", f"{e}/{s}: dead-letter reason matches the planted defect",
                              wrong_reason == 0, 0, wrong_reason, evaluated=planted)
                else:
                    res.check(f"V21-{e}-{s}-missed", f"{e}/{s}: planted defects", True, "n/a", "none planted",
                              fatal=False, detail="this source was generated clean (defects: none)")
                res.check(f"V21-{e}-{s}-falsepos", f"{e}/{s}: no clean row dead-lettered for a structural reason",
                          false_pos == 0, 0, false_pos, evaluated=len(truth))
                res.facts[f"{e}/{s} clean rows rejected by business rules"] = rule_rejects
    finally:
        con.close()
    res.facts["confusion (planted class, expected, observed) → rows"] = {f"{a}|{b}|{c}": n for (a, b, c), n
                                                                          in sorted(matrix.items())}
    path = res.write(project, "synthetic-score", "Synthetic planted-truth score (V21)",
                     "**PASS**" if not res.failures else "**FAILED**")
    for c in res.checks:
        print(f"[{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.actual}")
    print(f"report: {path.relative_to(project.root)}")
    return 0 if not res.failures else 1
