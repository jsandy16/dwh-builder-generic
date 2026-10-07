"""Bronze: land every source exactly as received, behind file-level ingress gates.

* One table (text formats) or one immutable file set (typed formats) per source.
* Checkpoints are content-aware: same (batch, md5) is skipped; same batch with a new md5
  is a RE-DELIVERY and lands as a new _batch_version (or is rejected, per policy).
* The CSV dialect and columns are declared, never sniffed. Unparseable records go to a
  parse dead-letter, and the landed + rejected count must equal an independent record count.
* Nothing is written and no checkpoint is recorded for a rejected file.
"""
from __future__ import annotations

import csv
import fnmatch
import glob
import io
import os
import re
import shutil
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

from . import config as C
from . import egress, lineage
from .project import Project, audit, now_iso
from .runtime import Results, VerificationError, connect, heartbeat, ledger, ledger_write, qi, ql, qpath, table_exists
from .validators import TEXT_FORMATS

_TMP: list = []  # set by build(): the project's scratch folder for transcoded files
PROV_COLS = ["_src", "_batch_id", "_batch_version", "_source_file", "_row_number", "_ingested_at"]


class Rejected(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


class Transient(Exception):
    pass


# ---------------------------------------------------------------- batches
BATCH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def batch_key(spec: dict, batch: str):
    """Sort batches by the date their id encodes (31-01-2024 before 01-02-2024), else by text."""
    fr = (spec or {}).get("freshness") or {}
    fmt = fr.get("token_format") if str(fr.get("basis", "")).lower() == "batch_token" else None
    if fmt:
        try:
            return (0, datetime.strptime(batch, fmt).isoformat(), batch)
        except ValueError:
            pass
    return (1, batch, batch)


def discover(project: Project, name: str, spec: dict, only_batch: str | None = None) -> list[tuple[str, str]]:
    """[(batch_id, location)] in ascending batch order."""
    loc = spec["location"]
    if "{batch}" not in loc:
        return [("full", loc)]
    if only_batch:
        if not BATCH_ID.match(only_batch):
            raise Rejected("bad_batch_id", f"'{only_batch}': use letters, digits, '.', '_' or '-'")
        return [(only_batch, loc.replace("{batch}", only_batch))]
    if spec["connector"] == "http_file":
        raise Rejected("batch_required", "HTTP sources need --batch <id> (URLs cannot be listed)")
    pattern = str(project.p(loc.replace("{batch}", "*"))) if not os.path.isabs(loc) else loc.replace("{batch}", "*")
    rx = re.compile("^" + re.escape(loc if os.path.isabs(loc) else str(project.p(loc))).replace(
        re.escape("{batch}"), "(?P<b>.+?)") + "$")
    out = []
    for path in sorted(glob.glob(pattern)):
        m = rx.match(str(Path(path)))
        if m:
            out.append((m.group("b"), path))
    return sorted(out, key=lambda bp: batch_key(spec, bp[0]))


def fetch(project: Project, spec: dict, location: str, attempts: int) -> Path:
    """Exponential backoff (2, 4, 8 … seconds × DWH_RETRY_BASE). Never a flat sleep."""
    base = float(os.environ.get("DWH_RETRY_BASE", "1"))
    faults = int(os.environ.get("DWH_FAULT_FETCH", "0"))  # test hook: first N attempts fail
    for attempt in range(1, attempts + 1):
        try:
            if attempt <= faults:
                raise Transient(f"injected transient failure #{attempt}")
            if spec["connector"] == "http_file":
                dest = project.state / "downloads" / re.sub(r"[^A-Za-z0-9._-]", "_", location)[-120:]
                dest.parent.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(location)
                env = spec.get("credentials_env")
                if env and not C.is_token(env, C.NA_TOKEN) and os.environ.get(env):
                    req.add_header("Authorization", f"Bearer {os.environ[env]}")
                with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as out:
                    shutil.copyfileobj(r, out)
                return dest
            p = Path(location) if os.path.isabs(location) else project.p(location)
            if not p.exists():
                raise Rejected("file_not_found", str(location))
            return p
        except (Transient, OSError) as e:
            if isinstance(e, Rejected):
                raise
            wait = base * (2 ** attempt)
            audit(project, "bronze.retry", location=location, attempt=attempt, wait=wait, error=str(e)[:200])
            if attempt == attempts:
                raise Rejected("unreachable", f"{location} after {attempts} attempts: {e}") from e
            time.sleep(wait)
    raise Rejected("unreachable", location)


# ---------------------------------------------------------------- ingress
def _declared(spec: dict) -> dict:
    return spec["schema"]["columns"]


def _sq(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _csv_header_and_count(path: Path, spec: dict) -> tuple[list[str], int]:
    c = spec.get("csv") or {}
    enc = c.get("encoding", "utf-8")
    enc = "utf-8-sig" if enc.lower() in ("utf-8", "utf8") else enc  # tolerate a byte-order mark
    has_header = C.as_bool(c.get("header", "yes"))
    header, n = None, 0
    with open(path, encoding=enc, newline="") as fh:
        rdr = csv.reader(fh, delimiter=c.get("delimiter", ","), quotechar=c.get("quote", '"'),
                         escapechar=None if c.get("escape", '"') == c.get("quote", '"') else c.get("escape"),
                         doublequote=c.get("escape", '"') == c.get("quote", '"'))
        for row in rdr:  # streamed: multi-GB files never sit in memory
            if not row or (len(row) == 1 and not row[0].strip()):
                continue  # blank line — DuckDB skips these as well
            if header is None:
                header = [h.strip() for h in row] if has_header else [f"column{i}" for i in range(len(row))]
                if has_header:
                    continue
            n += 1
    return (header or []), n


def _norm_type(t: str) -> str:
    t = t.upper().strip()
    aliases = {"INT": "INTEGER", "INT4": "INTEGER", "INT8": "BIGINT", "FLOAT8": "DOUBLE", "STRING": "VARCHAR",
               "TEXT": "VARCHAR", "FLOAT4": "FLOAT", "REAL": "FLOAT", "TIMESTAMP_NS": "TIMESTAMP",
               "TIMESTAMP_US": "TIMESTAMP", "TIMESTAMP_MS": "TIMESTAMP"}
    base = t.split("(")[0]
    return aliases.get(base, base)


def gate_file(con, project: Project, name: str, spec: dict, batch: str, path: Path, led: dict) -> dict:
    """File-level gates. Returns facts; raises Rejected (nothing written) on failure."""
    fmt = spec["format"].lower()
    declared = _declared(spec)
    required = [c for c, s in declared.items() if C.as_bool((s or {}).get("required", "no"))]
    facts: dict = {"format": fmt}
    if fmt == "csv":
        header, records = _csv_header_and_count(path, spec)
        facts.update(columns=header, records=records)
        types = {}
    elif fmt == "parquet":
        desc = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
        header = [d[0] for d in desc]
        types = {d[0]: d[1] for d in desc}
        facts.update(columns=header, records=con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0])
    elif fmt in ("json", "jsonl"):
        desc = con.execute("DESCRIBE SELECT * FROM read_json_auto(?)", [str(path)]).fetchall()
        header = [d[0] for d in desc]
        types = {}
        facts.update(columns=header, records=con.execute("SELECT COUNT(*) FROM read_json_auto(?)", [str(path)]).fetchone()[0])
    elif fmt == "xlsx":
        import pandas as pd
        x = spec.get("xlsx") or {}
        df = pd.read_excel(path, sheet_name=x.get("sheet"), header=int(x.get("header_row", "1")) - 1, dtype=str)
        header = [str(c).strip() for c in df.columns]
        types = {}
        facts.update(columns=header, records=len(df), _frame=df)
    else:
        raise Rejected("unsupported_format", fmt)

    missing = [c for c in required if c not in header]
    if missing:
        raise Rejected("missing_required_columns", ", ".join(missing))
    unknown = [c for c in header if c not in declared]
    if unknown:
        if str(spec.get("drift_policy", "land_and_log")).lower() == "reject":
            raise Rejected("unexpected_columns", ", ".join(unknown))
        facts["drift_additive"] = unknown
    if types:  # typed formats: fingerprint against the declared types and the first batch
        reg = led.get(f"types|{name}", {})
        changes = []
        for c, t in types.items():
            if c in declared and _norm_type(t) != _norm_type(declared[c].get("type", t)):
                if not (_norm_type(t) in ("INTEGER", "BIGINT", "SMALLINT", "TINYINT")
                        and _norm_type(declared[c]["type"]) in ("BIGINT", "INTEGER", "DECIMAL", "DOUBLE")):
                    changes.append(f"{c}: declared {declared[c]['type']} got {t}")
            if c in reg and _norm_type(reg[c]) != _norm_type(t):
                changes.append(f"{c}: {reg[c]} -> {t} since the first batch")
        if changes:
            raise Rejected("type_change", "; ".join(changes) + " — route through dwh-schema-change")
        facts["types"] = types
    if facts["records"] == 0:
        raise Rejected("zero_rows", "a zero-row file is a broken source, never valid data")
    vol = spec.get("volume") or {}
    lo, hi = vol.get("min_rows"), vol.get("max_rows")
    if lo and not C.is_token(lo, C.NA_TOKEN) and facts["records"] < C.as_int(lo):
        raise Rejected("volume_out_of_bounds", f"{facts['records']} rows < min {lo}")
    if hi and not C.is_token(hi, C.NA_TOKEN) and facts["records"] > C.as_int(hi):
        raise Rejected("volume_out_of_bounds", f"{facts['records']} rows > max {hi}")
    _freshness(spec, batch, path, con, fmt)
    return facts


def _today() -> date:
    fixed = os.environ.get("DWH_FIXED_NOW")
    return datetime.fromisoformat(fixed).date() if fixed else date.today()


def _freshness(spec: dict, batch: str, path: Path, con, fmt: str) -> None:
    """Batch-token freshness, and column freshness for typed files, are checked before landing.
    Column freshness for text formats runs on the parsed rows (see _freshness_rows)."""
    fr = spec.get("freshness") or {}
    basis = str(fr.get("basis", "none")).lower()
    if basis == "none":
        return
    if basis == "batch_token":
        try:
            newest = datetime.strptime(batch, fr["token_format"]).date()
        except ValueError:
            raise Rejected("bad_batch_token", f"'{batch}' does not match {fr['token_format']}") from None
        _age_check(fr, newest)
    elif fmt == "parquet":
        col = fr["column"]
        v = con.execute(f'SELECT MAX(CAST({qi(col)} AS DATE)) FROM read_parquet(?)', [str(path)]).fetchone()[0]
        if v is None:
            raise Rejected("freshness_unknown", f"no dates in {col}")
        _age_check(fr, v)


def _freshness_rows(con, spec: dict, table: str) -> None:
    fr = spec.get("freshness") or {}
    if str(fr.get("basis", "none")).lower() != "column":
        return
    col, fmts = fr["column"], [str(f) for f in C.as_list(fr.get("formats"))]
    parse = "COALESCE(" + ", ".join(f"TRY_STRPTIME(CAST({qi(col)} AS VARCHAR), {ql(f)})" for f in fmts) + ")"
    v = con.execute(f"SELECT MAX(CAST({parse} AS DATE)) FROM {table}").fetchone()[0]
    if v is None:
        raise Rejected("freshness_unknown", f"no value of {col} matches the declared formats")
    _age_check(fr, v)


def _age_check(fr: dict, newest) -> None:
    window = C.as_int(fr.get("window_days"))
    age = (_today() - newest).days
    if age > window:
        raise Rejected("stale_batch", f"newest data {newest} is {age} days old (window {window} days)")


# ---------------------------------------------------------------- landing
def _land_text(con, name: str, spec: dict, batch: str, version: int, path: Path, facts: dict, at: str) -> dict:
    table = qi(f"bronze_{name}")
    header = facts["columns"]
    declared = list(_declared(spec).keys())
    all_cols = declared + [c for c in header if c not in declared]
    if not table_exists(con, f"bronze_{name}"):
        cols = ", ".join(f"{qi(c)} VARCHAR" for c in declared)
        con.execute(f"CREATE TABLE {table} ({cols}, _src VARCHAR, _batch_id VARCHAR, _batch_version INTEGER, "
                    f"_source_file VARCHAR, _row_number BIGINT, _ingested_at VARCHAR)")
    existing = {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}
    for c in all_cols:
        if c not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {qi(c)} VARCHAR")  # additive drift lands
    fmt = spec["format"].lower()
    rejects = []
    src_name, transcoded = path.name, None
    if fmt == "csv":
        c = spec.get("csv") or {}
        enc = str(c.get("encoding", "utf-8")).lower()
        if enc not in ("utf-8", "utf8"):
            path = transcoded = _transcode(path, enc)
            c = {**c, "encoding": "utf-8"}
        colmap = "{" + ", ".join(f"{ql(h)}: 'VARCHAR'" for h in header) + "}"
        nulls = [""] + [str(t) for t in C.as_list(c.get("null_tokens")) if not C.is_token(t, C.NA_TOKEN)]
        nullstr = "[" + ", ".join(_sq(n) for n in nulls) + "]"
        import hashlib
        rej = "rej_" + hashlib.md5(f"{name}|{batch}|{version}".encode()).hexdigest()[:12]
        q = (f"SELECT *, ROW_NUMBER() OVER () AS _rn FROM read_csv(?, columns={colmap}, auto_detect=false, "
             f"header={'true' if C.as_bool(c.get('header', 'yes')) else 'false'}, "
             f"delim={_sq(c.get('delimiter', ','))}, quote={_sq(c.get('quote', chr(34)))}, "
             f"escape={_sq(c.get('escape', chr(34)))}, encoding={_sq(c.get('encoding', 'utf-8'))}, "
             f"store_rejects=true, rejects_table='{rej}_e', rejects_scan='{rej}_s', nullstr={nullstr})")
        con.execute(f"CREATE TEMP TABLE _land AS {q}", [str(path)])
        # one entry per rejected RECORD (DuckDB logs one row per error, e.g. per missing column)
        rejects = con.execute(f"SELECT line, string_agg(DISTINCT error_type, '; ' ORDER BY error_type) "
                              f"FROM {rej}_e GROUP BY line ORDER BY line").fetchall()
        con.execute(f"DROP TABLE IF EXISTS {rej}_e; DROP TABLE IF EXISTS {rej}_s")
    elif fmt in ("json", "jsonl"):
        con.execute("CREATE TEMP TABLE _land AS SELECT *, ROW_NUMBER() OVER () AS _rn FROM read_json_auto(?)", [str(path)])
    elif fmt == "xlsx":
        df = facts.pop("_frame")
        df.columns = header
        con.register("_xl", df)
        con.execute("CREATE TEMP TABLE _land AS SELECT *, ROW_NUMBER() OVER () AS _rn FROM _xl")
        con.unregister("_xl")
    _freshness_rows(con, spec, "_land")
    landed_cols = {r[0] for r in con.execute("DESCRIBE _land").fetchall()}
    sel = ", ".join((f"CAST({qi(c)} AS VARCHAR) AS {qi(c)}" if c in landed_cols else f"NULL::VARCHAR AS {qi(c)}")
                    for c in all_cols)
    con.execute(f"INSERT INTO {table} BY NAME SELECT {sel}, ? AS _src, ? AS _batch_id, ? AS _batch_version, "
                f"? AS _source_file, _rn AS _row_number, ? AS _ingested_at FROM _land",
                [name, batch, version, src_name, at])
    landed = con.execute("SELECT COUNT(*) FROM _land").fetchone()[0]
    con.execute("DROP TABLE _land")
    if transcoded is not None:
        transcoded.unlink(missing_ok=True)
    return {"landed": landed, "parse_rejects": rejects}


def _land_typed(con, project: Project, name: str, spec: dict, batch: str, version: int, path: Path, at: str) -> dict:
    folder = project.loc("landed") / name
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{re.sub(r'[^A-Za-z0-9._-]', '_', batch)}__v{int(version)}.parquet"
    con.execute("CREATE OR REPLACE TEMP TABLE _typed_land AS SELECT *, ?::VARCHAR AS _src, ?::VARCHAR AS _batch_id, "
                "?::INTEGER AS _batch_version, ?::VARCHAR AS _source_file, ROW_NUMBER() OVER () AS _row_number, "
                "?::VARCHAR AS _ingested_at FROM read_parquet(?)", [name, batch, int(version), path.name, at, str(path)])
    con.execute(f"COPY _typed_land TO {qpath(dest)} (FORMAT PARQUET)")
    con.execute("DROP TABLE _typed_land")
    con.execute(f"CREATE OR REPLACE VIEW {qi('bronze_' + name)} AS SELECT * FROM "
                f"read_parquet({ql(folder.as_posix() + '/*.parquet')}, union_by_name=true)")
    landed = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(dest)]).fetchone()[0]
    return {"landed": landed, "parse_rejects": [], "file": str(dest.relative_to(project.root))}


def _transcode(path: Path, enc: str) -> Path:
    """DuckDB reads UTF-8 natively; other declared encodings are converted first (streamed)."""
    tmp = Path(_TMP[0]) if _TMP else path.parent
    tmp.mkdir(parents=True, exist_ok=True)
    out = tmp / f"utf8_{path.name}"
    with open(path, encoding=enc, newline="") as src, open(out, "w", encoding="utf-8", newline="") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
    return out


def _reject_file(project: Project, name: str, batch: str, path: str, reason: str, detail: str) -> None:
    out = project.loc("dead_letter") / "rejected_files.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    new = not out.exists()
    with open(out, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["source", "batch", "file", "reason", "detail", "rejected_at"])
        w.writerow([name, batch, Path(path).name, reason, detail[:500], now_iso()])
    audit(project, "bronze.rejected_file", source=name, batch=batch, reason=reason, detail=detail[:300])


def _write_parse_rejects(project: Project, name: str, batch: str, version: int, rejects: list) -> None:
    if not rejects:
        return
    out = project.loc("dead_letter") / f"parse_{name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    new = not out.exists()
    with open(out, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["source", "batch", "batch_version", "line", "error_type"])
        for line, err in rejects:
            w.writerow([name, batch, version, line, err])


# ---------------------------------------------------------------- build
def build(project: Project, res: Results | None = None, only_source: str | None = None,
          only_batch: str | None = None) -> Results:
    doc = project.document()
    sources = doc.get("sources") or {}
    led = ledger(project, "bronze")
    res = res or Results("bronze", only_source or "all sources")
    _TMP[:] = [str(project.state / "tmp")]
    at = now_iso()
    landed_total = skipped = rejected = 0
    drift_log = []
    con = connect(project)
    try:
        for name, spec in sources.items():
            if only_source and name != only_source:
                continue
            attempts = C.as_int(spec.get("retry_attempts") or "3") if not C.is_token(spec.get("retry_attempts", ""), C.NA_TOKEN) else 3
            try:
                batches = discover(project, name, spec, only_batch)
            except Rejected as e:
                _reject_file(project, name, only_batch or "?", spec["location"], e.reason, e.detail)
                rejected += 1
                continue
            if not batches:
                res.check(f"B-{name}-found", f"{name}: files found", False, ">= 1 file", 0,
                          detail=f"nothing matches {spec['location']}")
                continue
            for batch, location in batches:
                key = f"{name}|{batch}"
                heartbeat()
                try:
                    if not BATCH_ID.match(batch):
                        raise Rejected("bad_batch_id", f"'{batch}': use letters, digits, '.', '_' or '-'")
                    path = fetch(project, spec, location, attempts)
                    md5 = C.file_md5(path)
                    prev = led.get(key)
                    if prev and prev.get("md5") == md5:
                        skipped += 1
                        audit(project, "bronze.skip", source=name, batch=batch, reason="same content")
                        continue
                    version = 1
                    if prev:
                        if str(spec.get("redelivery_policy", "replace")).lower() == "reject":
                            raise Rejected("redelivery_rejected", f"batch {batch} re-delivered with new content")
                        version = int(prev["version"]) + 1
                    facts = gate_file(con, project, name, spec, batch, path, led)
                    con.execute("BEGIN")
                    try:
                        if spec["format"].lower() == "parquet":
                            out = _land_typed(con, project, name, spec, batch, version, path, at)
                        else:
                            out = _land_text(con, name, spec, batch, version, path, facts, at)
                        n_rej = len(out["parse_rejects"])
                        same = facts["records"] == out["landed"] + n_rej
                        res.check(f"V09-{name}-{batch}", f"{name} {batch}: records = landed + parse rejects",
                                  same, facts["records"], out["landed"] + n_rej, evaluated=facts["records"],
                                  fatal=False, detail="" if same else "file rejected: counts disagree, nothing landed")
                        if not same:
                            raise Rejected("record_count_mismatch",
                                           f"{facts['records']} records counted, {out['landed']} landed + {n_rej} unparseable")
                        con.execute("COMMIT")
                    except BaseException:
                        con.execute("ROLLBACK")
                        if out_file := locals().get("out", {}).get("file"):
                            project.p(out_file).unlink(missing_ok=True)
                        raise
                    _write_parse_rejects(project, name, batch, version, out["parse_rejects"])
                    led[key] = {"md5": md5, "version": version, "records": facts["records"],
                                "landed": out["landed"], "parse_rejects": n_rej, "at": at,
                                "file": str(path.name), "redelivery": version > 1}
                    if facts.get("types"):
                        led.setdefault(f"types|{name}", facts["types"])
                    if facts.get("drift_additive"):
                        drift_log.append({"source": name, "batch": batch, "new_columns": facts["drift_additive"],
                                          "classification": "additive", "action": "landed and logged"})
                    ledger_write(project, "bronze", led)  # after COMMIT only
                    landed_total += out["landed"]
                    audit(project, "bronze.landed", source=name, batch=batch, version=version,
                          landed=out["landed"], parse_rejects=n_rej)
                except Rejected as e:
                    _reject_file(project, name, batch, location, e.reason, e.detail)
                    rejected += 1
        res.facts.update(landed_rows=landed_total, skipped_batches=skipped, rejected_files=rejected)
    finally:
        con.close()
    if drift_log:
        old = C.read_json(project.loc("schema_drift"), []) or []
        C.atomic_write_json(project.loc("schema_drift"), old + drift_log)
    lineage.register(project, "dwh-bronze",
                     [{"id": f"src_{n}", "label": f"{n} ({s.get('format')})", "layer": "source"} for n, s in sources.items()]
                     + [{"id": f"bronze_{n}", "label": f"bronze_{n}", "layer": "bronze"} for n in sources],
                     [{"from": f"src_{n}", "to": f"bronze_{n}", "label": "land as received"} for n in sources])
    return res
