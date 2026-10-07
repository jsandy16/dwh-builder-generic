"""Validation of the SQL fragments people write into specs (filters, rules, flags).

A spec fragment is spliced into generated SQL, so it is an injection surface
(`a > 0; DROP TABLE s` really drops a table). Every fragment must be:
  * exactly one scalar expression (no statements, subqueries, windows or stars),
  * built only from allow-listed functions (no read_csv, COPY, ATTACH, getenv, http…),
  * referencing only columns that exist in its scope,
  * of the right type (predicates must be BOOLEAN) — checked by DuckDB's binder.
"""
from __future__ import annotations

import json
import re

import duckdb

ALLOWED_FUNCTIONS = {
    # operators DuckDB represents as functions
    "+", "-", "*", "/", "//", "%", "||", "~~", "!~~", "~~*", "!~~*", "^", "**",
    "like_escape", "not_like_escape", "ilike_escape", "not_ilike_escape",
    # scalar functions
    "abs", "round", "ceil", "ceiling", "floor", "sign", "sqrt", "power", "pow", "ln", "log",
    "log10", "exp", "mod", "greatest", "least", "coalesce", "nullif", "ifnull", "isnan", "isinf",
    "lower", "upper", "lcase", "ucase", "trim", "ltrim", "rtrim", "length", "strlen", "substr",
    "substring", "left", "right", "concat", "concat_ws", "replace", "contains", "starts_with",
    "ends_with", "prefix", "suffix", "strpos", "position", "instr", "regexp_matches",
    "regexp_replace", "regexp_extract", "lpad", "rpad", "reverse", "split_part", "md5",
    "date_trunc", "datetrunc", "date_part", "datepart", "extract", "year", "month", "day",
    "dayofweek", "dayofyear", "week", "weekofyear", "quarter", "hour", "minute", "second",
    "strftime", "strptime", "try_strptime", "date_diff", "datediff", "date_sub", "datesub",
    "date_add", "epoch", "make_date", "last_day",
    "list_contains", "list_has", "array_contains", "len", "list_value",
}
FORBIDDEN_CLASSES = {"SUBQUERY", "WINDOW", "STAR", "PARAMETER", "LAMBDA", "POSITIONAL_REFERENCE"}
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _walk(node, funcs: set, cols: set, bad: set) -> None:
    if isinstance(node, dict):
        cls = node.get("class")
        if cls in FORBIDDEN_CLASSES:
            bad.add(cls)
        if cls == "FUNCTION":
            funcs.add(str(node.get("function_name", "")).lower())
        if cls == "COLUMN_REF":
            names = node.get("column_names") or []
            if names:
                cols.add(str(names[-1]).lower())
        for v in node.values():
            _walk(v, funcs, cols, bad)
    elif isinstance(node, list):
        for v in node:
            _walk(v, funcs, cols, bad)


def validate(fragment: str, columns: dict[str, str], kind: str = "predicate") -> str | None:
    """Return None when safe, else a human-readable reason."""
    if not isinstance(fragment, str) or not fragment.strip():
        return "empty SQL fragment"
    if ";" in re.sub(r"'(?:[^']|'')*'", "''", fragment):
        return "SQL fragments must be a single expression (no ';')"
    con = duckdb.connect()
    try:
        ser = json.loads(con.execute("SELECT json_serialize_sql($1)", [f"SELECT ({fragment}) AS x"]).fetchone()[0])
        if ser.get("error"):
            return f"not a valid SQL expression: {ser.get('error_message', '')[:160]}"
        stmts = ser.get("statements", [])
        if len(stmts) != 1:
            return "SQL fragments must be a single expression"
        node = stmts[0].get("node", {})
        if node.get("type") != "SELECT_NODE" or node.get("from_table", {}).get("type") not in (None, "EMPTY"):
            return "SQL fragments must be a plain expression"
        if node.get("where_clause") or node.get("group_expressions") or node.get("having") \
                or node.get("modifiers") or (node.get("cte_map", {}).get("map")):
            return "SQL fragments must be a plain expression"
        sel = node.get("select_list", [])
        if len(sel) != 1:
            return "SQL fragments must be exactly one expression"
        funcs, cols, bad = set(), set(), set()
        _walk(sel[0], funcs, cols, bad)
        if bad:
            return f"not allowed in spec fragments: {', '.join(sorted(bad)).lower()}"
        disallowed = sorted(f for f in funcs if f not in ALLOWED_FUNCTIONS)
        if disallowed:
            return f"function(s) not allowed in spec fragments: {', '.join(disallowed)}"
        known = {c.lower() for c in columns}
        unknown = sorted(c for c in cols if c not in known)
        if unknown:
            return f"unknown column(s): {', '.join(unknown)} (available: {', '.join(sorted(known))})"
        # binder check on an empty table with the real types
        defs = ", ".join(f'"{c}" {t}' for c, t in columns.items())
        con.execute(f"CREATE TEMP TABLE _t ({defs})" if defs else "CREATE TEMP TABLE _t (_dummy INTEGER)")
        typ = con.execute(f"DESCRIBE SELECT ({fragment}) AS x FROM _t").fetchall()[0][1]
        if kind == "predicate" and typ.upper() != "BOOLEAN":
            return f"a filter/rule must be TRUE/FALSE, but this expression is {typ}"
        return None
    except duckdb.Error as e:
        return f"invalid expression: {str(e).splitlines()[0][:200]}"
    finally:
        con.close()


def columns_in(fragment: str) -> set[str]:
    """Lower-cased column names an (already validated) fragment references."""
    con = duckdb.connect()
    try:
        ser = json.loads(con.execute("SELECT json_serialize_sql($1)", [f"SELECT ({fragment}) AS x"]).fetchone()[0])
        if ser.get("error"):
            return set()
        funcs, cols, bad = set(), set(), set()
        _walk(ser["statements"][0]["node"].get("select_list", []), funcs, cols, bad)
        return cols
    finally:
        con.close()


def valid_identifier(name: str) -> bool:
    return bool(_IDENT.match(name or ""))


def quote_ident(name: str) -> str:
    if not valid_identifier(name):
        raise ValueError(f"invalid identifier {name!r}: use letters, digits and underscore")
    return f'"{name}"'


def valid_type(type_str: str) -> str | None:
    # Shape check FIRST: the string is interpolated into SQL, so it must never reach
    # DuckDB unless it can only be a type name (letters, digits, spaces, commas, parens).
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_ ]*(\(\s*\d+\s*(,\s*\d+\s*)?\))?", (type_str or "").strip()):
        return f"invalid type {type_str!r}"
    con = duckdb.connect()
    try:
        con.execute(f"SELECT CAST(NULL AS {type_str})")
        return None
    except duckdb.Error as e:
        return f"invalid type {type_str!r}: {str(e).splitlines()[0][:120]}"
    finally:
        con.close()


def sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"
