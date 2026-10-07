"""Default answers for the intake workbook.

The workbook shows every question of every layer with a default the owner keeps or changes.
Defaults come from, in increasing priority:

  1. the catalogue's documented default          (e.g. dead-letter tolerance 5 %)
  2. the stats-only analysis of the sample files (types, keys, empty counts, date formats)
  3. the assistant's draft, config/intake/draft.yaml — what it proposes after reading the
     requirements and any data documentation (entity names, rules, KPIs …), with a note per
     path saying why
  4. answers already recorded by a person (shown as the current answer)

Nothing here is recorded as an answer. Only the owner's submitted workbook is.
"""
from __future__ import annotations

import copy
import re
from datetime import date
from pathlib import Path
from typing import Any

from . import analyze as A
from . import catalogue as K
from . import config as C
from . import sqlfrag
from .project import Project

DRAFT_FILE = ("config", "intake", "draft.yaml")
NO_DEFAULT = {"golden_values", "readback_confirmed"}  # a default would make the check prove itself


def draft_path(project: Project) -> Path:
    return project.loc("draft")


def load_draft(project: Project) -> tuple[dict, dict]:
    raw = C.load_yaml(draft_path(project))
    raw = raw if isinstance(raw, dict) else {}
    notes = raw.pop("notes", {}) if isinstance(raw.get("notes"), dict) else {}
    raw.pop("notes", None)
    return raw, {str(k): str(v) for k, v in notes.items()}


def _merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = _merge(base.get(k), v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(over) if over is not None else copy.deepcopy(base)


def canon(name: str) -> str:
    """A canonical silver column name for a source column (identifier, lower case)."""
    if sqlfrag.valid_identifier(name):
        return name
    s = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower() or "col"
    return "c_" + s if s[0].isdigit() else s


class Proposal:
    def __init__(self, doc: dict, notes: dict, analysis: dict):
        self.doc = doc            # spec-shaped proposed answers
        self.notes = notes        # path -> why this default
        self.analysis = analysis  # stats-only facts

    def get(self, path: str, default: Any = None) -> Any:
        v = C.get_path(self.doc, path)
        return default if v is None else v

    def note(self, path: str) -> str:
        return self.notes.get(path, "")


def _setdefault(doc: dict, notes: dict, path: str, value: Any, why: str = "") -> None:
    if C.get_path(doc, path) is None:
        C.set_path(doc, path, value)
        if why and path not in notes:
            notes[path] = why


def compose(project: Project, run_analysis: bool = True) -> Proposal:
    draft, notes = load_draft(project)
    doc: dict = copy.deepcopy(draft)
    sources = doc.get("sources") if isinstance(doc.get("sources"), dict) else {}
    if not sources:
        sources = C.get_path(project.document(), "sources") or {}
        doc["sources"] = copy.deepcopy(sources)
    for s in list((doc.get("sources") or {}).keys()):
        _source_basics(doc, notes, s)  # format and dialect first: the analysis reads the files with them
    analysis = A.run(project, doc.get("sources") or {}) if run_analysis else A.load(project)
    _project(project, doc, notes)
    _policies(doc, notes)
    for s in list((doc.get("sources") or {}).keys()):
        _source(doc, notes, s, (analysis.get("sources") or {}).get(s) or {})
    _silver(doc, notes, analysis)
    _metrics(doc, notes)
    _serve(doc, notes)
    return Proposal(doc, notes, analysis)


# ---------------------------------------------------------------- per namespace
def _people_with(doc: dict, role: str) -> list[str]:
    out = []
    for pid, rec in (doc.get("people") or {}).items() if isinstance(doc.get("people"), dict) else []:
        if isinstance(rec, dict) and role in {str(r).strip().upper() for r in C.as_list(rec.get("roles"))}:
            out.append(pid)
    return out


def _project(project: Project, doc: dict, notes: dict) -> None:
    doc.setdefault("people", {})
    name = re.sub(r"[^0-9a-zA-Z-]+", "-", project.root.name).strip("-").lower() or "warehouse"
    _setdefault(doc, notes, "project.name", name, "the project folder's name")
    _setdefault(doc, notes, "project.profile", "fast",
                "first dashboard quickly; ★ decisions that may wait can be 'pending'; consumer release stays blocked")
    de = _people_with(doc, "DE")
    if de:
        _setdefault(doc, notes, "project.builder", de[0], "the first person with the DE role")


def _policies(doc: dict, notes: dict) -> None:
    _setdefault(doc, notes, "policies.compliance", "none",
                "change to gdpr / hipaa / gxp if the data falls under one (v1 then blocks release to consumers)")
    _setdefault(doc, notes, "policies.egress", "stats_only",
                "safest choice that still lets the assistant profile the data: counts and distributions, no values")
    _setdefault(doc, notes, "policies.timezone.reporting", "UTC",
                "change to the time zone your business reports in (e.g. America/Sao_Paulo, Asia/Kolkata)")
    _setdefault(doc, notes, "policies.calendar.type", "gregorian", "the only calendar v1 builds")
    _setdefault(doc, notes, "policies.calendar.week_start", "monday", "ISO weeks start on Monday")
    _setdefault(doc, notes, "policies.money.scale", "2", "two decimal places, as in most currencies")


def _source_basics(doc: dict, notes: dict, s: str) -> None:
    base = f"sources.{s}"
    spec = C.get_path(doc, base) or {}
    loc = str(spec.get("location") or "")
    ext = Path(loc).suffix.lower()
    _setdefault(doc, notes, f"{base}.connector", "http_file" if loc.lower().startswith("http") else "local_file")
    _setdefault(doc, notes, f"{base}.format", A.DATA_EXT.get(ext, "csv"), "from the file extension")
    fmt = str(C.get_path(doc, f"{base}.format")).lower()
    if fmt == "csv":
        _setdefault(doc, notes, f"{base}.csv.delimiter", "\t" if ext == ".tsv" else ",")
        for k, v in (("header", "yes"), ("quote", '"'), ("escape", '"'), ("encoding", "utf-8")):
            _setdefault(doc, notes, f"{base}.csv.{k}", v)
        _setdefault(doc, notes, f"{base}.csv.null_tokens", "NA", "only empty fields count as missing")
    if fmt == "xlsx":
        _setdefault(doc, notes, f"{base}.xlsx.header_row", "1")


def _source(doc: dict, notes: dict, s: str, an: dict) -> None:
    base = f"sources.{s}"
    spec = C.get_path(doc, base) or {}
    loc = str(spec.get("location") or "")
    batched = "{batch}" in loc
    _setdefault(doc, notes, f"{base}.load_type", "incremental_append" if batched else "full_refresh",
                "the location has a {batch} token, so batches add rows" if batched
                else "one file without a batch token: each delivery replaces the table")
    declared_cols = C.get_path(doc, f"{base}.schema.columns") or {}
    has_key = bool((an.get("key") or {}).get("columns")) or any(
        isinstance(v, dict) and str(v.get("key", "")).lower() in C.TRUE_WORDS for v in declared_cols.values())
    lt = str(C.get_path(doc, f"{base}.load_type"))
    if lt == "incremental_append" and not has_key:
        _setdefault(doc, notes, f"{base}.redelivery_policy", "reject",
                    "no key: rows are appended once and repeats skipped, so a changed re-delivery is rejected and alerted")
    elif lt in ("incremental_append", "snapshot", "cdc"):
        _setdefault(doc, notes, f"{base}.redelivery_policy", "replace",
                    "a corrected re-delivery replaces the old batch and rebuilds downstream")
    cols_an = an.get("columns") or {}
    proposed = {c: A.propose_type(c, i)[0] for c, i in cols_an.items()}
    timestamps = [c for c, t in proposed.items() if t in ("TIMESTAMP", "DATE")]
    money = [c for c, t in proposed.items() if t.startswith("DECIMAL")]
    small = an.get("rows") is not None and an.get("rows", 0) <= 1000 and len(cols_an) <= 3
    role, why = ("fact", "has event timestamps or money amounts") if (timestamps or money) else \
        ("reference", "a small code/lookup table") if small else ("dimension", "describes things, not events")
    _setdefault(doc, notes, f"{base}.role", role, why)
    _setdefault(doc, notes, f"{base}.freshness.basis", "none",
                "no freshness check: batch ids are not dates (change to batch_token or column for live feeds)")
    for k in ("min_rows", "max_rows"):
        _setdefault(doc, notes, f"{base}.volume.{k}", "NA", "only zero-row files are rejected")
    _setdefault(doc, notes, f"{base}.retry_attempts", "3")
    _setdefault(doc, notes, f"{base}.credentials_env", "NA", "local files need no credentials")
    _setdefault(doc, notes, f"{base}.drift_policy", "land_and_log",
                "new columns are landed and logged; type changes and missing required columns still reject")
    _setdefault(doc, notes, f"{base}.profile_split_by", "NA", "chosen automatically from low-cardinality columns")
    # schema
    declared = C.get_path(doc, f"{base}.schema.columns")
    declared = declared if isinstance(declared, dict) else {}
    key = (an.get("key") or {}).get("columns") or []
    names = list(dict.fromkeys(list(cols_an) + list(declared)))  # every analysed column, plus declared extras
    for c in names:
        cp = f"{base}.schema.columns.{c}"
        info = cols_an.get(c) or {}
        t, why = A.propose_type(c, info) if info else ("VARCHAR", "")
        _setdefault(doc, notes, f"{cp}.type", t, why)
        _setdefault(doc, notes, f"{cp}.required", "yes", "every file must carry this column")
        if not any(str((declared.get(x) or {}).get("key", "")).lower() in C.TRUE_WORDS
                   for x in declared if isinstance(declared.get(x), dict)):
            _setdefault(doc, notes, f"{cp}.key", "yes" if c in key else "no",
                        f"{'+'.join(key)} is unique in the sample" if c in key and key else "")
        else:
            _setdefault(doc, notes, f"{cp}.key", "no")
        _setdefault(doc, notes, f"{cp}.allowed_values", "NA", "no allowed-value check")
        cls, cwhy = A.propose_classification(c, str(C.get_path(doc, f"{cp}.type")).upper())
        _setdefault(doc, notes, f"{cp}.classification", cls, cwhy)


def _entity_for_source(doc: dict, s: str) -> str | None:
    for e, spec in (C.get_path(doc, "silver.entities") or {}).items():
        if isinstance(spec, dict) and s in C.as_list(spec.get("sources")):
            return e
    return None


def _silver(doc: dict, notes: dict, analysis: dict) -> None:
    ents = C.get_path(doc, "silver.entities")
    if not isinstance(ents, dict):
        C.set_path(doc, "silver.entities", {})
    for s in (doc.get("sources") or {}):
        if _entity_for_source(doc, s) is None:
            name = s if s not in doc["silver"]["entities"] else f"{s}_entity"
            doc["silver"]["entities"][name] = {"sources": [s]}
            notes.setdefault(f"silver.entities.{name}", f"one cleaned entity per source ({s})")
    tz = str(C.get_path(doc, "policies.timezone.reporting") or "UTC")
    for e, spec in doc["silver"]["entities"].items():
        base = f"silver.entities.{e}"
        srcs = C.as_list(spec.get("sources"))
        mapping = spec.get("mapping") if isinstance(spec.get("mapping"), dict) else {}
        if not isinstance(spec.get("columns"), dict):
            spec["columns"] = {}
        cols = spec["columns"]
        key_cols: list[str] = []
        load_types = set()
        for s in srcs:
            scols = C.get_path(doc, f"sources.{s}.schema.columns") or {}
            an = ((analysis.get("sources") or {}).get(s) or {}).get("columns") or {}
            m = mapping.get(s) if isinstance(mapping.get(s), dict) else {}
            rev = {str(v): k for k, v in m.items()}
            load_types.add(str(C.get_path(doc, f"sources.{s}.load_type") or ""))
            drops = spec.get("drop_columns") if isinstance(spec.get("drop_columns"), dict) else {}
            for c, cs in scols.items() if isinstance(scols, dict) else []:
                cn = rev.get(c, canon(c))
                if isinstance(cs, dict) and str(cs.get("key", "")).lower() in C.TRUE_WORDS and cn not in key_cols:
                    key_cols.append(cn)
                if cn not in cols and c not in drops:
                    cols[cn] = {}
                    notes.setdefault(f"{base}.columns.{cn}", f"carried from {s}.{c}")
                if cn in cols:
                    t = str((cs or {}).get("type", "VARCHAR")) if isinstance(cs, dict) else "VARCHAR"
                    _setdefault(doc, notes, f"{base}.columns.{cn}.type", t, "same as the bronze type")
                    if C.get_path(doc, f"{base}.columns.{cn}.type") in ("DATE", "TIMESTAMP"):
                        fm = [f for f, _ in (an.get(c) or {}).get("formats", [])] or (
                            ["%Y-%m-%d %H:%M:%S"] if C.get_path(doc, f"{base}.columns.{cn}.type") == "TIMESTAMP"
                            else ["%Y-%m-%d"])
                        _setdefault(doc, notes, f"{base}.columns.{cn}.formats", fm,
                                    "formats found in the sample" if (an.get(c) or {}).get("formats") else
                                    "assumed ISO format")
                    if C.get_path(doc, f"{base}.columns.{cn}.type") == "TIMESTAMP":
                        _setdefault(doc, notes, f"{base}.columns.{cn}.source_timezone", tz,
                                    "assumed recorded in the reporting time zone — change if the source system uses another")
        spec["columns"] = cols
        _setdefault(doc, notes, f"{base}.natural_key", key_cols or list(cols),
                    "the source key" if key_cols else "no key column: the whole row is the key, so exact duplicates collapse")
        ts = [c for c, cs in cols.items() if isinstance(cs, dict) and str(cs.get("type")) in ("TIMESTAMP", "DATE")]
        nk = C.as_list(C.get_path(doc, f"{base}.natural_key"))
        ver = [c for c in ts if re.search(r"(?i)(updated|modified|changed|last_|version|answer)", c)]
        pick = (ver or ts)[:1]
        _setdefault(doc, notes, f"{base}.tiebreaker",
                    [f"{pick[0]} DESC"] if pick else [f"{nk[0] if nk else next(iter(cols), 'x')} ASC"],
                    f"the latest {pick[0]} wins when one key arrives twice" if pick else
                    "no timestamp: a deterministic order")
        whole_row = not key_cols and sorted(C.as_list(C.get_path(doc, f"{base}.natural_key"))) == sorted(cols)
        if "cdc" in load_types:
            strat, why = "cdc_apply", "the source delivers change records"
        elif whole_row and load_types & {"incremental_append"}:
            # no key: the same row can arrive again in a later batch — append skips it, while
            # partition_replace would keep one copy per batch
            strat, why = "append", "no key: a row already loaded from an earlier batch is skipped, not duplicated"
        elif "snapshot" in load_types:
            strat, why = "snapshot_diff", "the source delivers full snapshots"
        else:
            strat, why = "partition_replace", "each batch replaces its own rows, so a corrected re-delivery swaps cleanly"
        _setdefault(doc, notes, f"{base}.merge.strategy", strat, why)
        if str(C.get_path(doc, f"{base}.merge.strategy")) == "partition_replace":
            _setdefault(doc, notes, f"{base}.merge.partition_column", "NA", "the source batch is the partition")
        _setdefault(doc, notes, f"{base}.rejected_survivor_policy", "keep_last_good",
                    "a bad correction never wipes out the last good version")
        np_ = spec.get("null_policy") if isinstance(spec.get("null_policy"), dict) else {}
        for c in cols:
            if c not in np_:
                np_[c] = "drop" if c in nk and len(nk) < len(cols) else "keep"
                notes.setdefault(f"{base}.null_policy.{c}", "a row without its key cannot be identified"
                                 if np_[c] == "drop" else "an empty value stays empty")
        spec["null_policy"] = np_
        _setdefault(doc, notes, f"{base}.valid_anomalies", "none")
        _setdefault(doc, notes, f"{base}.hard_rejects", "none")
        _setdefault(doc, notes, f"{base}.dead_letter_tolerance_pct", "5",
                    "a batch losing more than 5 % of its rows means the source changed")
        _setdefault(doc, notes, f"{base}.tolerance_source", "owner")
        for k in ("flags", "lookups", "drop_columns", "target_table"):
            _setdefault(doc, notes, f"{base}.{k}", "NA")
        # masking for protected columns
        for s in srcs:
            scols = C.get_path(doc, f"sources.{s}.schema.columns") or {}
            m = mapping.get(s) if isinstance(mapping.get(s), dict) else {}
            rev = {str(v): k for k, v in m.items()}
            for c, cs in scols.items() if isinstance(scols, dict) else []:
                cl = str((cs or {}).get("classification", "")).lower() if isinstance(cs, dict) else ""
                cn = rev.get(c, canon(c))
                if cl in ("pii", "sensitive", "regulated") and cn in cols:
                    free_text = cl == "sensitive" and str((cs or {}).get("type", "")).upper() == "VARCHAR" \
                        and cn not in nk
                    _setdefault(doc, notes, f"{base}.masking.{cn}", "drop" if free_text else "hash",
                                "free text is dropped by default" if free_text else
                                "hashed: still joinable and countable, no longer readable")
        # structural-null candidates: a column never filled in the sample
        for s in srcs:
            an = ((analysis.get("sources") or {}).get(s) or {})
            rows = an.get("rows") or 0
            m = mapping.get(s) if isinstance(mapping.get(s), dict) else {}
            rev = {str(v): k for k, v in m.items()}
            for c, info in (an.get("columns") or {}).items():
                cn = rev.get(c, canon(c))
                if rows and info.get("empty") == rows and cn in cols:
                    _setdefault(doc, notes, f"{base}.structural_nulls.{cn}|source={s}", "defect",
                                f"never filled in the sample ({rows:,} rows); 'defect' lets the null policy apply")
            for cn, expr in m.items():
                if str(expr).strip().upper() == "NULL":
                    _setdefault(doc, notes, f"{base}.structural_nulls.{cn}|source={s}", "structural",
                                f"source {s} never supplies {cn}")


def _metrics(doc: dict, notes: dict) -> None:
    metrics = doc.get("metrics") if isinstance(doc.get("metrics"), dict) else {}
    doc["metrics"] = metrics
    po = _people_with(doc, "PO")
    for m, spec in metrics.items():
        if not isinstance(spec, dict):
            continue
        base = f"metrics.{m}"
        mt = str(spec.get("metric_type", "")).lower()
        unit = str(spec.get("unit", "count"))
        _setdefault(doc, notes, f"{base}.unit", "count")
        _setdefault(doc, notes, f"{base}.precision",
                    "0" if unit == "count" else "1" if unit == "percent" else "2")
        _setdefault(doc, notes, f"{base}.additivity",
                    "additive" if mt in ("sum", "count") else "non_additive",
                    "sums and counts add up across rows; ratios, averages and distinct counts do not")
        _setdefault(doc, notes, f"{base}.numerator.filter", "none")
        _setdefault(doc, notes, f"{base}.filters", "none")
        if mt in ("ratio", "average"):
            _setdefault(doc, notes, f"{base}.zero_denominator", "null", "blank, so it does not drag averages to 0")
        if mt == "ratio":
            _setdefault(doc, notes, f"{base}.denominator.exclude.values", "none")
        _setdefault(doc, notes, f"{base}.population", "NA")
        _setdefault(doc, notes, f"{base}.valid_range.min", "0" if mt != "sum" else "none")
        _setdefault(doc, notes, f"{base}.valid_range.max", "100" if unit == "percent" else "none")
        _setdefault(doc, notes, f"{base}.cadence", "daily")
        if po:
            _setdefault(doc, notes, f"{base}.dispute_owner", po[0], "the first person with the PO role")
        _setdefault(doc, notes, f"{base}.version", "1.0.0")
        _setdefault(doc, notes, f"{base}.effective_from", date.today().isoformat())
        ctl = spec.get("denominator", {}).get("measure") if mt in ("ratio", "average") and isinstance(
            spec.get("denominator"), dict) else C.get_path(doc, f"{base}.numerator.measure")
        if ctl:
            _setdefault(doc, notes, f"{base}.reconciliation.control", str(ctl),
                        "ties the metric back to silver" + (" (for a ratio: its denominator)" if mt == "ratio" else ""))
        flt = C.get_path(doc, f"{base}.filters")
        excl = "none" if C.is_token(flt, "none") or not flt else f"NOT ({flt})"
        _setdefault(doc, notes, f"{base}.reconciliation.excluded_by", excl)
        _setdefault(doc, notes, f"{base}.reconciliation.max_excluded_pct", "0" if excl == "none" else "50")
        tg = str(C.get_path(doc, f"{base}.time_grain") or "day")
        _setdefault(doc, notes, f"{base}.target_table", f"gold_{m}_{tg}",
                    "one table per metric (metrics sharing a table must share entity and grain)")


def _serve(doc: dict, notes: dict) -> None:
    name = C.get_path(doc, "project.name") or "warehouse"
    _setdefault(doc, notes, "serve.title", f"{name} dashboard")
    _setdefault(doc, notes, "serve.audience", "project team")
    _setdefault(doc, notes, "serve.runtime", "streamlit", "the only runtime v1 builds")
    basis = {str(C.get_path(doc, f"sources.{s}.freshness.basis") or "none") for s in (doc.get("sources") or {})}
    _setdefault(doc, notes, "serve.reference_clock", "replay" if basis <= {"none"} else "load",
                "historical data: no stale banner" if basis <= {"none"} else "fresh = time since the last load")
    if str(C.get_path(doc, "serve.reference_clock")) in ("event", "load"):
        _setdefault(doc, notes, "serve.stale_after_hours", "24")
    metrics = doc.get("metrics") or {}
    if not isinstance(C.get_path(doc, "serve.kpis"), dict) and metrics:
        C.set_path(doc, "serve.kpis", {m: {"metric": m, "label": "NA"} for m in metrics})
        notes.setdefault("serve.kpis", "one tile per metric")
    if not isinstance(C.get_path(doc, "serve.charts"), dict) and metrics:
        charts = {}
        for m, spec in metrics.items():
            if isinstance(spec, dict) and spec.get("date_basis"):
                charts[f"{m}_trend"] = {"type": "line", "metric": m, "x": spec["date_basis"], "color": "NA",
                                        "title": "NA"}
        if charts:
            C.set_path(doc, "serve.charts", charts)
            notes.setdefault("serve.charts", "one trend line per metric")
    _setdefault(doc, notes, "serve.filters", "NA", "date range filter only")
    _setdefault(doc, notes, "serve.port", "NA")
    _setdefault(doc, notes, "serve.auto_refresh_seconds", "NA")
    _setdefault(doc, notes, "serve.row_security", "none", "every viewer sees every row (the only option in v1)")


def catalogue_field(path: str) -> K.Field | None:
    f, _ = K.find_field(path)
    return f
