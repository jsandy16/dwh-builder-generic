"""Field-type checks, per-field validators and cross-field (skill-level) validators.

Field validators are referenced from catalogues as "name:arg" (arg may use {1} captures).
Skill validators return (path, owner, problem, fix) tuples. Data-dependent validators
(gate B) only run when the data they need exists.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from . import config as C
from . import sqlfrag
from .catalogue import Field, _subst

MEASURE_RE = re.compile(r"^(count|sum:[A-Za-z_]\w*|count_distinct:[A-Za-z_]\w*)$")
NUMERIC_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "INT", "BIGINT", "HUGEINT", "DOUBLE", "FLOAT",
                 "REAL", "DECIMAL", "NUMERIC", "UBIGINT", "UINTEGER")


# ---------------------------------------------------------------- types
def check_type(f: Field, v: Any) -> str | None:
    t = f.type
    try:
        if t in ("string", "text", "person", "column", "measure", "sql_predicate", "sql_expr",
                 "path_pattern", "timezone", "duckdb_type"):
            if not isinstance(v, str):
                return f"expected a single value, got {type(v).__name__}"
        if t == "enum":
            if not isinstance(v, str) or v.strip().lower() not in {c.lower() for c in f.choices}:
                return f"must be one of: {', '.join(f.choices)}"
        elif t == "int":
            C.as_int(v)
        elif t == "number":
            C.as_number(v)
        elif t == "percent":
            n = C.as_number(v)
            if not (0 <= n <= 100):
                return "must be between 0 and 100"
        elif t == "bool":
            C.as_bool(v)
        elif t == "date":
            datetime.strptime(str(v).strip(), "%Y-%m-%d")
        elif t in ("list", "columns", "strftime_list"):
            if not isinstance(v, list):
                return "expected a list"
            if f.choices:
                bad = [x for x in v if str(x).lower() not in {c.lower() for c in f.choices}]
                if bad:
                    return f"not allowed: {', '.join(map(str, bad))} (choices: {', '.join(f.choices)})"
            if t == "strftime_list":
                for fmt in v:
                    if "%" not in str(fmt):
                        return f"'{fmt}' is not a date format (use strftime codes like %Y-%m-%d)"
                    sample = datetime(2024, 3, 7, 13, 5, 9).strftime(fmt)
                    if datetime.strptime(sample, fmt).year != 2024 and "%Y" in fmt:
                        return f"format '{fmt}' does not round-trip"
        elif t == "map":
            if not isinstance(v, dict):
                return "expected a mapping of name → details"
        elif t == "measure":
            if not MEASURE_RE.match(v.strip()):
                return "measure must be count | sum:<col> | count_distinct:<col> (averages: metric_type average)"
        elif t == "timezone":
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(v.strip())
            except Exception:
                return f"unknown time zone '{v}' (use an IANA name like Asia/Kolkata or UTC)"
        elif t == "duckdb_type":
            return sqlfrag.valid_type(v.strip())
        elif t == "golden_values":
            if not isinstance(v, list) or len(v) < 3:
                return "needs at least 3 golden values computed by hand by the owner"
            for g in v:
                if not isinstance(g, dict) or "key" not in g or "value" not in g:
                    return "each golden value needs `key` (grain values) and `value`"
                if not C.is_token(g["value"], "null"):
                    C.as_number(g["value"])
    except ValueError as e:
        return str(e)
    return None


# ---------------------------------------------------------------- scopes
TEXT_FORMATS = ("csv", "json", "jsonl", "xlsx")


def source_columns(doc: dict, source: str) -> dict[str, str]:
    """Physical bronze columns: text formats land as VARCHAR, typed formats keep their type."""
    cols = C.get_path(doc, f"sources.{source}.schema.columns") or {}
    fmt = str(C.get_path(doc, f"sources.{source}.format") or "").lower()
    out = {}
    for name, spec in cols.items() if isinstance(cols, dict) else []:
        declared = (spec or {}).get("type", "VARCHAR") if isinstance(spec, dict) else "VARCHAR"
        out[name] = "VARCHAR" if fmt in TEXT_FORMATS else declared
    return out


def silver_columns(doc: dict, entity: str, include_derived: bool = True) -> dict[str, str]:
    """include_derived=False: the typed canonical columns rules are written against.
    include_derived=True: the columns of the published silver table (masking applied,
    plus imputation flags, lookup columns <lookup>_<column> and business flags)."""
    ent = C.get_path(doc, f"silver.entities.{entity}") or {}
    if not isinstance(ent, dict):
        return {}
    cols = {}
    for name, spec in (ent.get("columns") or {}).items() if isinstance(ent.get("columns"), dict) else []:
        cols[name] = (spec or {}).get("type", "VARCHAR") if isinstance(spec, dict) else "VARCHAR"
    if include_derived:
        masking = ent.get("masking") if isinstance(ent.get("masking"), dict) else {}
        for c, m in masking.items():
            m = str(m).strip().lower()
            if c in cols and m == "drop":
                cols.pop(c)
            elif c in cols and m == "hash":
                cols[c] = "VARCHAR"
        np = ent.get("null_policy")
        if isinstance(np, dict):
            for col, pol in np.items():
                if str(pol).lower().startswith("impute"):
                    cols[f"is_{col}_imputed"] = "BOOLEAN"
        lookups = ent.get("lookups")
        if isinstance(lookups, dict):
            for lk_name, lk in lookups.items():
                ref = (lk or {}).get("reference", "") if isinstance(lk, dict) else ""
                ref_ent = _reference_entity(doc, ref)
                ref_cols = silver_columns(doc, ref_ent, include_derived=False) if ref_ent else {}
                for c in C.as_list((lk or {}).get("columns") if isinstance(lk, dict) else []):
                    cols[f"{lk_name}_{c}"] = ref_cols.get(c, "VARCHAR")
        flags = ent.get("flags")
        if isinstance(flags, dict):
            for name in flags:
                cols[name] = "BOOLEAN"
    return cols


def _reference_entity(doc: dict, name: str) -> str:
    ents = C.get_path(doc, "silver.entities") or {}
    if name in ents:
        return name
    for e, spec in ents.items():
        if name in C.as_list((spec or {}).get("sources")):
            return e
    return ""


def scope_columns(doc: dict, scope: str, caps: list[str]) -> dict[str, str]:
    kind, _, arg = scope.partition(":")
    arg = _subst(arg, caps) if arg else ""
    if kind == "source":
        return source_columns(doc, arg)
    if kind == "silver":
        return silver_columns(doc, arg, include_derived=False)
    if kind == "silver_all":
        return silver_columns(doc, arg, include_derived=True)
    if kind == "metric":
        ent = C.get_path(doc, f"metrics.{arg}.entity") or ""
        return silver_columns(doc, ent, include_derived=True)
    raise ValueError(f"unknown scope {scope}")


# ---------------------------------------------------------------- field validators
def run_field_validator(spec: str, project, doc: dict, f: Field, path: str, caps: list[str], v: Any) -> str | None:
    name, _, arg = spec.partition(":")
    try:
        if name == "person_with_role":
            from .intake import roles_of
            if arg.upper() not in roles_of(project, str(v)):
                return f"'{v}' is not in the people list with role {arg.upper()}"
        elif name in ("sql_predicate", "sql_expr"):
            if C.is_token(v, C.NONE_TOKEN):
                return None
            cols = scope_columns(doc, arg, caps)
            return sqlfrag.validate(str(v), cols, "predicate" if name == "sql_predicate" else "expr")
        elif name == "columns_of":
            cols = {c.lower() for c in scope_columns(doc, arg, caps)}
            items = C.as_list(v)
            bad = [c for c in items if str(c).split()[0].lower() not in cols]
            if bad:
                return f"unknown column(s): {', '.join(map(str, bad))}"
        elif name == "column_of":
            cols = {c.lower() for c in scope_columns(doc, arg, caps)}
            if str(v).lower() not in cols:
                return f"unknown column '{v}' (available: {', '.join(sorted(cols))})"
        elif name == "measure_of":
            cols = {c.lower() for c in scope_columns(doc, arg, caps)}
            col = str(v).partition(":")[2]
            if col and col.lower() not in cols:
                return f"measure column '{col}' not in entity"
        elif name == "identifier":
            if not sqlfrag.valid_identifier(str(v)):
                return "use letters, digits and underscore only"
        elif name == "batch_token":
            lt = C.get_path(doc, _subst(arg, caps)) or ""
            if str(lt).lower() in ("incremental_append", "snapshot", "cdc") and "{batch}" not in str(v):
                return "incremental/snapshot/CDC sources need a {batch} token in the location"
        elif name == "silver_entity":
            if str(v) not in (C.get_path(doc, "silver.entities") or {}):
                return f"no silver entity '{v}'"
        elif name == "source_list":
            known = set((C.get_path(doc, "sources") or {}).keys())
            bad = [s for s in C.as_list(v) if s not in known]
            if bad:
                return f"unknown source(s): {', '.join(bad)}"
        elif name == "metric_name":
            if str(v) not in (C.get_path(doc, "metrics") or {}):
                return f"no metric card '{v}'"
        elif name == "tiebreaker":
            cols = {c.lower() for c in scope_columns(doc, arg, caps)}
            for item in C.as_list(v):
                parts = str(item).split()
                if not parts or parts[0].lower() not in cols or (len(parts) > 1 and parts[1].upper() not in ("ASC", "DESC")) or len(parts) > 2:
                    return f"tiebreaker item '{item}' must be '<column> [ASC|DESC]' using entity columns"
    except ValueError as e:
        return str(e)
    return None


# ---------------------------------------------------------------- skill validators
def run_skill_validator(name: str, project, doc: dict, gate: str) -> list[tuple]:
    fn = SKILL_VALIDATORS.get(name)
    if fn is None:
        raise ValueError(f"unknown skill validator {name}")
    return fn(project, doc, gate)


def _v_people_roles(project, doc, gate):
    """The assistant is never a stakeholder — under any id or display name."""
    from . import AGENT_IDS
    bad = AGENT_IDS | {"claude", "chatgpt", "gpt", "copilot", "gemini", "llm", "assistant", "agent"}
    out = []
    ppl = doc.get("people") or {}
    for pid, rec in ppl.items() if isinstance(ppl, dict) else []:
        name = str((rec or {}).get("name", "")) if isinstance(rec, dict) else ""
        tokens = {t for t in re.split(r"[^a-z0-9]+", f"{pid} {name}".lower()) if t}
        if tokens & bad:
            out.append((f"people.{pid}", "DE", "the assistant cannot be listed as a person or hold a role",
                        "list only the people who actually answer and approve"))
    return out


def _na(v) -> bool:
    return C.is_blank(v) or C.is_token(v, C.NA_TOKEN) or C.is_token(v, C.NONE_TOKEN)


def _v_silver_entities(project, doc, gate):
    out = []
    ents = C.get_path(doc, "silver.entities") or {}
    if not C.get_path(doc, "sources"):
        out.append(("sources", "DE", "silver needs the bronze sources described first", "answer the dwh-bronze intake"))
    for e, spec in ents.items() if isinstance(ents, dict) else []:
        spec = spec if isinstance(spec, dict) else {}
        base = f"silver.entities.{e}"
        cols = silver_columns(doc, e, include_derived=False)
        srcs = C.as_list(spec.get("sources"))
        if not sqlfrag.valid_identifier(e):
            out.append((base, "DE", "entity names use letters, digits and underscore", ""))
        for c in cols:
            if not sqlfrag.valid_identifier(c):
                out.append((f"{base}.columns.{c}", "DE", "canonical column names use letters, digits and underscore", ""))
        merge = spec.get("merge") if isinstance(spec.get("merge"), dict) else {}
        strategy = str(merge.get("strategy", "")).lower()
        tb = [str(t).split() for t in C.as_list(spec.get("tiebreaker"))]
        # merge strategy vs load behaviour of the sources (one rule for every load type loses data)
        for s in srcs:
            lt = str(C.get_path(doc, f"sources.{s}.load_type") or "").lower()
            rp = str(C.get_path(doc, f"sources.{s}.redelivery_policy") or "").lower()
            if strategy == "append" and rp == "replace":
                out.append((f"{base}.merge.strategy", "DE",
                            f"source '{s}' replaces re-delivered batches, but append never applies a corrected row",
                            "use partition_replace or upsert_by_version"))
            if lt == "cdc" and strategy not in ("cdc_apply", ""):
                out.append((f"{base}.merge.strategy", "DE", f"source '{s}' is CDC; use cdc_apply", ""))
            if lt == "snapshot" and strategy not in ("snapshot_diff", "partition_replace", ""):
                out.append((f"{base}.merge.strategy", "DE",
                            f"source '{s}' delivers snapshots; use snapshot_diff or partition_replace", ""))
            if lt == "full_refresh" and strategy not in ("partition_replace", "snapshot_diff", ""):
                out.append((f"{base}.merge.strategy", "DE",
                            f"source '{s}' is a full refresh; use partition_replace or snapshot_diff", ""))
        for strat, col_key in (("upsert_by_version", "version_column"), ("cdc_apply", "sequence_column")):
            vc = merge.get(col_key)
            if strategy == strat and vc and (not tb or tb[0][0] != vc or (len(tb[0]) < 2 or tb[0][1].upper() != "DESC")):
                out.append((f"{base}.tiebreaker", "DE",
                            f"with {strat} the tiebreaker must start with '{vc} DESC' "
                            "(the newest version of a key must win inside a batch too)", f"[\"{vc} DESC\", …]"))
        if strategy == "partition_replace":
            pc = merge.get("partition_column")
            if pc and not _na(pc) and pc != "_batch_id" and pc not in cols:
                out.append((f"{base}.merge.partition_column", "DE", f"unknown column '{pc}'", ""))
        lookups = spec.get("lookups") if isinstance(spec.get("lookups"), dict) else {}
        for name, lk in lookups.items():
            if not sqlfrag.valid_identifier(name):
                out.append((f"{base}.lookups.{name}", "DE", "lookup names use letters, digits and underscore", ""))
            lk = lk if isinstance(lk, dict) else {}
            ref = _reference_entity(doc, lk.get("reference", ""))
            ref_cols = silver_columns(doc, ref, include_derived=False) if ref else {}
            for lc, rc in (lk.get("on") or {}).items() if isinstance(lk.get("on"), dict) else []:
                if lc not in cols:
                    out.append((f"{base}.lookups.{name}.on", "DE", f"'{lc}' is not a column of {e}", ""))
                if ref and rc not in ref_cols:
                    out.append((f"{base}.lookups.{name}.on", "DE", f"'{rc}' is not a column of {ref}", ""))
            for rc in C.as_list(lk.get("columns")):
                if ref and rc not in ref_cols:
                    out.append((f"{base}.lookups.{name}.columns", "DE", f"'{rc}' is not a column of {ref}", ""))
        masking = spec.get("masking") if isinstance(spec.get("masking"), dict) else {}
        for k in C.as_list(spec.get("natural_key")):
            if str(masking.get(k, "")).lower() == "drop":
                out.append((f"{base}.masking.{k}", "GOV", "a natural-key column cannot be dropped; hash it instead", ""))
        for k, m in masking.items():
            if str(m).lower() in ("hash", "drop") and k in (merge.get("version_column"), merge.get("sequence_column")):
                out.append((f"{base}.masking.{k}", "GOV", "the version/sequence column cannot be masked", ""))
        # V19: every bronze column is mapped into silver or dropped with a reason
        drops = spec.get("drop_columns") if isinstance(spec.get("drop_columns"), dict) else {}
        mapping_all = spec.get("mapping") if isinstance(spec.get("mapping"), dict) else {}
        for s in srcs:
            scols = source_columns(doc, s)
            if not scols:
                continue
            m = mapping_all.get(s) if isinstance(mapping_all.get(s), dict) else {}
            used = set()
            for c in cols:
                expr = m.get(c)
                if expr is None:
                    used.add(c.lower())
                elif str(expr).strip().upper() != "NULL":
                    if str(expr).strip() in scols:
                        used.add(str(expr).strip().lower())
                    else:
                        used |= sqlfrag.columns_in(str(expr))
            for sc in scols:
                if sc.lower() not in used and sc not in drops:
                    out.append((f"{base}.drop_columns", "DE",
                                f"bronze column '{sc}' of source '{s}' is neither mapped nor dropped",
                                f"map it to a canonical column or add drop_columns.{sc}: <reason>"))
        # every canonical column needs an explicit null policy (no silent defaults)
        np = spec.get("null_policy") if isinstance(spec.get("null_policy"), dict) else {}
        for c in cols:
            if c not in np:
                out.append((f"{base}.null_policy.{c}", "SME", "missing null policy",
                            "drop (dead-letter) | impute:<value> | keep"))
            else:
                pol = str(np[c]).strip().lower()
                if not (pol in ("drop", "keep") or pol.startswith("impute:")):
                    out.append((f"{base}.null_policy.{c}", "SME", f"invalid null policy '{np[c]}'",
                                "drop | impute:<value> | keep"))
        for c in np:
            if c not in cols:
                out.append((f"{base}.null_policy.{c}", "SME", "null policy for unknown column", ""))
        # natural key must be identity columns of the entity
        for k in C.as_list(spec.get("natural_key")):
            if k not in cols:
                out.append((f"{base}.natural_key", "DE", f"key column '{k}' is not a canonical column", ""))
            elif str(np.get(k, "")).lower().startswith("impute"):
                out.append((f"{base}.null_policy.{k}", "SME", "key columns cannot be imputed", "use drop"))
        # mapping: required when several sources feed the entity or columns are renamed
        mapping = spec.get("mapping") if isinstance(spec.get("mapping"), dict) else {}
        for s in srcs:
            scols = set(source_columns(doc, s))
            m = mapping.get(s) if isinstance(mapping.get(s), dict) else {}
            for c in cols:
                expr = m.get(c, c if c in scols else None)
                if expr is None:
                    out.append((f"{base}.mapping.{s}.{c}", "DE",
                                f"source '{s}' has no column '{c}'", "map an expression or NULL"))
                elif str(expr).strip().upper() != "NULL":
                    err = sqlfrag.validate(str(expr), source_columns(doc, s), "expr")
                    if err:
                        out.append((f"{base}.mapping.{s}.{c}", "DE", err, ""))
        # structural nulls declared by mapping (no data needed) must be decided by the SME
        sn = spec.get("structural_nulls") if isinstance(spec.get("structural_nulls"), dict) else {}
        for cand in mapping_null_candidates(doc, e):
            if cand not in sn:
                out.append((f"{base}.structural_nulls", "SME",
                            f"'{cand}' is never supplied — decide structural (leave NULL) or defect",
                            f"set structural_nulls.\"{cand}\" to structural|defect (★ SME)"))
            elif str(sn[cand]).lower() == "defect":
                col = cand.split("|")[0]
                pol = str(np.get(col, "")).lower()
                if pol.startswith("impute") or pol == "drop":
                    what = "impute every value (fabricated data)" if pol.startswith("impute") else \
                        "dead-letter every row of that source"
                    out.append((f"{base}.structural_nulls.{cand}", "SME",
                                f"the mapping says this source never supplies '{col}', so treating it as a defect "
                                f"would {what}", "mark it structural, or map a real source column"))
        if gate == "B":
            for cand in profile_null_candidates(doc, e):
                if cand not in sn:
                    out.append((f"{base}.structural_nulls", "SME",
                                f"profile shows '{cand}' ~100% null — structural or defect?",
                                "★ SME decision"))
            amb = live_ambiguity(project, e)
            da = spec.get("date_ambiguity") if isinstance(spec.get("date_ambiguity"), dict) else {}
            for col, n in amb.items():
                if col not in da:
                    out.append((f"{base}.date_ambiguity.{col}", "SME",
                                f"{n} values parse to different dates under two declared formats",
                                "prefer_first | reject (★ SME)"))
        for c, pol in (spec.get("masking") or {}).items() if isinstance(spec.get("masking"), dict) else []:
            if c not in cols:
                out.append((f"{base}.masking.{c}", "GOV", "masking for unknown column", ""))
        for c in sensitive_columns(doc, e):
            if not isinstance(spec.get("masking"), dict) or c not in spec["masking"]:
                out.append((f"{base}.masking.{c}", "GOV",
                            f"'{c}' is classified non-public — choose hash | drop | keep", "★ GOV"))
        strategy = str(C.get_path(spec, "merge.strategy") or "").lower()
        if strategy == "upsert_by_version" and not C.get_path(spec, "merge.version_column"):
            out.append((f"{base}.merge.version_column", "DE", "upsert_by_version needs a version column", ""))
    return out


def _v_silver_rules_vs_data(project, doc, gate):
    """Gate B: rule conflicts and read-back must be resolved on real data (V04, V07)."""
    if gate != "B":
        return []
    from . import silver
    out = []
    for e in (C.get_path(doc, "silver.entities") or {}):
        try:
            res = silver.rule_readback(project, e, write=False)
        except silver.NoBronzeData:
            out.append((f"silver.entities.{e}", "DE", "no bronze data yet", "run the dwh-bronze build first"))
            continue
        except silver.SpecError as err:
            out.append((f"silver.entities.{e}", "DE", str(err), ""))
            continue
        for conflict in res["conflicts"]:
            out.append((f"silver.entities.{e}.valid_anomalies", "SME",
                        f"rule conflict: {conflict}", "a row cannot be both a valid anomaly and a hard reject"))
        confirmed = C.get_path(doc, f"silver.entities.{e}.readback_confirmed")
        if res["rules"] and not res["readback_current"]:
            out.append((f"silver.entities.{e}.readback_confirmed", "SME",
                        "the owner has not confirmed the read-back of the CURRENT rules",
                        f"run `dwh intake readback {e}`, show it to the SME, then record readback_confirmed"))
        elif res["rules"] and confirmed is not None and str(confirmed).strip().lower() in C.FALSE_WORDS:
            out.append((f"silver.entities.{e}.readback_confirmed", "SME",
                        "the owner said the rules do not mean what was intended", "fix the rules with the SME"))
    return out


def live_ambiguity(project, e: str) -> dict[str, int]:
    from . import silver
    try:
        return silver.ambiguity_counts(project, e)
    except (silver.NoBronzeData, silver.SpecError):
        return {}


def _v_gold(project, doc, gate):
    out = []
    cal = str(C.get_path(doc, "policies.calendar.type") or "").strip().lower()
    if cal and not _na(cal) and cal != "gregorian":
        out.append(("policies.calendar.type", "PO",
                    f"v1 builds the Gregorian calendar only; '{cal}' arrives with the governed phase",
                    "answer gregorian (or wait for fiscal-calendar support)"))
    if not C.get_path(doc, "silver.entities"):
        out.append(("silver.entities", "DE", "gold needs the silver entities described first", "answer the dwh-silver intake"))
    metrics = C.get_path(doc, "metrics") or {}
    tables: dict[str, tuple] = {}
    members: dict[str, list] = {}
    omit_tables: dict[str, list] = {}
    for m, spec in metrics.items() if isinstance(metrics, dict) else []:
        spec = spec if isinstance(spec, dict) else {}
        base = f"metrics.{m}"
        ent = spec.get("entity", "")
        cols = silver_columns(doc, ent, include_derived=True)
        grain = C.as_list(spec.get("grain"))
        for g in grain:
            if g not in cols:
                out.append((f"{base}.grain", "PO", f"grain column '{g}' not in entity '{ent}'", ""))
        if spec.get("date_basis") and spec["date_basis"] not in grain:
            out.append((f"{base}.date_basis", "PO", "date basis must be one of the grain columns", ""))
        gv = spec.get("golden_values")
        if isinstance(gv, list):
            for i, g in enumerate(gv):
                keys = set((g.get("key") or {}).keys()) if isinstance(g, dict) else set()
                if keys != set(grain):
                    out.append((f"{base}.golden_values.{i}", "PO",
                                f"golden key must name exactly the grain {grain}", ""))
        if not sqlfrag.valid_identifier(m):
            out.append((base, "PO", "metric names use letters, digits and underscore (they become column names)", ""))
        db = spec.get("date_basis")
        if db and cols.get(db) and str(cols[db]).upper() not in ("DATE", "TIMESTAMP"):
            out.append((f"{base}.date_basis", "PO", f"'{db}' is {cols[db]}, not a date or timestamp", ""))
        mt = str(spec.get("metric_type", "")).lower()
        num = str(C.get_path(spec, "numerator.measure") or "").strip()
        den = str(C.get_path(spec, "denominator.measure") or "").strip()
        nk, _, ncol = num.partition(":")
        dk, _, dcol = den.partition(":")
        want = {"sum": ("sum",), "count": ("count",), "distinct_count": ("count_distinct",),
                "ratio": ("count", "sum", "count_distinct"), "average": ("sum",)}.get(mt)
        if num and want and nk not in want:
            out.append((f"{base}.numerator.measure", "PO",
                        f"a {mt} metric needs a numerator of the form {' | '.join(w + (':<col>' if w != 'count' else '') for w in want)}",
                        "use metric_type average for averages (sum:<col> ÷ count)"))
        if mt == "average" and den and dk not in ("count", "count_distinct"):
            out.append((f"{base}.denominator.measure", "PO", "an average divides by count or count_distinct:<col>", ""))
        for k, col, where in ((nk, ncol, "numerator"), (dk, dcol, "denominator")):
            if k == "sum" and col and col in cols and not str(cols[col]).upper().startswith(NUMERIC_TYPES):
                out.append((f"{base}.{where}.measure", "PO", f"cannot sum '{col}' ({cols[col]})", ""))
        if mt == "ratio":
            inc = C.get_path(spec, "denominator.include.column")
            if inc and inc not in cols:
                out.append((f"{base}.denominator.include.column", "PO", f"unknown column '{inc}'", ""))
        if str(spec.get("zero_denominator", "")).lower() == "omit":
            omit_tables.setdefault(spec.get("target_table", ""), []).append(m)
        # V26: a metric reading imputed or structurally-null inputs must state its population
        inputs = {c for c in (ncol, dcol, C.get_path(spec, "denominator.include.column")) if c}
        for frag_path in ("numerator.filter", "filters"):
            frag = C.get_path(spec, frag_path)
            if frag and not _na(frag):
                inputs |= sqlfrag.columns_in(str(frag))
        risky = sorted(c for c in inputs if c in imputed_or_structural(doc, ent))
        if risky and _na(spec.get("population")):
            out.append((f"{base}.population", "PO",
                        f"input column(s) {', '.join(risky)} are imputed or structurally NULL for some rows",
                        "state which rows count (e.g. 'excludes services that never report passengers')"))
        elif risky:
            from .intake import load_provenance, roles_of
            rec = load_provenance(project).get(f"{base}.population") or {}
            if "PO" not in roles_of(project, str(rec.get("by", ""))):
                out.append((f"{base}.population", "PO", "the population statement must come from the product owner",
                            "record it with --by <PO person>"))
        unit = str(spec.get("unit", "")).lower()
        if unit.startswith("currency") and ncol and not str(cols.get(ncol, "")).upper().startswith("DECIMAL"):
            out.append((f"silver.entities.{ent}.columns.{ncol}.type", "DE",
                        "money must be DECIMAL, not floating point (money policy)", "e.g. DECIMAL(18,2)"))
        scale = C.get_path(doc, "policies.money.scale")
        m_dec = re.match(r"DECIMAL\(\s*\d+\s*,\s*(\d+)\s*\)", str(cols.get(ncol, "")).upper()) if ncol else None
        if unit.startswith("currency") and m_dec and scale and not _na(scale) and m_dec.group(1) != str(scale).strip():
            out.append((f"silver.entities.{ent}.columns.{ncol}.type", "DE",
                        f"money policy says scale {scale}, but {ncol} is {cols[ncol]}", "align the type or the policy"))
        t = spec.get("target_table", "")
        sig = (ent, tuple(grain), str(spec.get("time_grain", "")), str(spec.get("date_basis", "")))
        if t in tables and tables[t] != sig:
            out.append((f"{base}.target_table", "DE",
                        f"metrics sharing table '{t}' must share entity, grain, time grain and date basis", ""))
        tables.setdefault(t, sig)
        members.setdefault(t, []).append(m)
    for t, ms in omit_tables.items():
        if len(members.get(t, [])) > 1:
            out.append((f"metrics.{ms[0]}.zero_denominator", "PO",
                        f"'omit' removes whole rows, so it needs its own table (table '{t}' is shared)", ""))
    return out


def imputed_or_structural(doc: dict, entity: str) -> set[str]:
    spec = C.get_path(doc, f"silver.entities.{entity}") or {}
    if not isinstance(spec, dict):
        return set()
    out = {c for c, p in (spec.get("null_policy") or {}).items() if str(p).lower().startswith("impute")} \
        if isinstance(spec.get("null_policy"), dict) else set()
    sn = spec.get("structural_nulls") if isinstance(spec.get("structural_nulls"), dict) else {}
    out |= {k.split("|")[0] for k, v in sn.items() if str(v).lower() == "structural"}
    return out


def _v_serve(project, doc, gate):
    out = []
    metrics = C.get_path(doc, "metrics") or {}
    serve = C.get_path(doc, "serve") or {}
    for section in ("kpis", "charts"):
        items = serve.get(section) if isinstance(serve.get(section), dict) else {}
        for name, spec in items.items():
            m = (spec or {}).get("metric", "")
            if m not in metrics:
                out.append((f"serve.{section}.{name}.metric", "PO", f"no metric card '{m}'", ""))
                continue
            grain = C.as_list(metrics[m].get("grain"))
            for axis in ("x", "color"):
                val = (spec or {}).get(axis)
                if val and not C.is_token(val, C.NA_TOKEN) and val not in grain:
                    out.append((f"serve.{section}.{name}.{axis}", "PO",
                                f"'{val}' is not in the grain of {m} {grain}", ""))
            mt = str(metrics[m].get("metric_type", "")).lower()
            add = str(metrics[m].get("additivity", "")).lower()
            if section == "charts" and add == "non_additive" and mt not in ("ratio", "average"):
                shown = {(spec or {}).get("x"), (spec or {}).get("color")}
                if not set(grain) <= shown:
                    out.append((f"serve.charts.{name}", "PO",
                                f"{m} is non-additive, so a chart must show its full grain {grain} "
                                "(summing it over the other columns would be wrong)", ""))
    rls = serve.get("row_security")
    if rls is not None and not C.is_blank(rls) and not C.is_token(rls, C.NONE_TOKEN) and not C.is_token(rls, C.NA_TOKEN):
        out.append(("serve.row_security", "GOV", "row-level security is not enforced by dwh_core v1",
                    "answer 'none' (every viewer sees every row), or keep this dashboard unpublished until the "
                    "governed phase"))
    grains = set()
    for spec in metrics.values() if isinstance(metrics, dict) else []:
        grains |= set(C.as_list((spec or {}).get("grain")))
    for f in C.as_list(serve.get("filters")):
        if not C.is_token(f, C.NA_TOKEN) and f not in grains:
            out.append(("serve.filters", "PO", f"filter '{f}' is not a grain column of any metric", ""))
    return out


def _v_synthetic(project, doc, gate):
    out = []
    sources = C.get_path(doc, "sources") or {}
    for name, syn in (C.get_path(doc, "synthetic.sources") or {}).items():
        base = f"synthetic.sources.{name}"
        if name not in sources:
            out.append((base, "DE", f"no bronze source '{name}'", "describe it in the dwh-bronze intake first"))
            continue
        src = sources[name] if isinstance(sources[name], dict) else {}
        if str(src.get("connector", "")).lower() != "local_file":
            out.append((base, "DE", "synthetic files can only be written for local_file sources", ""))
        if str(src.get("format", "")).lower() not in ("csv", "parquet"):
            out.append((base, "DE", "synthetic generation supports csv and parquet sources", ""))
        d = (syn or {}).get("defects") if isinstance(syn, dict) else None
        if isinstance(d, dict):
            for k, v in d.items():
                if k not in ("null", "cast", "domain", "duplicate"):
                    out.append((f"{base}.defects.{k}", "DE", "defect classes: null, cast, domain, duplicate", ""))
                else:
                    try:
                        if not 0 <= C.as_number(v) <= 50:
                            out.append((f"{base}.defects.{k}", "DE", "use a percent between 0 and 50", ""))
                    except ValueError as e:
                        out.append((f"{base}.defects.{k}", "DE", str(e), ""))
        fr = src.get("freshness") or {}
        if str(fr.get("basis", "")).lower() == "batch_token" and isinstance(syn, dict):
            for b in C.as_list(syn.get("batches")):
                try:
                    datetime.strptime(str(b), fr.get("token_format", ""))
                except ValueError:
                    out.append((f"{base}.batches", "DE", f"batch '{b}' does not match {fr.get('token_format')}", ""))
    return out


def _v_sources(project, doc, gate):
    out = []
    for name, spec in (C.get_path(doc, "sources") or {}).items():
        if not sqlfrag.valid_identifier(name):
            out.append((f"sources.{name}", "DE", "source names use letters, digits and underscore", ""))
        env = (spec or {}).get("credentials_env") if isinstance(spec, dict) else None
        if env and not _na(env):
            from . import egress
            if egress.find_secrets(str(env)) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", str(env)):
                out.append((f"sources.{name}.credentials_env", "DE",
                            "give the NAME of an environment variable (e.g. TLC_TOKEN), never the secret itself", ""))
        loc = str((spec or {}).get("location", "")) if isinstance(spec, dict) else ""
        from . import egress
        if egress.find_secrets(loc):
            out.append((f"sources.{name}.location", "DE",
                        "the location contains a credential or signed token; put it in an environment variable", ""))
    return out


SKILL_VALIDATORS = {
    "people_roles": _v_people_roles,
    "sources": _v_sources,
    "silver_entities": _v_silver_entities,
    "silver_rules_vs_data": _v_silver_rules_vs_data,
    "gold_metrics": _v_gold,
    "serve_refs": _v_serve,
    "synthetic_sources": _v_synthetic,
}


# ---------------------------------------------------------------- shared helpers
def mapping_null_candidates(doc: dict, entity: str) -> list[str]:
    spec = C.get_path(doc, f"silver.entities.{entity}") or {}
    mapping = spec.get("mapping") if isinstance(spec.get("mapping"), dict) else {}
    out = []
    for s, m in mapping.items():
        if isinstance(m, dict):
            for c, expr in m.items():
                if str(expr).strip().upper() == "NULL":
                    out.append(f"{c}|source={s}")
    return sorted(out)


def profile_null_candidates(doc: dict, entity: str) -> list[str]:
    spec = C.get_path(doc, f"silver.entities.{entity}") or {}
    out = []
    cols = set((spec.get("columns") or {}).keys())
    mapping = spec.get("mapping") if isinstance(spec.get("mapping"), dict) else {}
    for s in C.as_list(spec.get("sources")):
        prof = C.get_path(doc, f"profile.sources.{s}.structural_null_candidates") or []
        m = mapping.get(s) if isinstance(mapping.get(s), dict) else {}
        rev = {str(v): k for k, v in m.items()} if m else {}
        for cand in prof:
            col, _, subset = str(cand).partition("|")
            canon = rev.get(col, col)
            if canon in cols:
                out.append(f"{canon}|source={s}" + (f"|{subset}" if subset else ""))
    return sorted(set(out))


def sensitive_columns(doc: dict, entity: str) -> list[str]:
    """Canonical columns fed by any pii/sensitive/regulated bronze column (renames and expressions)."""
    spec = C.get_path(doc, f"silver.entities.{entity}") or {}
    if not isinstance(spec, dict):
        return []
    mapping = spec.get("mapping") if isinstance(spec.get("mapping"), dict) else {}
    out = set()
    for s in C.as_list(spec.get("sources")):
        scols = C.get_path(doc, f"sources.{s}.schema.columns") or {}
        if not isinstance(scols, dict):
            continue
        lower = {k.lower(): k for k in scols}
        m = mapping.get(s) if isinstance(mapping.get(s), dict) else {}
        for c in (spec.get("columns") or {}):
            expr = str(m.get(c, c)).strip()
            if expr.upper() == "NULL":
                continue
            feeds = [expr] if expr in scols else [lower[x] for x in sqlfrag.columns_in(expr) if x in lower]
            for src in feeds:
                cl = str((scols.get(src) or {}).get("classification", "") if isinstance(scols.get(src), dict) else "").lower()
                if cl in ("pii", "sensitive", "regulated"):
                    out.add(c)
    return sorted(out)
