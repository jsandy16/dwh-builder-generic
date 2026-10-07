"""Silver: type, conform, judge, pick one survivor per key, merge by strategy — proven by counting.

Everything that runs is GENERATED from the specs (see `render`), one SQL file per
(entity, source) plus one merge file per entity, each with a tamper-evident header.
The runner (`build`) executes those files batch by batch inside a transaction and only
COMMITs after the row law and the post-conditions hold:

    batch rows = survivors + dead-lettered + in-batch duplicates
    survivors  = inserted + updated + stale + already-present + unchanged + reactivated
    Δ table    = inserted − partition rows removed

Order inside a batch (it matters):
  1 typed     cast every column per the type map; dates by the declared formats (ambiguous
              values follow the owner's rule); timestamps moved to the reporting time zone
  2 judged    one reason per rejected row: cast loss, ambiguity, NULL key, NULL policy,
              allowed values, hard rejects, missing lookup codes
  3 outcome   rank every version of a key with the tiebreaker (+ file/row for determinism);
              the owner's rejected-survivor policy decides keep-last-good vs reject-key
  4 final     impute (flagged), mask, flags, lookups, surrogate key, row hash
  5 merge     append | upsert_by_version | partition_replace | cdc_apply | snapshot_diff
"""
from __future__ import annotations

import json
from pathlib import Path

from . import KEY_ALGO
from . import config as C
from . import lineage, sqlfrag
from . import validators as V
from .project import Project, audit, now_iso
from .runtime import (Results, VerificationError, connect, heartbeat, key_sql, ledger, ledger_write, qpath,
                      table_exists)

TEXT_TYPES = ("VARCHAR", "TEXT", "STRING", "CHAR")
INT_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "INT", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER",
             "UBIGINT")
STRATEGIES = ("append", "upsert_by_version", "partition_replace", "cdc_apply", "snapshot_diff")
DL_TABLE = "silver_dead_letter"
META = ["_sk", "_row_hash", "_src", "_batch_id", "_batch_version", "_source_file", "_row_number",
        "_loaded_at", "_is_deleted"]


class NoBronzeData(RuntimeError):
    pass


class SpecError(RuntimeError):
    pass


def q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


lit = sqlfrag.sql_literal


def _is_na(v) -> bool:
    return C.is_blank(v) or C.is_token(v, C.NA_TOKEN) or C.is_token(v, C.NONE_TOKEN)


def _map(v) -> dict:
    return v if isinstance(v, dict) else {}


# ================================================================ entity plan
def entities(doc: dict) -> dict:
    return _map(C.get_path(doc, "silver.entities"))


def target_of(doc: dict, e: str) -> str:
    t = (entities(doc).get(e) or {}).get("target_table")
    return t if isinstance(t, str) and not _is_na(t) else f"silver_{e}"


def entity_order(doc: dict) -> list[str]:
    """Reference entities (lookups) are built before the entities that use them."""
    ents = entities(doc)
    deps = {e: {V._reference_entity(doc, (lk or {}).get("reference", ""))
                for lk in _map((s or {}).get("lookups")).values()} - {"", e}
            for e, s in ents.items()}
    order, seen, stack = [], set(), set()

    def visit(e):
        if e in seen:
            return
        if e in stack:
            raise SpecError(f"lookup cycle involving entity '{e}'")
        stack.add(e)
        for d in sorted(deps.get(e, ())):
            if d in ents:
                visit(d)
        stack.discard(e)
        seen.add(e)
        order.append(e)

    for e in ents:
        visit(e)
    return order


class Plan:
    """Everything the templates need about one entity, derived from the specs only."""

    def __init__(self, doc: dict, e: str):
        self.doc, self.e = doc, e
        spec = entities(doc).get(e)
        if not isinstance(spec, dict):
            raise SpecError(f"no silver entity '{e}'")
        self.spec = spec
        self.sources = [str(s) for s in C.as_list(spec.get("sources"))]
        self.columns = {c: (cs if isinstance(cs, dict) else {}) for c, cs in _map(spec.get("columns")).items()}
        for c in self.columns:
            if not sqlfrag.valid_identifier(c):
                raise SpecError(f"canonical column '{c}' must use letters, digits and underscore")
        self.types = {c: str(cs.get("type", "VARCHAR")).strip().upper() for c, cs in self.columns.items()}
        self.key = [str(k) for k in C.as_list(spec.get("natural_key"))]
        self.tiebreaker = [str(t) for t in C.as_list(spec.get("tiebreaker"))]
        self.policy = str(spec.get("rejected_survivor_policy", "")).strip().lower()
        self.null_policy = {c: str(p).strip() for c, p in _map(spec.get("null_policy")).items()}
        self.structural = {k: str(v).strip().lower() for k, v in _map(spec.get("structural_nulls")).items()}
        self.anomalies = {} if _is_na(spec.get("valid_anomalies")) else _map(spec.get("valid_anomalies"))
        self.hard = {} if _is_na(spec.get("hard_rejects")) else _map(spec.get("hard_rejects"))
        self.flags = {} if _is_na(spec.get("flags")) else _map(spec.get("flags"))
        self.lookups = {} if _is_na(spec.get("lookups")) else _map(spec.get("lookups"))
        self.masking = {c: str(m).strip().lower() for c, m in _map(spec.get("masking")).items()}
        self.ambiguity = {c: str(r).strip().lower() for c, r in _map(spec.get("date_ambiguity")).items()}
        merge = _map(spec.get("merge"))
        self.strategy = str(merge.get("strategy", "")).strip().lower()
        self.version_col = merge.get("version_column")
        self.sequence_col = merge.get("sequence_column")
        self.op_col = merge.get("op_column")
        self.op_codes = _map(merge.get("op_codes"))
        pc = merge.get("partition_column")
        self.partition_col = "_batch_id" if _is_na(pc) else str(pc)
        self.target = target_of(doc, e)
        self.rep_tz = str(C.get_path(doc, "policies.timezone.reporting") or "UTC").strip()
        self.tolerance = C.as_number(spec.get("dead_letter_tolerance_pct") or "0")
        if self.strategy not in STRATEGIES:
            raise SpecError(f"{e}: unknown merge strategy '{self.strategy}'")
        if self.policy not in ("keep_last_good", "reject_key"):
            raise SpecError(f"{e}: rejected_survivor_policy must be keep_last_good or reject_key")
        # surrogate keys of protected identities are salted (an unsalted md5 of an e-mail is reversible)
        self.salted_key = any(self.masking.get(k) in ("hash", "drop") for k in self.key)

    # ---- columns produced
    def out_columns(self) -> list[tuple[str, str]]:
        out = []
        for c, t in self.types.items():
            m = self.masking.get(c)
            if m == "drop":
                continue
            out.append((c, "VARCHAR" if m == "hash" else t))
        for c in self.imputed_cols():
            out.append((f"is_{c}_imputed", "BOOLEAN"))
        for name, lk in self.lookups.items():
            for rc in C.as_list((lk or {}).get("columns")):
                out.append((f"{name}_{rc}", "ANY"))
        for f in self.flags:
            out.append((f, "BOOLEAN"))
        return out

    def target_columns(self) -> list[str]:
        return [c for c, _ in self.out_columns()] + META

    def imputed_cols(self) -> list[str]:
        return [c for c, p in self.null_policy.items() if p.lower().startswith("impute:") and c in self.types]

    # ---- per-source raw expressions
    def physical(self, s: str) -> dict[str, str]:
        return V.source_columns(self.doc, s)

    def raw_expr(self, s: str, c: str) -> tuple[str | None, str]:
        """(SQL over the bronze row, its type) for canonical column c from source s."""
        phys = self.physical(s)
        mapping = _map(_map(self.spec.get("mapping")).get(s))
        expr = mapping.get(c)
        if expr is None:
            if c not in phys:
                raise SpecError(f"{self.e}: source '{s}' has no column '{c}' and no mapping")
            return q(c), phys[c]
        expr = str(expr).strip()
        if expr.upper() == "NULL":
            return None, "NULL"
        if expr in phys:
            return q(expr), phys[expr]
        err = sqlfrag.validate(expr, phys, "expr")
        if err:
            raise SpecError(f"{self.e}: mapping {s}.{c}: {err}")
        return f"({expr})", expr_type(expr, phys)

    def raw_source_column(self, s: str, c: str) -> str | None:
        """The bronze column name when c is a plain (renamed) column, else None."""
        phys = self.physical(s)
        expr = _map(_map(self.spec.get("mapping")).get(s)).get(c)
        if expr is None:
            return c if c in phys else None
        expr = str(expr).strip()
        return expr if expr in phys else None

    def formats(self, c: str) -> list[str]:
        return [str(f) for f in C.as_list(self.columns[c].get("formats")) if not _is_na(f)]

    def structural_cond(self, s: str, c: str) -> str | None:
        """SQL that is TRUE where column c is structurally NULL for rows of source s."""
        conds = []
        for key, decision in self.structural.items():
            if decision != "structural":
                continue
            parts = key.split("|")
            if parts[0] != c or len(parts) < 2 or parts[1] != f"source={s}":
                continue
            if len(parts) == 2:
                return "TRUE"
            col, _, val = parts[2].partition("=")
            conds.append(f"{q('_split__' + col)} = {lit(val)}")
        return " OR ".join(conds) if conds else None

    def split_columns(self, s: str) -> list[str]:
        out = []
        for key, decision in self.structural.items():
            parts = key.split("|")
            if decision == "structural" and len(parts) == 3 and parts[1] == f"source={s}":
                out.append(parts[2].partition("=")[0])
        return sorted(set(out))

    def allowed_values(self, s: str, c: str) -> list[str]:
        src = self.raw_source_column(s, c)
        if not src:
            return []
        av = C.get_path(self.doc, f"sources.{s}.schema.columns.{src}.allowed_values")
        if _is_na(av) or not isinstance(av, list):
            return []
        return [str(v) for v in av]

    def op_kind_sql(self) -> str:
        if self.strategy != "cdc_apply":
            return "FALSE"
        code = str(self.op_codes.get("delete", "D"))
        return f"COALESCE(trim(CAST({q(self.op_col)} AS VARCHAR)) = {lit(code)}, FALSE)"

    def op_unknown_sql(self) -> str | None:
        if self.strategy != "cdc_apply":
            return None
        codes = ", ".join(lit(str(self.op_codes.get(k))) for k in ("insert", "update", "delete") if self.op_codes.get(k))
        return f"(t.{q(self.op_col)} IS NULL OR trim(CAST(t.{q(self.op_col)} AS VARCHAR)) NOT IN ({codes}))"


def expr_type(expr: str, cols: dict[str, str]) -> str:
    import duckdb
    con = duckdb.connect()
    try:
        defs = ", ".join(f"{q(c)} {t}" for c, t in cols.items()) or "_d INTEGER"
        con.execute(f"CREATE TEMP TABLE _t ({defs})")
        return con.execute(f"DESCRIBE SELECT ({expr}) AS x FROM _t").fetchall()[0][1]
    finally:
        con.close()


def _is_text(t: str) -> bool:
    return str(t).upper().startswith(TEXT_TYPES)


def swapped_format(fmt: str) -> str | None:
    """The day/month-swapped twin of a day-first or month-first format (%d/%m/%Y <-> %m/%d/%Y).
    ISO-style formats that start with the year are not swapped: nobody writes year-day-month."""
    import re as _re
    m = _re.match(r"^%([dm])([^%])%([dm])", fmt)
    if not m or m.group(1) == m.group(3):
        return None
    return f"%{m.group(3)}{m.group(2)}%{m.group(1)}" + fmt[m.end():]


def typed_expr(P: Plan, s: str, c: str, raw: str | None, rtype: str) -> tuple[str, str | None]:
    """(typed expression, ambiguity expression or None)."""
    t = P.types[c]
    if raw is None:
        return f"CAST(NULL AS {t})", None
    if t in ("DATE", "TIMESTAMP"):
        amb = None
        if _is_text(rtype):
            fmts = P.formats(c)
            if not fmts:
                raise SpecError(f"{P.e}.{c}: a {t} column needs its formats")
            parts = [f"TRY_STRPTIME({raw}, {lit(f)})" for f in fmts]
            ts = parts[0] if len(parts) == 1 else f"COALESCE({', '.join(parts)})"
            # a value is ambiguous when two readings give different dates — between the declared
            # formats, or under the day/month swap of a declared format (04/01/2024)
            twins = [f"TRY_STRPTIME({raw}, {lit(sw)})" for f in fmts if (sw := swapped_format(f)) and sw not in fmts]
            if len(parts) + len(twins) > 1:
                amb = f"(len(list_distinct([{', '.join(parts + twins)}])) > 1)"
        else:
            ts = f"TRY_CAST({raw} AS TIMESTAMP)"
        if t == "DATE":
            return f"CAST({ts} AS DATE)", amb
        src_tz = str(P.columns[c].get("source_timezone") or P.rep_tz).strip()
        if src_tz != P.rep_tz:
            ts = f"timezone({lit(P.rep_tz)}, timezone({lit(src_tz)}, {ts}))"
        return ts, amb
    if t.startswith(TEXT_TYPES):
        base = raw if _is_text(rtype) else f"CAST({raw} AS VARCHAR)"
        return (f"trim({base})" if c in P.key else base), None
    base_t = t.split("(")[0]
    if base_t in INT_TYPES:
        # DuckDB would silently turn '3.7' (or 3.7::DOUBLE) into 4; a non-integer is cast loss
        if _is_text(rtype):
            return (f"CASE WHEN regexp_matches(trim({raw}), '^[+-]?[0-9]+$') THEN TRY_CAST(trim({raw}) AS {t}) END"), None
        return f"CASE WHEN TRY_CAST({raw} AS DOUBLE) = trunc(TRY_CAST({raw} AS DOUBLE)) THEN TRY_CAST({raw} AS {t}) END", None
    if base_t in ("DECIMAL", "NUMERIC"):
        # '3.149' into DECIMAL(10,2) would silently become 3.15: a value that does not fit the scale is cast loss
        r = f"trim({raw})" if _is_text(rtype) else raw
        return (f"CASE WHEN TRY_CAST({r} AS DOUBLE) = TRY_CAST(TRY_CAST({r} AS {t}) AS DOUBLE) "
                f"THEN TRY_CAST({r} AS {t}) END"), None
    return f"TRY_CAST({raw} AS {t})", None


# ================================================================ rendering
def _bronze_cte(s: str, scope: str) -> str:
    if scope == "batch":
        return (f"SELECT * FROM {q('bronze_' + s)} WHERE \"_batch_id\" = (SELECT batch_id FROM _scope) "
                f"AND \"_batch_version\" = (SELECT batch_version FROM _scope)")
    return (f"SELECT * FROM {q('bronze_' + s)} "
            f"QUALIFY \"_batch_version\" = max(\"_batch_version\") OVER (PARTITION BY \"_batch_id\")")


def typed_sql(P: Plan, s: str, scope: str = "batch", table: str = "_typed") -> str:
    sel = ['"_src"', '"_batch_id"', '"_batch_version"', '"_source_file"', '"_row_number"']
    for c in P.types:
        raw, rtype = P.raw_expr(s, c)
        typed, amb = typed_expr(P, s, c, raw, rtype)
        if raw is not None:
            sel.append(f"{raw} AS {q('_raw__' + c)}")
        else:
            sel.append(f"CAST(NULL AS VARCHAR) AS {q('_raw__' + c)}")
        sel.append(f"{typed} AS {q(c)}")
        sel.append(f"{amb or 'FALSE'} AS {q('_amb__' + c)}")
        av = P.allowed_values(s, c)
        if av:
            sel.append(f"({raw} IS NOT NULL AND trim(CAST({raw} AS VARCHAR)) NOT IN "
                       f"({', '.join(lit(v) for v in av)})) AS {q('_dom__' + c)}")
        else:
            sel.append(f"FALSE AS {q('_dom__' + c)}")
    for col in P.split_columns(s):
        sel.append(f"CAST({q(col)} AS VARCHAR) AS {q('_split__' + col)}")
    keycols = [(k, P.types[k]) for k in P.key]
    sk = key_sql(keycols)
    if P.salted_key:
        sk = sk.replace("md5(to_json(", "md5(dwh_salt() || to_json(", 1)
    content = "md5(to_json(struct_pack(" + ", ".join(f"{q(c)} := {q(c)}" for c in P.types) + ")))"
    key_ok = " AND ".join(f"{q(k)} IS NOT NULL" for k in P.key) or "TRUE"
    return (f"CREATE OR REPLACE TEMP TABLE {table} AS\n"
            f"WITH b AS ({_bronze_cte(s, scope)}),\n"
            f"t AS (SELECT\n  " + ",\n  ".join(sel) + "\nFROM b)\n"
            f"SELECT t.*, {sk} AS \"_sk\", {content} AS \"_content\", ({key_ok}) AS \"_key_ok\", "
            f"{P.op_kind_sql()} AS \"_is_del\"\nFROM t")


def _lookup_join(P: Plan, name: str, lk: dict) -> tuple[str, list[str], str]:
    ref = V._reference_entity(P.doc, lk.get("reference", ""))
    if not ref:
        raise SpecError(f"{P.e}: lookup {name} references unknown entity '{lk.get('reference')}'")
    on = _map(lk.get("on"))
    rt = target_of(P.doc, ref)
    alias = q("lk_" + name)
    cols = [f"{q(rc)} AS {q(name + '_' + rc)}" for rc in C.as_list(lk.get("columns"))]
    keys = [f"{q(rc)} AS {q('_k_' + lc)}" for lc, rc in on.items()]
    sub = f"(SELECT {', '.join(keys + cols)}, TRUE AS \"_hit\" FROM {q(rt)} WHERE NOT \"_is_deleted\")"
    # The reference table is the PUBLISHED silver table, where a hashed key column holds
    # md5(salt || value). Hash the local value the same way, or no row would ever match.
    ref_mask = {str(k): str(v).strip().lower() for k, v in _map(C.get_path(P.doc, f"silver.entities.{ref}.masking")).items()}
    local = {}
    for lc, rc in on.items():
        if ref_mask.get(rc) == "drop":
            raise SpecError(f"{P.e}: lookup {name} joins on {ref}.{rc}, which {ref} drops — hash it instead")
        local[lc] = (f"md5(dwh_salt() || CAST(t.{q(lc)} AS VARCHAR))" if ref_mask.get(rc) == "hash"
                     else f"t.{q(lc)}")
    cond = " AND ".join(f"{local[lc]} = {alias}.{q('_k_' + lc)}" for lc in on)
    sel = [f"{alias}.{q(name + '_' + rc)} AS {q(name + '_' + rc)}" for rc in C.as_list(lk.get("columns"))]
    sel.append(f"{alias}.\"_hit\" AS {q('_hit__' + name)}")
    local_nonnull = " AND ".join(f"t.{q(lc)} IS NOT NULL" for lc in on)
    return f"LEFT JOIN {sub} {alias} ON {cond}", sel, local_nonnull


def judged_sql(P: Plan, s: str, src_table: str = "_typed", table: str = "_judged") -> str:
    canon = {c: t for c, t in P.types.items()}
    whens: list[tuple[str, str]] = []
    not_del = "NOT t.\"_is_del\""
    for k in P.key:
        whens.append((f"t.{q('_raw__' + k)} IS NOT NULL AND t.{q(k)} IS NULL", f"cast_{k}"))
    whens.append(("NOT t.\"_key_ok\"", "null_key"))
    if P.op_unknown_sql():
        whens.append((P.op_unknown_sql(), "unknown_op"))
    for c in P.types:
        if c not in P.key:
            whens.append((f"t.{q('_raw__' + c)} IS NOT NULL AND t.{q(c)} IS NULL", f"cast_{c}"))
    for c in P.types:
        if P.ambiguity.get(c) == "reject":
            whens.append((f"t.{q('_amb__' + c)}", f"ambiguous_date_{c}"))
    for c, pol in P.null_policy.items():
        if pol.lower() == "drop" and c not in P.key and c in P.types:
            sc = P.structural_cond(s, c)
            if sc == "TRUE":
                continue
            cond = f"t.{q(c)} IS NULL" + (f" AND NOT ({sc})" if sc else "")
            whens.append((f"{not_del} AND {cond}", f"null_{c}"))
    for c in P.types:
        if P.allowed_values(s, c):
            whens.append((f"{not_del} AND t.{q('_dom__' + c)}", f"domain_{c}"))
    for name, hr in P.hard.items():
        pred = _frag((hr or {}).get("predicate"), canon, f"hard_rejects.{name}")
        whens.append((f"{not_del} AND COALESCE(({_qualify(pred)}), FALSE)", str((hr or {}).get("reason") or name)))
    joins, lk_sel = [], []
    for name, lk in P.lookups.items():
        j, sel, nonnull = _lookup_join(P, name, lk or {})
        joins.append(j)
        lk_sel += sel
        if str((lk or {}).get("missing", "reject")).lower() == "reject":
            whens.append((f"{not_del} AND {nonnull} AND lk_{name}.\"_hit\" IS NULL", f"missing_{name}"))
    reason = "CASE\n    " + "\n    ".join(f"WHEN {w} THEN {lit(r)}" for w, r in whens) + "\n  END"
    anom = "NULL"
    if P.anomalies:
        anom = "CASE " + " ".join(
            f"WHEN COALESCE(({_qualify(_frag((a or {}).get('predicate'), canon, f'valid_anomalies.{n}'))}), FALSE) "
            f"THEN {lit(n)}" for n, a in P.anomalies.items()) + " END"
    hard = "NULL"
    if P.hard:
        hard = "CASE " + " ".join(
            f"WHEN COALESCE(({_qualify(_frag((h or {}).get('predicate'), canon, f'hard_rejects.{n}'))}), FALSE) "
            f"THEN {lit(n)}" for n, h in P.hard.items()) + " END"
    cols = ", ".join(["t.*"] + lk_sel)
    return (f"CREATE OR REPLACE TEMP TABLE {table} AS\nSELECT {cols},\n  {reason} AS \"_reason\",\n"
            f"  {anom} AS \"_anomaly\",\n  {hard} AS \"_hard\"\nFROM {src_table} t\n" + "\n".join(joins))


def _frag(expr, cols: dict, where: str) -> str:
    err = sqlfrag.validate(str(expr), cols, "predicate")
    if err:
        raise SpecError(f"{where}: {err}")
    return str(expr)


def _qualify(pred: str) -> str:
    """Fragments reference canonical columns; inside the judged query those live on alias t.
    DuckDB resolves unqualified names against every joined relation, and lookups only
    contribute prefixed/underscored names, so unqualified references stay unambiguous."""
    return pred


def _order_by(P: Plan) -> str:
    items = []
    for t in P.tiebreaker:
        parts = t.split()
        items.append(f"{q(parts[0])} {parts[1].upper() if len(parts) > 1 else 'ASC'} NULLS LAST")
    items += ['"_batch_version" DESC', '"_source_file" DESC', '"_row_number" DESC']
    return ", ".join(items)


def outcome_sql(P: Plan) -> str:
    ob = _order_by(P)
    accepted = "k.any_good" if P.policy == "keep_last_good" else "k.newest_good"
    return f"""CREATE OR REPLACE TEMP TABLE _outcome AS
WITH r AS (
  SELECT *,
    CASE WHEN "_key_ok" THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_sk" ORDER BY {ob}) END AS "_rank_all",
    CASE WHEN "_key_ok" AND "_reason" IS NULL
         THEN ROW_NUMBER() OVER (PARTITION BY "_key_ok", "_reason" IS NULL, "_sk" ORDER BY {ob}) END AS "_rank_good"
  FROM _judged),
k AS (
  SELECT "_sk", bool_or("_reason" IS NULL) AS any_good,
         bool_or("_rank_all" = 1 AND "_reason" IS NULL) AS newest_good
  FROM r WHERE "_key_ok" GROUP BY "_sk")
SELECT r.*,
  CASE WHEN NOT r."_key_ok" OR r."_reason" IS NOT NULL THEN 'dead_letter'
       WHEN NOT {accepted} THEN 'dead_letter'
       WHEN r."_rank_good" = 1 THEN 'survivor'
       ELSE 'duplicate' END AS "_outcome",
  CASE WHEN r."_reason" IS NOT NULL THEN r."_reason"
       WHEN NOT {accepted} THEN 'key_rejected' END AS "_dl_reason"
FROM r LEFT JOIN k ON r."_sk" = k."_sk" AND r."_key_ok\""""


def final_sql(P: Plan, s: str) -> str:
    inner = []
    for c, t in P.types.items():
        pol = P.null_policy.get(c, "keep")
        if pol.lower().startswith("impute:"):
            val = pol.partition(":")[2]
            sc = P.structural_cond(s, c)
            if sc == "TRUE":
                inner.append(f"{q(c)}")
                inner.append(f"FALSE AS {q('is_' + c + '_imputed')}")
                continue
            guard = f"{q(c)} IS NULL" + (f" AND NOT ({sc})" if sc else "")
            inner.append(f"CASE WHEN {guard} THEN CAST({lit(val)} AS {t}) ELSE {q(c)} END AS {q(c)}")
            inner.append(f"({guard}) AS {q('is_' + c + '_imputed')}")
        else:
            inner.append(q(c))
    for name, lk in P.lookups.items():
        for rc in C.as_list((lk or {}).get("columns")):
            inner.append(q(f"{name}_{rc}"))
    inner += ['"_sk"', '"_src"', '"_batch_id"', '"_batch_version"', '"_source_file"', '"_row_number"', '"_is_del"']
    canon = dict(P.types)
    outer = []
    for c, t in P.out_columns():
        if c in P.types and P.masking.get(c) == "hash":
            outer.append(f"md5(dwh_salt() || CAST({q(c)} AS VARCHAR)) AS {q(c)}")
        elif c in P.flags:
            pred = _frag(P.flags[c], canon, f"flags.{c}")
            outer.append(f"COALESCE(({pred}), FALSE) AS {q(c)}")
        else:
            outer.append(q(c))
    business = [c for c, _ in P.out_columns()]
    row_hash = "md5(to_json(struct_pack(" + ", ".join(f"{q(c)} := {q(c)}" for c in business) + ")))"
    extra = ', CASE WHEN "_is_del" THEN \'delete\' ELSE \'upsert\' END AS "_op"' if P.strategy == "cdc_apply" else ""
    return (f"CREATE OR REPLACE TEMP TABLE _final AS\n"
            f"WITH i AS (SELECT {', '.join(inner)} FROM _outcome WHERE \"_outcome\" = 'survivor'),\n"
            f"o AS (SELECT {', '.join(outer)}, \"_sk\", \"_src\", \"_batch_id\", \"_batch_version\", "
            f"\"_source_file\", \"_row_number\", \"_is_del\" FROM i)\n"
            f"SELECT {', '.join(q(c) for c in business)}, \"_sk\", {row_hash} AS \"_row_hash\", \"_src\", "
            f"\"_batch_id\", \"_batch_version\", \"_source_file\", \"_row_number\", dwh_now() AS \"_loaded_at\", "
            f"FALSE AS \"_is_deleted\"{extra}\nFROM o\nORDER BY \"_sk\"")


def raw_row_sql(P: Plan, s: str) -> str:
    """The rejected row as JSON: declared columns only; pii/sensitive/regulated values hashed."""
    cols = C.get_path(P.doc, f"sources.{s}.schema.columns") or {}
    parts = []
    for i, (c, cs) in enumerate(cols.items()):
        cls = str((cs or {}).get("classification", "") if isinstance(cs, dict) else "").lower()
        ref = f"\"__raw\".{q(c)}"
        val = f"md5(dwh_salt() || CAST({ref} AS VARCHAR))" if cls in ("pii", "sensitive", "regulated", "") else ref
        parts.append(f"{lit(c)}, {val}")
    return f"json_object({', '.join(parts)})" if parts else "NULL"


def deadletter_sql(P: Plan, s: str) -> str:
    return (f"DELETE FROM {DL_TABLE} WHERE entity = {lit(P.e)} AND src = (SELECT src FROM _scope) "
            f"AND batch_id = (SELECT batch_id FROM _scope);\n"
            f"INSERT INTO {DL_TABLE} SELECT {lit(P.e)}, o.\"_src\", o.\"_batch_id\", o.\"_batch_version\", "
            f"o.\"_source_file\", o.\"_row_number\", o.\"_dl_reason\", o.\"_anomaly\", dwh_now(), {raw_row_sql(P, s)}\n"
            f"FROM _outcome o JOIN {q('bronze_' + s)} \"__raw\" ON \"__raw\".\"_batch_id\" = o.\"_batch_id\" "
            f"AND \"__raw\".\"_batch_version\" = o.\"_batch_version\" AND \"__raw\".\"_row_number\" = o.\"_row_number\"\n"
            f"WHERE o.\"_outcome\" = 'dead_letter'")


def withdraw_sql(P: Plan) -> str:
    """reject_key: a stored record whose newest version (this batch) was rejected is withdrawn
    (soft-deleted) — a stale version must not stand in for a rejected correction."""
    T = q(P.target)
    if P.policy != "reject_key" or P.strategy not in ("upsert_by_version", "cdc_apply", "snapshot_diff"):
        return "CREATE OR REPLACE TEMP TABLE _withdraw AS SELECT NULL::VARCHAR AS \"_sk\" WHERE FALSE"
    newer = "TRUE"
    if P.strategy in ("upsert_by_version", "cdc_apply"):
        v = q(P.version_col if P.strategy == "upsert_by_version" else P.sequence_col)
        newer = f"(o.{v} > t.{v} OR t.{v} IS NULL)"
    return (f"CREATE OR REPLACE TEMP TABLE _withdraw AS SELECT DISTINCT o.\"_sk\" FROM _outcome o "
            f"JOIN {T} t ON o.\"_sk\" = t.\"_sk\" WHERE o.\"_rank_all\" = 1 AND o.\"_dl_reason\" IS NOT NULL "
            f"AND NOT t.\"_is_deleted\" AND NOT EXISTS (SELECT 1 FROM _final f WHERE f.\"_sk\" = o.\"_sk\") AND {newer}")


def merge_sql(P: Plan) -> str:
    T = q(P.target)
    cols = ", ".join(q(c) for c in P.target_columns())
    steps = [("create", f"CREATE TABLE IF NOT EXISTS {T} AS SELECT {cols} FROM _final WHERE FALSE")]
    zero = ("0 AS updated, 0 AS stale, 0 AS already_present, 0 AS unchanged, 0 AS reactivated, "
            "0 AS deleted, 0 AS removed")
    if P.strategy == "append":
        steps.append(("terms", f"""CREATE OR REPLACE TEMP TABLE _terms AS
SELECT COUNT(*) FILTER (WHERE t."_sk" IS NULL) AS inserted, 0 AS updated, 0 AS stale,
       COUNT(*) FILTER (WHERE t."_sk" IS NOT NULL) AS already_present, 0 AS unchanged, 0 AS reactivated,
       0 AS deleted, 0 AS removed
FROM _final f LEFT JOIN (SELECT DISTINCT "_sk" FROM {T}) t ON f."_sk" = t."_sk\""""))
        steps.append(("apply", f"""INSERT INTO {T} ({cols})
SELECT {cols} FROM _final f WHERE NOT EXISTS (SELECT 1 FROM {T} x WHERE x."_sk" = f."_sk")"""))
    elif P.strategy == "upsert_by_version":
        v = q(P.version_col)
        newer = f'(f.{v} > t.{v} OR (t.{v} IS NULL AND f.{v} IS NOT NULL))'
        steps.append(("terms", f"""CREATE OR REPLACE TEMP TABLE _terms AS
SELECT COUNT(*) FILTER (WHERE t."_sk" IS NULL) AS inserted,
       COUNT(*) FILTER (WHERE t."_sk" IS NOT NULL AND {newer}) AS updated,
       COUNT(*) FILTER (WHERE t."_sk" IS NOT NULL AND NOT {newer}) AS stale,
       0 AS already_present, 0 AS unchanged, 0 AS reactivated, 0 AS deleted, 0 AS removed
FROM _final f LEFT JOIN {T} t ON f."_sk" = t."_sk\""""))
        steps.append(("apply", f"""CREATE OR REPLACE TEMP TABLE _replace AS
SELECT f."_sk" FROM _final f JOIN {T} t ON f."_sk" = t."_sk" WHERE {newer};
DELETE FROM {T} WHERE "_sk" IN (SELECT "_sk" FROM _replace);
INSERT INTO {T} ({cols})
SELECT {cols} FROM _final f WHERE NOT EXISTS (SELECT 1 FROM {T} x WHERE x."_sk" = f."_sk")"""))
    elif P.strategy == "partition_replace":
        p = q(P.partition_col)
        steps.append(("terms", f"""CREATE OR REPLACE TEMP TABLE _parts AS
SELECT DISTINCT CAST({p} AS VARCHAR) AS p FROM _outcome WHERE {p} IS NOT NULL;
CREATE OR REPLACE TEMP TABLE _terms AS
SELECT (SELECT COUNT(*) FROM _final) AS inserted, {zero.replace('0 AS removed', '')}
       (SELECT COUNT(*) FROM {T} WHERE "_src" = (SELECT src FROM _scope)
          AND CAST({p} AS VARCHAR) IN (SELECT p FROM _parts)) AS removed"""))
        steps.append(("apply", f"""DELETE FROM {T} WHERE "_src" = (SELECT src FROM _scope)
  AND CAST({p} AS VARCHAR) IN (SELECT p FROM _parts);
INSERT INTO {T} ({cols}) SELECT {cols} FROM _final"""))
    elif P.strategy == "cdc_apply":
        sq = q(P.sequence_col)
        newer = f'(f.{sq} > t.{sq} OR (t.{sq} IS NULL AND f.{sq} IS NOT NULL))'
        steps.append(("terms", f"""CREATE OR REPLACE TEMP TABLE _terms AS
SELECT COUNT(*) FILTER (WHERE f."_op" = 'upsert' AND t."_sk" IS NULL) AS inserted,
       COUNT(*) FILTER (WHERE f."_op" = 'upsert' AND t."_sk" IS NOT NULL AND {newer}) AS updated,
       COUNT(*) FILTER (WHERE (t."_sk" IS NOT NULL AND NOT {newer}) OR (f."_op" = 'delete' AND t."_sk" IS NULL)) AS stale,
       0 AS already_present, 0 AS unchanged, 0 AS reactivated,
       COUNT(*) FILTER (WHERE f."_op" = 'delete' AND t."_sk" IS NOT NULL AND {newer}) AS deleted, 0 AS removed
FROM _final f LEFT JOIN {T} t ON f."_sk" = t."_sk\""""))
        steps.append(("apply", f"""CREATE OR REPLACE TEMP TABLE _apply AS
SELECT f.* FROM _final f LEFT JOIN {T} t ON f."_sk" = t."_sk"
WHERE (t."_sk" IS NULL AND f."_op" = 'upsert') OR (t."_sk" IS NOT NULL AND {newer});
UPDATE {T} SET "_is_deleted" = TRUE, {sq} = a.{sq}, "_batch_id" = a."_batch_id",
  "_batch_version" = a."_batch_version", "_loaded_at" = a."_loaded_at"
FROM _apply a WHERE {T}."_sk" = a."_sk" AND a."_op" = 'delete';
DELETE FROM {T} WHERE "_sk" IN (SELECT "_sk" FROM _apply WHERE "_op" = 'upsert');
INSERT INTO {T} ({cols}) SELECT {cols} FROM _apply WHERE "_op" = 'upsert'"""))
    elif P.strategy == "snapshot_diff":
        steps.append(("terms", f"""CREATE OR REPLACE TEMP TABLE _present AS
SELECT DISTINCT "_sk" FROM _outcome WHERE "_key_ok";
CREATE OR REPLACE TEMP TABLE _terms AS
SELECT COUNT(*) FILTER (WHERE t."_sk" IS NULL) AS inserted,
       COUNT(*) FILTER (WHERE t."_sk" IS NOT NULL AND NOT t."_is_deleted" AND t."_row_hash" <> f."_row_hash") AS updated,
       0 AS stale, 0 AS already_present,
       COUNT(*) FILTER (WHERE t."_sk" IS NOT NULL AND NOT t."_is_deleted" AND t."_row_hash" = f."_row_hash") AS unchanged,
       COUNT(*) FILTER (WHERE t."_sk" IS NOT NULL AND t."_is_deleted") AS reactivated,
       (SELECT COUNT(*) FROM {T} x WHERE x."_src" = (SELECT src FROM _scope) AND NOT x."_is_deleted"
          AND x."_sk" NOT IN (SELECT "_sk" FROM _present)) AS deleted,
       0 AS removed
FROM _final f LEFT JOIN {T} t ON f."_sk" = t."_sk\""""))
        steps.append(("apply", f"""UPDATE {T} SET "_is_deleted" = TRUE, "_batch_id" = (SELECT batch_id FROM _scope),
  "_batch_version" = (SELECT batch_version FROM _scope), "_loaded_at" = dwh_now()
WHERE "_src" = (SELECT src FROM _scope) AND NOT "_is_deleted" AND "_sk" NOT IN (SELECT "_sk" FROM _present);
DELETE FROM {T} WHERE "_sk" IN (SELECT f."_sk" FROM _final f JOIN {T} t ON f."_sk" = t."_sk"
  WHERE t."_row_hash" <> f."_row_hash" OR t."_is_deleted");
INSERT INTO {T} ({cols}) SELECT {cols} FROM _final f WHERE NOT EXISTS (SELECT 1 FROM {T} x WHERE x."_sk" = f."_sk")"""))
    # every strategy: withdrawn keys (reject_key) are counted and soft-deleted after the merge
    name, terms = steps[1]
    steps[1] = (name, withdraw_sql(P) + ";\n" + terms + ";\nCREATE OR REPLACE TEMP TABLE _terms AS SELECT x.*, "
                "(SELECT COUNT(*) FROM _withdraw) AS withdrawn FROM _terms x")
    name, apply = steps[2]
    steps[2] = (name, apply + f";\nUPDATE {T} SET \"_is_deleted\" = TRUE, \"_loaded_at\" = dwh_now() "
                "WHERE \"_sk\" IN (SELECT \"_sk\" FROM _withdraw)")
    return _steps(steps)


def _steps(steps: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"-- @step {name}\n{sql.strip()};" for name, sql in steps) + "\n"


def split_steps(body: str) -> list[tuple[str, str]]:
    out, name, buf = [], None, []
    for line in body.splitlines():
        if line.startswith("-- @step "):
            if name:
                out.append((name, "\n".join(buf).strip()))
            name, buf = line[len("-- @step "):].strip(), []
        elif name:
            buf.append(line)
    if name:
        out.append((name, "\n".join(buf).strip()))
    return out


def source_body(P: Plan, s: str) -> str:
    return _steps([("typed", typed_sql(P, s)), ("judged", judged_sql(P, s)), ("outcome", outcome_sql(P)),
                   ("final", final_sql(P, s)), ("deadletter", deadletter_sql(P, s))])


def render(project: Project) -> dict:
    doc = project.document()
    out = {}
    for e in entity_order(doc):
        P = Plan(doc, e)
        files = {f"silver/{e}__{s}.sql": source_body(P, s) for s in P.sources}
        files[f"silver/{e}__merge.sql"] = merge_sql(P)
        sha = C.canonical_hash({"entity": P.spec, "tz": P.rep_tz, "key_algo": KEY_ALGO,
                                "sources": {s: C.get_path(doc, f"sources.{s}") for s in P.sources}})
        for rel, body in files.items():
            out[rel] = (body, sha)
    return out


# ================================================================ read-back and data checks
def _con_with_bronze(project: Project, P: Plan):
    con = connect(project)
    _macros(con, project)
    for s in P.sources:
        if not table_exists(con, f"bronze_{s}"):
            con.close()
            raise NoBronzeData(f"bronze_{s} does not exist yet")
    return con


def _typed_all(con, P: Plan) -> None:
    """All bronze rows (latest version of each batch) typed, unioned across sources."""
    parts = []
    for i, s in enumerate(P.sources):
        con.execute(typed_sql(P, s, scope="latest", table=f"_ta{i}"))
        parts.append(f"SELECT * FROM _ta{i}")
    con.execute("CREATE OR REPLACE TEMP TABLE _typed_all AS " + " UNION ALL BY NAME ".join(parts))


def rules_hash(P: Plan) -> str:
    return C.canonical_hash({"valid_anomalies": P.anomalies, "hard_rejects": P.hard, "flags": P.flags})


def rule_readback(project: Project, e: str, write: bool = False) -> dict:
    doc = project.document()
    P = Plan(doc, e)
    canon = dict(P.types)
    con = _con_with_bronze(project, P)
    try:
        _typed_all(con, P)
        total = con.execute("SELECT COUNT(*) FROM _typed_all").fetchone()[0]
        rows, conflicts = [], []
        for kind, items, action in (("valid anomaly", P.anomalies, "KEEP — never removed"),
                                    ("hard reject", P.hard, "DEAD-LETTER"),
                                    ("flag", {k: {"predicate": v} for k, v in P.flags.items()}, "flag = TRUE")):
            for name, spec in items.items():
                pred = _frag((spec or {}).get("predicate"), canon, f"{kind} {name}")
                n = con.execute(f"SELECT COUNT(*) FROM _typed_all WHERE COALESCE(({pred}), FALSE)").fetchone()[0]
                act = action + (f" (reason {spec.get('reason')})" if kind == "hard reject" else "")
                rows.append({"kind": kind, "name": name, "rule": pred, "matches": int(n), "action": act})
        for an, a in P.anomalies.items():
            for hn, h in P.hard.items():
                n = con.execute(
                    f"SELECT COUNT(*) FROM _typed_all WHERE COALESCE(({a['predicate']}), FALSE) "
                    f"AND COALESCE(({h['predicate']}), FALSE)").fetchone()[0]
                if n:
                    conflicts.append(f"{n} rows match valid anomaly '{an}' AND hard reject '{hn}'")
    finally:
        con.close()
    rh = rules_hash(P)
    rb_file = project.loc("readback_state") / f"{e}.json"
    prev = C.read_json(rb_file, {}) or {}
    current = _readback_current(project, e, rh, prev)
    lines = [f"# Rule read-back — entity `{e}`", "",
             f"*Generated by dwh_core from the specs and {total} bronze rows (latest version of each batch). "
             "Show this to the business-rule owner (SME); they confirm the rules mean what they intended.*", "",
             "| Kind | Name | Rule as it will run | Rows matched | Action |", "|---|---|---|---|---|"]
    for r in rows:
        warn = " ⚠ matches nothing — mistyped?" if r["matches"] == 0 else ""
        lines.append(f"| {r['kind']} | {r['name']} | `{r['rule']}` | {r['matches']}{warn} | {r['action']} |")
    lines += ["", f"Conflicts (a row cannot be both a valid anomaly and a hard reject): "
                  f"{'; '.join(conflicts) if conflicts else 'none'}", "",
              f"Rules version: `{rh[:12]}`. After the owner reviews it, record:",
              f"`dwh intake set silver.entities.{e}.readback_confirmed yes --by <SME id>`"]
    text = "\n".join(lines) + "\n"
    if write:
        from . import egress
        egress.assert_clean(text, "rule read-back")
        C.atomic_write_text(project.loc("readback_md", entity=e), text)
        C.atomic_write_json(rb_file, {"rules_hash": rh, "generated_at": now_iso(), "rows": rows,
                                      "conflicts": conflicts, "total": total})
        audit(project, "intake.readback", entity=e, rules_hash=rh)
        prev = C.read_json(rb_file, {})
        current = _readback_current(project, e, rh, prev)
    return {"text": text, "rows": rows, "conflicts": conflicts, "rules": bool(rows),
            "readback_current": current, "rules_hash": rh}


def _readback_current(project: Project, e: str, rh: str, rb: dict) -> bool:
    """The owner confirmed THIS rules version, after seeing its read-back."""
    if not rb or rb.get("rules_hash") != rh:
        return False
    from .intake import load_provenance
    rec = load_provenance(project).get(f"silver.entities.{e}.readback_confirmed") or {}
    return bool(rec.get("at")) and str(rec.get("at")) >= str(rb.get("generated_at", ""))


def ambiguity_counts(project: Project, e: str) -> dict[str, int]:
    """Live count of values that parse to different dates under two declared formats (V12)."""
    doc = project.document()
    P = Plan(doc, e)
    con = _con_with_bronze(project, P)
    try:
        _typed_all(con, P)
        out = {}
        for c in P.types:
            n = con.execute(f"SELECT COUNT(*) FROM _typed_all WHERE {q('_amb__' + c)}").fetchone()[0]
            if n:
                out[c] = int(n)
        return out
    finally:
        con.close()


# ================================================================ runtime
def _macros(con, project: Project) -> None:
    salt_file = project.state / "salt"
    if not salt_file.exists():
        import secrets
        salt_file.write_text(secrets.token_hex(16), encoding="utf-8")
    salt = salt_file.read_text(encoding="utf-8").strip()
    con.execute(f"CREATE OR REPLACE TEMP MACRO dwh_salt() AS {lit(salt)}")
    con.execute(f"CREATE OR REPLACE TEMP MACRO dwh_now() AS {lit(now_iso())}")


def _ensure_dl(con) -> None:
    con.execute(f"""CREATE TABLE IF NOT EXISTS {DL_TABLE} (entity VARCHAR, src VARCHAR, batch_id VARCHAR,
        batch_version INTEGER, source_file VARCHAR, row_number BIGINT, reason VARCHAR, anomaly VARCHAR,
        dead_lettered_at VARCHAR, raw_row JSON)""")


def _one(con, sql: str, params: list | None = None):
    return con.execute(sql, params or []).fetchone()[0]


def _pending(project: Project, P: Plan, led_e: dict, rebuild: bool) -> list[tuple[str, str, int]]:
    """(source, batch, version) to process, ascending per source; latest bronze version only."""
    from .bronze import batch_key
    bl = ledger(project, "bronze")
    out = []
    for s in P.sources:
        spec = C.get_path(P.doc, f"sources.{s}") or {}
        batches = sorted(((k.split("|", 1)[1], int(v["version"])) for k, v in bl.items()
                          if k.startswith(f"{s}|") and isinstance(v, dict) and "version" in v),
                         key=lambda bv: batch_key(spec, bv[0]))
        done = (led_e.get("sources") or {}).get(s, {}) if not rebuild else {}
        for b, ver in batches:
            if int((done.get(b) or {}).get("version", 0)) < ver:
                out.append((s, b, ver))
    return out


def entity_signature(project: Project, e: str) -> str:
    led = ledger(project, "silver").get(e) or {}
    return C.canonical_hash({"spec": led.get("spec_sha"), "sources": led.get("sources")})


def is_current(project: Project) -> tuple[bool, str]:
    """Silver reflects every landed bronze batch under the current specs."""
    doc = project.document()
    led = ledger(project, "silver")
    rendered = render(project)
    for e in entity_order(doc):
        P = Plan(doc, e)
        le = led.get(e) or {}
        bodies = {rel: v[0] for rel, v in rendered.items() if rel.startswith(f"silver/{e}__")}
        if le.get("body_sha") != C.canonical_hash(bodies):
            return False, f"silver entity '{e}' has not been built with the current specs"
        if _pending(project, P, le, rebuild=False):
            return False, f"silver entity '{e}' has bronze batches not yet processed"
    return True, "ok"


def build(project: Project, res: Results | None = None, only_entity: str | None = None,
          force_rebuild: bool = False) -> Results:
    from . import generate
    doc = project.document()
    res = res or Results("silver", only_entity or "all entities")
    led = ledger(project, "silver")
    rendered = render(project)
    order = entity_order(doc)
    con = connect(project)
    _macros(con, project)
    _ensure_dl(con)
    try:
        for e in order:
            if only_entity and e != only_entity:
                continue
            P = Plan(doc, e)
            bodies = {rel: generate.load_verified(project, rel) for rel in rendered if rel.startswith(f"silver/{e}__")}
            spec_sha = rendered[f"silver/{e}__merge.sql"][1]
            body_sha = C.canonical_hash(bodies)
            led_e = led.get(e) or {}
            refs = {r: entity_signature(project, r) for r in
                    {V._reference_entity(doc, (lk or {}).get("reference", "")) for lk in P.lookups.values()} if r}
            rebuild = force_rebuild or (led_e.get("body_sha") != body_sha) or (led_e.get("refs", {}) != refs)
            replay_why = ""
            if not rebuild:
                from .bronze import batch_key
                for s, b, ver in _pending(project, P, led_e, False):
                    done = ((led_e.get("sources") or {}).get(s) or {}).get(b)
                    if done and P.strategy != "partition_replace":
                        rebuild, replay_why = True, f"batch {s}/{b} was re-delivered; {P.strategy} replays history"
                    last = (led_e.get("last_snapshot") or {}).get(s)
                    spec = C.get_path(doc, f"sources.{s}") or {}
                    if P.strategy == "snapshot_diff" and last and batch_key(spec, b) < batch_key(spec, last):
                        rebuild, replay_why = True, f"snapshot {s}/{b} arrived after a newer one; replaying in order"
            for s in P.sources:
                if not table_exists(con, f"bronze_{s}"):
                    raise NoBronzeData(f"bronze_{s} does not exist yet — run the dwh-bronze build first")
            for lk_name, lk in P.lookups.items():
                _check_reference_unique(con, P, lk_name, lk or {}, res)
            if rebuild:
                why = ("rebuild requested" if force_rebuild else replay_why or
                       ("first build" if not led_e else "specs or reference data changed"))
                audit(project, "silver.rebuild", entity=e, reason=why)
                con.execute("BEGIN")
                con.execute(f"DROP TABLE IF EXISTS {q(P.target)}")
                con.execute(f"DELETE FROM {DL_TABLE} WHERE entity = ?", [e])
                con.execute("COMMIT")
                led_e = {"spec_sha": spec_sha, "body_sha": body_sha, "refs": refs, "sources": {},
                         "rows_after": 0, "rebuilt_at": now_iso(), "rebuild_reason": why}
            pending = _pending(project, P, led_e, rebuild)
            if not pending and not table_exists(con, P.target):
                raise NoBronzeData(f"no bronze batches for entity {e}")
            for s, b, ver in pending:
                heartbeat()
                _apply_batch(con, project, P, s, b, ver, bodies, res, led_e)
                led_e.setdefault("sources", {}).setdefault(s, {})[b] = res.facts[f"{e}|{s}|{b}"]
                if P.strategy == "snapshot_diff":
                    from .bronze import batch_key
                    spec = C.get_path(doc, f"sources.{s}") or {}
                    prev = (led_e.get("last_snapshot") or {}).get(s, b)
                    led_e.setdefault("last_snapshot", {})[s] = max(b, prev, key=lambda x: batch_key(spec, x))
                led_e["rows_after"] = res.facts[f"{e}|{s}|{b}"]["rows_after"]
                led[e] = led_e
                ledger_write(project, "silver", led)  # after COMMIT only
            led[e] = led_e
            ledger_write(project, "silver", led)
            _entity_postconditions(con, P, res, led_e)
        _export_dead_letter(con, project)
    finally:
        con.close()
    lineage.register(project, "dwh-silver", *_lineage(doc))
    return res


def _check_reference_unique(con, P: Plan, name: str, lk: dict, res: Results) -> None:
    ref = V._reference_entity(P.doc, lk.get("reference", ""))
    rt = target_of(P.doc, ref)
    if not table_exists(con, rt):
        raise NoBronzeData(f"lookup {name}: reference table {rt} is not built yet")
    on = list(_map(lk.get("on")).values())
    keys = ", ".join(q(c) for c in on)
    dup = _one(con, f"SELECT COUNT(*) FROM (SELECT {keys} FROM {q(rt)} WHERE NOT \"_is_deleted\" "
                    f"GROUP BY {keys} HAVING COUNT(*) > 1)")
    n = _one(con, f"SELECT COUNT(*) FROM {q(rt)} WHERE NOT \"_is_deleted\"")
    res.check(f"V23-{P.e}-{name}", f"{P.e}: reference key of lookup {name} is unique in {rt}",
              dup == 0, 0, dup, evaluated=n, detail="a duplicated reference key would multiply rows")
    if dup:
        raise VerificationError(f"reference key of lookup {name} is not unique in {rt}")


def _apply_batch(con, project, P: Plan, s: str, b: str, ver: int, bodies: dict, res: Results, led_e: dict) -> None:
    e, T = P.e, q(P.target)
    tag = f"{e}|{s}|{b}"
    con.execute("BEGIN")
    try:
        con.execute("CREATE OR REPLACE TEMP TABLE _scope AS SELECT ?::VARCHAR AS src, ?::VARCHAR AS batch_id, "
                    "?::INTEGER AS batch_version", [s, b, ver])
        src_steps = dict(split_steps(bodies[f"silver/{e}__{s}.sql"]))
        for name in ("typed", "judged", "outcome", "final"):
            _exec(con, src_steps[name])
        steps = dict(split_steps(bodies[f"silver/{e}__merge.sql"]))
        _exec(con, steps["create"])
        before = _one(con, f"SELECT COUNT(*) FROM {T}")
        expected_before = int(led_e.get("rows_after", 0))
        counts = dict(zip(["batch", "survivors", "dead", "dups", "null_key", "cast_loss", "anomalies_kept",
                           "conflicts", "ties"], con.execute("""
            SELECT COUNT(*), COUNT(*) FILTER (WHERE "_outcome" = 'survivor'),
                   COUNT(*) FILTER (WHERE "_outcome" = 'dead_letter'), COUNT(*) FILTER (WHERE "_outcome" = 'duplicate'),
                   COUNT(*) FILTER (WHERE NOT "_key_ok"),
                   COUNT(*) FILTER (WHERE "_outcome" = 'survivor' AND "_reason" LIKE 'cast_%'),
                   COUNT(*) FILTER (WHERE "_anomaly" IS NOT NULL AND "_outcome" <> 'dead_letter'),
                   COUNT(*) FILTER (WHERE "_anomaly" IS NOT NULL AND "_hard" IS NOT NULL), 0
            FROM _outcome""").fetchone()))
        tb_cols = ", ".join(q(t.split()[0]) for t in P.tiebreaker)
        counts["ties"] = _one(con, f"""SELECT COUNT(*) FROM (SELECT "_sk"{', ' + tb_cols if tb_cols else ''}
            FROM _outcome WHERE "_key_ok" GROUP BY ALL HAVING COUNT(DISTINCT "_content") > 1)""")
        anomalies_in = _one(con, "SELECT COUNT(*) FROM _outcome WHERE \"_anomaly\" IS NOT NULL")
        _exec(con, src_steps["deadletter"])
        _exec(con, steps["terms"])
        terms = dict(zip(["inserted", "updated", "stale", "already_present", "unchanged", "reactivated",
                          "deleted", "removed", "withdrawn"], con.execute(
            "SELECT inserted, updated, stale, already_present, unchanged, reactivated, deleted, removed, withdrawn "
            "FROM _terms").fetchone()))
        _exec(con, steps["apply"])
        if os_fault("after_merge"):
            raise VerificationError("injected fault after merge (DWH_FAULT=after_merge)")
        after = _one(con, f"SELECT COUNT(*) FROM {T}")
        dup_sk = _one(con, f"SELECT COUNT(*) FROM (SELECT \"_sk\" FROM {T} GROUP BY 1 HAVING COUNT(*) > 1)")
        key_null = " OR ".join(f"{q(k)} IS NULL" for k in P.key if P.masking.get(k) != "drop") or "FALSE"
        null_keys = _one(con, f"SELECT COUNT(*) FROM {T} WHERE {key_null}")
        dl_rows = _one(con, f"SELECT COUNT(*) FROM {DL_TABLE} WHERE entity = ? AND src = ? AND batch_id = ?", [e, s, b])
        c = counts
        merged = (terms["inserted"] + terms["updated"] + terms["stale"] + terms["already_present"]
                  + terms["unchanged"] + terms["reactivated"]
                  + (terms["deleted"] if P.strategy == "cdc_apply" else 0))
        pid = f"{e}/{s}/{b}"
        res.check(f"V18a-{pid}", f"{pid}: batch rows = survivors + dead-lettered + duplicates",
                  c["batch"] == c["survivors"] + c["dead"] + c["dups"], c["batch"],
                  f"{c['survivors']} + {c['dead']} + {c['dups']} = {c['survivors'] + c['dead'] + c['dups']}",
                  evaluated=c["batch"])
        res.check(f"V18b-{pid}", f"{pid}: every survivor has exactly one merge outcome",
                  c["survivors"] == merged, c["survivors"], f"{terms}", evaluated=max(c["survivors"], 1))
        res.check(f"V18c-{pid}", f"{pid}: table rows changed by inserted − removed",
                  after - before == terms["inserted"] - terms["removed"],
                  f"{before} + {terms['inserted']} − {terms['removed']}", after, evaluated=max(after, 1))
        res.check(f"V18d-{pid}", f"{pid}: table untouched outside the pipeline since the last batch",
                  before == expected_before, expected_before, before, detail="cumulative row law")
        res.check(f"V18e-{pid}", f"{pid}: dead-letter file holds every dead-lettered row", dl_rows == c["dead"],
                  c["dead"], dl_rows)
        res.check(f"V14a-{pid}", f"{pid}: tiebreaker separates every real duplicate", c["ties"] == 0, 0,
                  c["ties"], evaluated=c["batch"], detail="keys whose tied versions differ in content")
        res.check(f"V14b-{pid}", f"{pid}: one row per key in {P.target}", dup_sk == 0, 0, dup_sk, evaluated=max(after, 1))
        res.check(f"V13-{pid}", f"{pid}: no cast loss in survivors", c["cast_loss"] == 0, 0, c["cast_loss"],
                  evaluated=c["batch"])
        res.check(f"NK-{pid}", f"{pid}: no NULL natural key in {P.target}", null_keys == 0, 0, null_keys,
                  evaluated=max(after, 1))
        res.check(f"V04-{pid}", f"{pid}: no row is both a valid anomaly and a hard reject", c["conflicts"] == 0, 0,
                  c["conflicts"])
        res.check(f"AN-{pid}", f"{pid}: valid anomalies kept", True, "kept unless another rule applies",
                  f"{c['anomalies_kept']} of {anomalies_in} kept or superseded", fatal=False,
                  detail="anomaly rows are only dead-lettered for missing/unparseable values, never by a hard reject (V04)")
        pct = (100.0 * c["dead"] / c["batch"]) if c["batch"] else 0.0
        res.check(f"TOL-{pid}", f"{pid}: dead-lettered share within tolerance",
                  pct <= float(P.tolerance), f"<= {P.tolerance}%", f"{pct:.2f}%", evaluated=c["batch"])
        if P.strategy in ("upsert_by_version", "cdc_apply"):
            col = q(P.version_col if P.strategy == "upsert_by_version" else P.sequence_col)
            back = _one(con, f"SELECT COUNT(*) FROM _final f JOIN {T} t ON f.\"_sk\" = t.\"_sk\" WHERE f.{col} > t.{col}")
            res.check(f"V16-{pid}", f"{pid}: merge only moves forward", back == 0, 0, back,
                      evaluated=max(c["survivors"], 1))
        reasons = dict(con.execute("SELECT \"_dl_reason\", COUNT(*) FROM _outcome WHERE \"_outcome\" = "
                                   "'dead_letter' GROUP BY 1 ORDER BY 1").fetchall())
        fails = [ch for ch in res.checks if ch.id.endswith(pid) and not ch.passed and ch.fatal]
        if fails:
            raise VerificationError("; ".join(f"{f.id}: expected {f.expected}, got {f.actual}" for f in fails))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    res.facts[tag] = {"version": ver, "batch_rows": c["batch"], "survivors": c["survivors"],
                      "dead_lettered": c["dead"], "duplicates": c["dups"], **terms,
                      "rows_before": before, "rows_after": after, "dead_letter_reasons": reasons,
                      "at": now_iso()}
    audit(project, "silver.batch", entity=e, source=s, batch=b, version=ver, **{k: v for k, v in terms.items()},
          survivors=c["survivors"], dead=c["dead"], dups=c["dups"])


def _exec(con, step_sql: str) -> None:
    """A step may hold several statements; generated SQL ends each with ';' + newline."""
    for stmt in step_sql.split(";\n"):
        stmt = stmt.strip().rstrip(";").strip()
        if stmt:
            con.execute(stmt)


def os_fault(point: str) -> bool:
    import os
    return os.environ.get("DWH_FAULT") == point


def _entity_postconditions(con, P: Plan, res: Results, led_e: dict) -> None:
    T = q(P.target)
    if not table_exists(con, P.target):
        return
    n = _one(con, f"SELECT COUNT(*) FROM {T}")
    res.facts[f"{P.e}|rows"] = n
    res.facts[f"{P.e}|active_rows"] = _one(con, f"SELECT COUNT(*) FROM {T} WHERE NOT \"_is_deleted\"")
    res.check(f"ROWS-{P.e}", f"{P.e}: ledger row count equals the table", n == int(led_e.get("rows_after", n)),
              led_e.get("rows_after"), n)


def _export_dead_letter(con, project: Project) -> None:
    out = project.loc("dead_letter") / "silver_dead_letter.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT entity, src, batch_id, batch_version, source_file, row_number, reason, anomaly, "
                f"dead_lettered_at, CAST(raw_row AS VARCHAR) AS raw_row FROM {DL_TABLE} "
                f"ORDER BY entity, src, batch_id, row_number) TO {qpath(out)} (HEADER, DELIMITER ',')")


def _lineage(doc: dict):
    nodes, edges = [], []
    for e in entities(doc):
        t = target_of(doc, e)
        nodes.append({"id": t, "label": t, "layer": "silver"})
        for s in C.as_list(entities(doc)[e].get("sources")):
            edges.append({"from": f"bronze_{s}", "to": t, "label": "type · judge · merge"})
        edges.append({"from": f"bronze_{C.as_list(entities(doc)[e].get('sources'))[0]}", "to": "dead_letter",
                      "label": "rejected rows"})
        for name, lk in _map(entities(doc)[e].get("lookups")).items():
            ref = V._reference_entity(doc, (lk or {}).get("reference", ""))
            if ref:
                edges.append({"from": target_of(doc, ref), "to": t, "label": f"lookup {name}"})
    nodes.append({"id": "dead_letter", "label": "dead_letter", "layer": "dead_letter"})
    return nodes, edges
