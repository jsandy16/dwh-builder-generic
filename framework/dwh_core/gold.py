"""Gold: one aggregate table per target, generated from metric cards; rebuilt fully every run.

The card is the source of truth, not the SQL. Every build proves, before COMMIT:
  * grain — GROUP BY … HAVING COUNT(*) > 1 finds nothing;
  * valid range — NULL-safe and non-vacuous;
  * golden values — ≥3 numbers the owner computed by hand match (catches valid-SQL-wrong-meaning);
  * reconciliation per grain key — metric + excluded rows = silver control total;
  * exclusion size — the excluded share stays under the owner's bound;
  * population — a ratio's numerator never counts rows outside its denominator, and every value
    of the denominator column is classified (an inclusion list: new values stop the build).
Ratios publish <metric>__num and <metric>__den so dashboards recompute them, never average them.
"""
from __future__ import annotations

from decimal import Decimal

from . import config as C
from . import lineage, sqlfrag
from . import validators as V
from .project import Project, audit, now_iso
from .runtime import Results, VerificationError, connect, ledger, ledger_write, table_exists
from .silver import q, lit, target_of, _exec, split_steps

AGG = {"count": "COUNT(*)", "sum": "SUM({c})", "count_distinct": "COUNT(DISTINCT {c})"}


def metrics(doc: dict) -> dict:
    m = C.get_path(doc, "metrics")
    return m if isinstance(m, dict) else {}


def _na(v) -> bool:
    return V._na(v)


def _measure(measure: str, avg_count: bool = False) -> str:
    kind, _, col = str(measure).strip().partition(":")
    if avg_count and kind == "count" and col:
        return f"COUNT({q(col)})"
    return AGG[kind].format(c=q(col)) if kind in AGG else "NULL"


def _frag(spec: dict, path: str, cols: dict) -> str:
    v = C.get_path(spec, path)
    if v is None or _na(v):
        return "TRUE"
    err = sqlfrag.validate(str(v), cols, "predicate")
    if err:
        raise VerificationError(f"{path}: {err}")
    return f"COALESCE(({v}), FALSE)"


class Card:
    def __init__(self, doc: dict, name: str):
        self.name = name
        self.spec = metrics(doc)[name]
        s = self.spec
        self.entity = str(s.get("entity"))
        self.silver = target_of(doc, self.entity)
        self.cols = V.silver_columns(doc, self.entity, include_derived=True)
        self.type = str(s.get("metric_type", "")).lower()
        self.grain = [str(g) for g in C.as_list(s.get("grain"))]
        self.date_basis = str(s.get("date_basis"))
        self.time_grain = str(s.get("time_grain", "day")).lower()
        self.week_start = str(C.get_path(doc, "policies.calendar.week_start") or "monday").lower()
        self.precision = C.as_int(s.get("precision", "2"))
        self.unit = str(s.get("unit", "")).lower()
        self.scale = 100 if self.unit == "percent" else 1
        self.table = str(s.get("target_table"))
        self.w = _frag(s, "filters", self.cols)
        self.nf = _frag(s, "numerator.filter", self.cols)
        self.num = str(C.get_path(s, "numerator.measure") or "count")
        self.den = str(C.get_path(s, "denominator.measure") or "count")
        inc_col = C.get_path(s, "denominator.include.column")
        inc_vals = C.get_path(s, "denominator.include.values")
        exc_vals = C.get_path(s, "denominator.exclude.values")
        self.inc_col = None if _na(inc_col) else str(inc_col)
        self.inc_vals = [str(v) for v in C.as_list(inc_vals)] if not _na(inc_vals) else []
        self.exc_vals = [str(v) for v in C.as_list(exc_vals)] if not _na(exc_vals) else []
        self.inc = (f"CAST({q(self.inc_col)} AS VARCHAR) IN ({', '.join(lit(v) for v in self.inc_vals)})"
                    if self.inc_col and self.inc_vals else "TRUE")
        self.zero = str(s.get("zero_denominator", "null")).lower()
        self.additivity = str(s.get("additivity", "")).lower()

    @property
    def is_ratio(self) -> bool:
        return self.type in ("ratio", "average")

    def bucket(self) -> str:
        c = q(self.date_basis)
        if self.time_grain == "day":
            return f"CAST({c} AS DATE)"
        if self.time_grain == "week":
            if self.week_start == "sunday":
                return f"CAST(date_trunc('week', CAST({c} AS DATE) + 1) AS DATE) - 1"
            return f"CAST(date_trunc('week', {c}) AS DATE)"
        return f"CAST(date_trunc('{self.time_grain}', {c}) AS DATE)"

    def grain_select(self) -> list[str]:
        return [f"{self.bucket()} AS {q(g)}" if g == self.date_basis else q(g) for g in self.grain]

    def num_expr(self) -> str:
        if self.type == "ratio":
            return f"{_measure(self.num)} FILTER (WHERE {self.w} AND {self.nf} AND {self.inc})"
        return f"{_measure(self.num)} FILTER (WHERE {self.w} AND {self.nf})"

    def den_expr(self) -> str:
        if self.type == "ratio":
            return f"{_measure(self.den)} FILTER (WHERE {self.w} AND {self.inc})"
        # average: divide by the rows whose value is present (sum ignores NULLs, so must the count)
        ncol = self.num.partition(":")[2]
        den = f"COUNT({q(ncol)})" if self.den.strip() == "count" and ncol else _measure(self.den)
        return f"{den} FILTER (WHERE {self.w} AND {self.nf})"

    def columns(self) -> list[str]:
        p = self.precision
        if not self.is_ratio:
            agg = self.num_expr()
            if self.type == "sum":
                agg = f"ROUND({agg}, {p})"
            return [f"{agg} AS {q(self.name)}"]
        n, d = self.num_expr(), self.den_expr()
        val = f"ROUND({self.scale} * CAST({n} AS DOUBLE) / NULLIF(COALESCE({d}, 0), 0), {p})"
        if self.zero == "zero":
            val = f"CASE WHEN COALESCE({d}, 0) = 0 THEN 0 ELSE {val} END"
        return [f"{n} AS {q(self.name + '__num')}", f"{d} AS {q(self.name + '__den')}", f"{val} AS {q(self.name)}"]

    def population(self) -> str:
        if not self.is_ratio:
            return f"COUNT(*) FILTER (WHERE {self.w} AND {self.nf}) > 0"
        pop = f"COUNT(*) FILTER (WHERE {self.w}) > 0"
        if self.zero == "omit":
            pop += f" AND COALESCE({self.den_expr()}, 0) <> 0"
        return pop


def cards(doc: dict) -> list[Card]:
    return [Card(doc, m) for m in metrics(doc)]


def tables(doc: dict) -> dict[str, list[Card]]:
    out: dict[str, list[Card]] = {}
    for c in cards(doc):
        out.setdefault(c.table, []).append(c)
    return out


def render(project: Project) -> dict:
    doc = project.document()
    out = {}
    for t, cs in tables(doc).items():
        first = cs[0]
        cols = [x for c in cs for x in c.columns()]
        pop = " OR ".join(f"({c.population()})" for c in cs)
        order = ", ".join(str(i + 1) for i in range(len(first.grain)))
        body = (f"-- @step build\nCREATE OR REPLACE TABLE {q(t)} AS\n"
                f"SELECT {', '.join(first.grain_select())},\n  " + ",\n  ".join(cols) + "\n"
                f"FROM {q(first.silver)}\nWHERE NOT \"_is_deleted\"\nGROUP BY ALL\nHAVING {pop}\nORDER BY {order};\n")
        sha = C.canonical_hash({"cards": {c.name: c.spec for c in cs},
                                "calendar": C.get_path(doc, "policies.calendar")})
        out[f"gold/{t}.sql"] = (body, sha)
    return out


# ================================================================ verification
def _tol(card: Card, rounded: bool) -> Decimal:
    return (Decimal(5) / Decimal(10) ** (card.precision + 1) if rounded else Decimal(0)) + Decimal("0.000000001")


def verify(con, doc: dict, res: Results) -> None:
    for t, cs in tables(doc).items():
        rows = con.execute(f"SELECT COUNT(*) FROM {q(t)}").fetchone()[0]
        res.facts[f"{t}|rows"] = rows
        g = ", ".join(q(x) for x in cs[0].grain)
        dup = con.execute(f"SELECT COUNT(*) FROM (SELECT {g} FROM {q(t)} GROUP BY ALL HAVING COUNT(*) > 1)").fetchone()[0]
        res.check(f"GRAIN-{t}", f"{t}: one row per grain ({', '.join(cs[0].grain)})", dup == 0, 0, dup, evaluated=rows)
        for c in cs:
            _verify_card(con, c, rows, res)


def _verify_card(con, c: Card, rows: int, res: Results) -> None:
    T, m, s = q(c.table), q(c.name), c.spec
    # valid range
    lo, hi = C.get_path(s, "valid_range.min"), C.get_path(s, "valid_range.max")
    conds = []
    if not _na(lo):
        conds.append(f"{m} < {C.as_number(lo)}")
    if not _na(hi):
        conds.append(f"{m} > {C.as_number(hi)}")
    nn = con.execute(f"SELECT COUNT({m}) FROM {T}").fetchone()[0]
    bad = con.execute(f"SELECT COUNT(*) FROM {T} WHERE {' OR '.join(conds)}").fetchone()[0] if conds else 0
    res.check(f"RANGE-{c.name}", f"{c.name}: values within [{lo}, {hi}]", bad == 0, 0, bad, evaluated=nn,
              detail=f"{rows - nn} NULL value(s) not range-checked" if rows - nn else "")
    # golden values (V25)
    gv = C.get_path(s, "golden_values") or []
    if not isinstance(gv, list) or not gv:
        res.check(f"V25-{c.name}", f"{c.name}: owner's golden values", False, ">= 3 hand-computed values",
                  "pending", fatal=False, detail="not yet proven against hand-computed values — release to "
                                                 "consumers stays blocked until the owner provides them")
    for i, g in enumerate(gv if isinstance(gv, list) else []):
        key = g.get("key") or {}
        where = " AND ".join(f"CAST({q(k)} AS VARCHAR) = {lit(v)}" for k, v in key.items())
        found = con.execute(f"SELECT {m} FROM {T} WHERE {where}").fetchall()
        exp = g.get("value")
        label = ", ".join(f"{k}={v}" for k, v in key.items())
        if len(found) != 1:
            # a key with no qualifying rows has no gold row: that is 0 for a count/sum, blank for a ratio
            ok = len(found) == 0 and (
                (C.is_token(exp, "null") and (c.is_ratio or c.zero == "omit")) or
                (not c.is_ratio and not C.is_token(exp, "null") and C.as_number(exp) == 0))
            res.check(f"V25-{c.name}-{i + 1}", f"{c.name} golden value at {label}", ok, exp,
                      f"{len(found)} rows for this key")
            continue
        act = found[0][0]
        if C.is_token(exp, "null"):
            ok = act is None
        else:
            ok = act is not None and abs(Decimal(str(act)) - C.as_number(exp)) <= _tol(c, True)
        res.check(f"V25-{c.name}-{i + 1}", f"{c.name} golden value at {label}", ok, exp, act, evaluated=1)
    # reconciliation per grain key (V27) and exclusion size (V28)
    ctl = str(C.get_path(s, "reconciliation.control") or "count")
    x = C.get_path(s, "reconciliation.excluded_by")
    xs = "FALSE" if _na(x) else f"COALESCE(({x}), FALSE)"
    gsel = c.grain_select()
    aliases = [f"g{i}" for i in range(len(c.grain))]
    s_sel = ", ".join(f"{e.rsplit(' AS ', 1)[0]} AS {a}" for e, a in zip(gsel, aliases))
    g_sel = ", ".join(f"{q(gc)} AS {a}" for gc, a in zip(c.grain, aliases))
    on = " AND ".join(f"s.{a} IS NOT DISTINCT FROM g.{a}" for a in aliases)
    vcol = q(c.name + "__den") if c.is_ratio else m
    tol = _tol(c, rounded=(c.type == "sum"))
    ctl_sql = _measure(ctl)
    if ctl.startswith("count_distinct"):
        # distinct counts do not add across groups (one id can be on both sides): the metric must
        # equal the distinct count over the rows that are NOT excluded, per key
        ctl_expr, exc_expr = f"{ctl_sql} FILTER (WHERE NOT ({xs}))", "0"
    else:
        ctl_expr, exc_expr = ctl_sql, f"{ctl_sql} FILTER (WHERE {xs})"
    bad, keys, exc_rows, all_rows = con.execute(f"""
        WITH s AS (SELECT {s_sel}, {ctl_expr} AS ctl, {exc_expr} AS exc,
                          COUNT(*) FILTER (WHERE {xs}) AS exc_rows, COUNT(*) AS all_rows
                   FROM {q(c.silver)} WHERE NOT "_is_deleted" GROUP BY ALL),
             g AS (SELECT {g_sel}, {vcol} AS v FROM {T})
        SELECT COUNT(*) FILTER (WHERE abs(COALESCE(g.v, 0) + COALESCE(s.exc, 0) - COALESCE(s.ctl, 0)) > {tol}),
               COUNT(*), COALESCE(SUM(s.exc_rows), 0), COALESCE(SUM(s.all_rows), 0)
        FROM s FULL OUTER JOIN g ON {on}""").fetchone()
    what = "denominator" if c.is_ratio else "metric"
    res.check(f"V27-{c.name}", f"{c.name}: {what} + excluded = silver {ctl} per grain key", bad == 0, 0,
              f"{bad} key(s) off", evaluated=keys, detail=f"excluded_by: {x}")
    share = (100.0 * exc_rows / all_rows) if all_rows else 0.0
    mx = C.as_number(C.get_path(s, "reconciliation.max_excluded_pct") or "100")
    res.check(f"V28-{c.name}", f"{c.name}: excluded share within bound", share <= float(mx), f"<= {mx}%",
              f"{share:.2f}%", evaluated=all_rows)
    # population consistency (V26)
    if c.type == "ratio" and c.inc_col:
        bigger = con.execute(f"SELECT COUNT(*) FROM {T} WHERE {q(c.name + '__num')} > {q(c.name + '__den')}").fetchone()[0] \
            if c.num.split(":")[0] in ("count", "count_distinct") and c.den.split(":")[0] == "count" else 0
        res.check(f"V26a-{c.name}", f"{c.name}: numerator never exceeds denominator", bigger == 0, 0, bigger,
                  evaluated=rows)
        outside = con.execute(f"SELECT COUNT(*) FROM {q(c.silver)} WHERE NOT \"_is_deleted\" AND {c.w} AND {c.nf} "
                              f"AND NOT ({c.inc})").fetchone()[0]
        res.check(f"V26c-{c.name}", f"{c.name}: rows matching the numerator filter outside the denominator", True,
                  "reported", outside, fatal=False,
                  detail="not counted: the numerator is (numerator filter AND denominator population). "
                         "If these rows should count, the denominator definition is wrong — ask the dispute owner")
        known = c.inc_vals + c.exc_vals
        unk = con.execute(f"SELECT DISTINCT CAST({q(c.inc_col)} AS VARCHAR) FROM {q(c.silver)} WHERE NOT \"_is_deleted\" "
                          f"AND {c.w} AND (CAST({q(c.inc_col)} AS VARCHAR) IS NULL OR CAST({q(c.inc_col)} AS VARCHAR) "
                          f"NOT IN ({', '.join(lit(v) for v in known) or 'NULL'})) ORDER BY 1 NULLS FIRST").fetchall()
        res.check(f"V26b-{c.name}", f"{c.name}: every {c.inc_col} value is classified in or out of the denominator",
                  not unk, "none unclassified", [u[0] for u in unk][:10],
                  detail="add it to denominator.include.values or exclude.values (★ PO), or filter it out")
    # headline for dashboard parity (V30)
    res.facts[f"headline|{c.name}"] = headline(con, c)


def headline(con, c: Card):
    T = q(c.table)
    if c.is_ratio:
        n, d = con.execute(f"SELECT SUM({q(c.name + '__num')}), SUM({q(c.name + '__den')}) FROM {T}").fetchone()
        return None if not d else round(c.scale * float(n or 0) / float(d), c.precision)
    if c.additivity == "additive":
        v = con.execute(f"SELECT SUM({q(c.name)}) FROM {T}").fetchone()[0]
        return None if v is None else round(float(v), c.precision)
    if c.additivity == "non_additive" and [g for g in c.grain if g != c.date_basis]:
        return None  # cannot be added across the other grain columns: no single headline
    v = con.execute(f"SELECT SUM({q(c.name)}) FROM {T} WHERE {q(c.date_basis)} = "
                    f"(SELECT MAX({q(c.date_basis)}) FROM {T})").fetchone()[0]
    return None if v is None else round(float(v), c.precision)


# ================================================================ build
def silver_signature(project: Project) -> str:
    return C.canonical_hash(ledger(project, "silver"))


def build(project: Project, res: Results | None = None) -> Results:
    from . import generate
    doc = project.document()
    res = res or Results("gold", "all metric tables")
    rendered = render(project)
    bodies = {rel: generate.load_verified(project, rel) for rel in rendered}
    con = connect(project)
    try:
        for t, cs in tables(doc).items():
            if not table_exists(con, cs[0].silver):
                raise VerificationError(f"{cs[0].silver} does not exist — build silver first")
        con.execute("BEGIN")
        try:
            for rel, body in bodies.items():
                for _, sql in split_steps(body):
                    _exec(con, sql)
            verify(con, doc, res)
            if res.failures:
                raise VerificationError("gold verification failed")
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    ledger_write(project, "gold", {"spec_sha": C.canonical_hash({k: v[1] for k, v in rendered.items()}),
                                   "body_sha": C.canonical_hash(bodies), "silver_sig": silver_signature(project),
                                   "passed": True, "at": now_iso(),
                                   "tables": {t: res.facts.get(f"{t}|rows") for t in tables(doc)},
                                   "headlines": {k.split("|", 1)[1]: v for k, v in res.facts.items()
                                                 if k.startswith("headline|")}})
    write_cards(project, doc)
    nodes = [{"id": t, "label": t, "layer": "gold"} for t in tables(doc)]
    edges = [{"from": cs[0].silver, "to": t, "label": ", ".join(c.name for c in cs)} for t, cs in tables(doc).items()]
    lineage.register(project, "dwh-gold", nodes, edges)
    audit(project, "gold.built", tables={t: res.facts.get(f"{t}|rows") for t in tables(doc)})
    return res


def is_current(project: Project) -> tuple[bool, str]:
    led = ledger(project, "gold")
    if not led.get("passed"):
        return False, "gold has not been built and verified"
    if led.get("spec_sha") != C.canonical_hash({k: v[1] for k, v in render(project).items()}):
        return False, "metric cards changed since the last gold build"
    if led.get("silver_sig") != silver_signature(project):
        return False, "silver changed since the last gold build"
    return True, "ok"


def write_cards(project: Project, doc: dict) -> None:
    lines = ["# Metric cards", "", "*Generated by dwh_core from the metric specs. The card is the source of "
             "truth; the generated gold SQL is rendered from it.*", ""]
    for c in cards(doc):
        s = c.spec
        lines += [f"## {c.name}", "", f"> {s.get('plain_definition')}", "",
                  f"- **Type:** {c.type} · **unit:** {s.get('unit')} · **precision:** {c.precision} · "
                  f"**additivity:** {c.additivity}",
                  f"- **Grain:** {', '.join(c.grain)} (`{c.date_basis}` bucketed by {c.time_grain}) → table `{c.table}`",
                  f"- **Numerator:** `{c.num}` where `{C.get_path(s, 'numerator.filter')}`",
                  f"- **Filters (whole metric):** `{s.get('filters')}`"]
        if c.is_ratio:
            lines.append(f"- **Denominator:** `{c.den}`" + (f" where `{c.inc_col}` in {c.inc_vals}; excluded: "
                                                           f"{c.exc_vals or 'none'}" if c.inc_col else ""))
            lines.append(f"- **Zero denominator:** {c.zero}")
        if not _na(s.get("population")):
            lines.append(f"- **Population:** {s.get('population')}")
        lines += [f"- **Valid range:** [{C.get_path(s, 'valid_range.min')}, {C.get_path(s, 'valid_range.max')}] · "
                  f"**cadence:** {s.get('cadence')}",
                  f"- **Dispute owner:** {s.get('dispute_owner')} · **version** {s.get('version')} from "
                  f"{s.get('effective_from')}",
                  f"- **Reconciles to:** silver `{C.get_path(s, 'reconciliation.control')}` with excluded rows "
                  f"`{C.get_path(s, 'reconciliation.excluded_by')}` (≤ {C.get_path(s, 'reconciliation.max_excluded_pct')}%)",
                  "- **Golden values (computed by hand by the owner):** "
                  + "; ".join(f"{g.get('key')} → {g.get('value')}" for g in (C.get_path(s, 'golden_values') or [])), ""]
    C.atomic_write_text(project.loc("metric_cards"), "\n".join(lines))
