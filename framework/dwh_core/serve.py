"""Dashboard bound to the metric cards (Streamlit in v1).

Two generated files: `serve/dash_data.py` (pure data functions — KPIs recomputed from the card,
ratios from numerator ÷ denominator, never averaged) and `serve/app.py` (the UI). The app reads
only the published snapshot (serving/CURRENT) and refuses to render a file whose hash does not
match the manifest. `dwh serve --check` proves it headlessly (V30, V42, V45).
"""
from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
import time
import urllib.request

from . import config as C
from . import generate
from .project import Project, audit
from .runtime import Results, ledger

DASH_DATA = r'''"""Dashboard data access: pure functions, testable without Streamlit."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

CONFIG = json.loads(__CONFIG__)
POINTER = __import__("os").environ.get("DWH_SERVE_POINTER", "CURRENT")
ROOT = next(p for p in Path(__file__).resolve().parents if (p / "dwh-project.yaml").exists())
SERVING = ROOT / __SERVING__


class SnapshotError(RuntimeError):
    pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def current_snapshot(root=ROOT, pointer=None):
    serving = SERVING if Path(root) == ROOT else Path(root) / __SERVING__
    ptr = serving / (pointer or POINTER)
    if not ptr.exists():
        raise SnapshotError("Nothing has been published yet. Run `dwh publish` after a passing gold build.")
    snap = serving / ptr.read_text(encoding="utf-8").strip()
    mf = snap / "manifest.json"
    if not mf.exists():
        raise SnapshotError(f"{snap.name} has no manifest (incomplete publish).")
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    for t, info in manifest["tables"].items():
        f = snap / info["file"]
        if not f.exists() or _sha256(f) != info["sha256"]:
            raise SnapshotError(f"{t}: file does not match the snapshot manifest; refusing to show it.")
    return snap, manifest


def load_tables(snap, manifest):
    out = {}
    for t, info in manifest["tables"].items():
        df = pd.read_parquet(Path(snap) / info["file"])
        for c in CONFIG["cards"].values():
            if c["table"] == t:
                df[c["date_basis"]] = pd.to_datetime(df[c["date_basis"]])
                for col in [c["name"], c["name"] + "__num", c["name"] + "__den"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
        out[t] = df
    return out


def card(name):
    return CONFIG["cards"][name]


def date_bounds(tables):
    lo = hi = None
    for c in CONFIG["cards"].values():
        s = tables[c["table"]][c["date_basis"]]
        if len(s):
            lo = s.min() if lo is None else min(lo, s.min())
            hi = s.max() if hi is None else max(hi, s.max())
    return (lo.date() if lo is not None else None), (hi.date() if hi is not None else None)


def frame(tables, name, start=None, end=None, filters=None):
    c = card(name)
    df = tables[c["table"]]
    if start is not None:
        df = df[df[c["date_basis"]] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df[c["date_basis"]] <= pd.Timestamp(end)]
    for col, vals in (filters or {}).items():
        if col in df.columns and vals:
            df = df[df[col].astype(str).isin([str(v) for v in vals])]
    return df


def filter_values(tables, col):
    vals = set()
    for c in CONFIG["cards"].values():
        df = tables[c["table"]]
        if col in df.columns:
            vals |= set(df[col].dropna().astype(str))
    return sorted(vals)


def _ratio(c, num, den):
    if not den:
        return None
    return round(c["scale"] * float(num) / float(den), c["precision"])


def kpi(tables, name, start=None, end=None, filters=None):
    """(value, note). Ratios: sum(numerator) / sum(denominator) over the selection, never an average."""
    c = card(name)
    df = frame(tables, name, start, end, filters)
    if df.empty:
        return None, "no data for this selection"
    if c["ratio"]:
        return _ratio(c, df[name + "__num"].sum(), df[name + "__den"].sum()), "recomputed from numerator and denominator"
    if c["additivity"] == "additive":
        return round(float(df[name].sum()), c["precision"]), ""
    latest = df[c["date_basis"]].max()
    return round(float(df.loc[df[c["date_basis"]] == latest, name].sum()), c["precision"]), \
        f"latest {c['time_grain']} ({latest.date()}) — this metric cannot be summed over time"


def chart_frame(tables, chart, start=None, end=None, filters=None):
    name = chart["metric"]
    c = card(name)
    df = frame(tables, name, start, end, filters)
    keys = [chart["x"]] + ([chart["color"]] if chart.get("color") else [])
    if df.empty:
        return pd.DataFrame()
    if c["additivity"] == "semi_additive" and c["date_basis"] not in keys:
        df = df[df[c["date_basis"]] == df[c["date_basis"]].max()]
    if c["ratio"]:
        g = df.groupby(keys, dropna=False)[[name + "__num", name + "__den"]].sum().reset_index()
        g[name] = [_ratio(c, n, d) for n, d in zip(g[name + "__num"], g[name + "__den"])]
    else:
        g = df.groupby(keys, dropna=False)[name].sum(min_count=1).reset_index()
    if chart.get("color"):
        out = g.pivot_table(index=chart["x"], columns=chart["color"], values=name, aggfunc="first", dropna=False)
        if not c["ratio"] and c["additivity"] == "additive":
            out = out.fillna(0)  # nothing recorded = 0 for an additive metric; a ratio stays undefined
    else:
        out = g.set_index(chart["x"])[[name]]
    return out.sort_index()


def freshness(tables, manifest, now=None):
    """(status, text) using the reference clock the owner chose."""
    clock = CONFIG["clock"]
    now = now or datetime.now(timezone.utc)
    if clock == "replay":
        return "replay", "Replayed/historical data — freshness is not alarmed."
    limit = float(CONFIG.get("stale_after_hours") or 0)
    if clock == "load":
        published = datetime.fromisoformat(manifest["published_at"])
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age = (now - published).total_seconds() / 3600
        what = f"published {age:.1f} h ago"
    else:
        lo, hi = date_bounds(tables)
        if hi is None:
            return "stale", "No data."
        age = (now.date() - hi).days * 24
        what = f"newest data {hi} ({age / 24:.0f} days ago)"
    if limit and age > limit:
        return "stale", f"STALE — {what}; expected within {limit:.0f} h."
    return "fresh", f"Fresh — {what}."


def fmt(name, v):
    c = card(name)
    if v is None:
        return "—"
    p = c["precision"]
    if c["unit"] == "percent":
        return f"{v:,.{p}f}%"
    if c["unit"].startswith("currency:"):
        return f"{c['unit'].split(':', 1)[1].upper()} {v:,.{p}f}"
    return f"{v:,.{p}f}"
'''

APP = r'''"""Streamlit dashboard bound to the metric cards."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

import dash_data as D  # noqa: E402

cfg = D.CONFIG
st.set_page_config(page_title=cfg["title"], layout="wide")
st.title(cfg["title"])
st.caption(cfg["audience"])
try:
    snap, manifest = D.current_snapshot()
except D.SnapshotError as e:
    st.error(str(e))
    st.stop()
tables = D.load_tables(snap, manifest)
if manifest.get("synthetic_data"):
    st.warning("SYNTHETIC DATA — generated test data, not real figures.")
if manifest.get("target") != "consumers":
    pend = manifest.get("pending_decisions") or []
    st.info("Unreleased: a local snapshot, not released to consumers"
            + (f" — {len(pend)} human-owned decision(s) still pending." if pend else
               (" — the current specs are not approved." if not manifest.get("approved") else ".")))
status, text = D.freshness(tables, manifest)
(st.error if status == "stale" else st.caption)(text)

lo, hi = D.date_bounds(tables)
start, end = lo, hi
if lo is not None:
    picked = st.sidebar.date_input("Date range", (lo, hi), min_value=lo, max_value=hi)
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        start, end = picked
filters = {}
for col in cfg["filters"]:
    pick = st.sidebar.multiselect(col, D.filter_values(tables, col))
    if pick:
        filters[col] = pick

if cfg["kpis"]:
    boxes = st.columns(len(cfg["kpis"]))
    for box, k in zip(boxes, cfg["kpis"]):
        v, note = D.kpi(tables, k["metric"], start, end, filters)
        box.metric(k["label"], D.fmt(k["metric"], v), help=note or None)

for ch in cfg["charts"]:
    st.subheader(ch["title"])
    df = D.chart_frame(tables, ch, start, end, filters)
    if df.empty:
        st.info("No data for this selection.")
        continue
    (st.line_chart if ch["type"] == "line" else st.bar_chart)(df)

st.caption(f"Snapshot {manifest['run_id']} · published {manifest['published_at']} · "
           f"specs {manifest['spec_hash'][:12]} · {'released to consumers' if manifest.get('target') == 'consumers' else 'local'}")
if cfg.get("auto_refresh_seconds"):
    import streamlit.components.v1 as components
    components.html(f"<script>setTimeout(function(){{window.parent.location.reload()}}, "
                    f"{int(cfg['auto_refresh_seconds']) * 1000});</script>", height=0)
'''


def _na(v) -> bool:
    return C.is_blank(v) or C.is_token(v, C.NA_TOKEN) or C.is_token(v, C.NONE_TOKEN)


def config(project: Project) -> dict:
    from . import gold
    doc = project.document()
    sv = C.get_path(doc, "serve") or {}
    kpis = [{"name": k, "metric": v["metric"], "label": v.get("label") if not _na(v.get("label")) else v["metric"]}
            for k, v in (sv.get("kpis") or {}).items()]
    charts = [{"name": k, "title": v.get("title") if not _na(v.get("title")) else k.replace("_", " ").capitalize(),
               "type": v["type"], "metric": v["metric"],
               "x": v["x"], "color": None if _na(v.get("color")) else v["color"]}
              for k, v in (sv.get("charts") or {}).items()]
    used = {k["metric"] for k in kpis} | {c["metric"] for c in charts}
    cards = {}
    for c in gold.cards(doc):
        if c.name in used:
            cards[c.name] = {"name": c.name, "table": c.table, "ratio": c.is_ratio, "scale": c.scale,
                             "precision": c.precision, "additivity": c.additivity, "date_basis": c.date_basis,
                             "time_grain": c.time_grain, "unit": c.unit, "grain": c.grain}
    filters = [f for f in C.as_list(sv.get("filters")) if not _na(f)]
    return {"title": sv.get("title"), "audience": sv.get("audience"), "clock": str(sv.get("reference_clock")).lower(),
            "stale_after_hours": None if _na(sv.get("stale_after_hours")) else C.as_int(sv["stale_after_hours"]),
            "port": C.as_int(sv.get("port")) if not _na(sv.get("port")) else 8501,
            "auto_refresh_seconds": None if _na(sv.get("auto_refresh_seconds")) else C.as_int(sv["auto_refresh_seconds"]),
            "filters": filters, "kpis": kpis, "charts": charts, "cards": cards}


def render(project: Project) -> dict:
    cfg = config(project)
    blob = json.dumps(cfg, indent=1, sort_keys=True)
    sha = C.canonical_hash(cfg)
    # repr() makes a safe Python literal whatever the answers contain (no triple-quote break-out)
    serving = repr(project.layout.rel("serving"))
    return {"serve/dash_data.py": (DASH_DATA.replace("__CONFIG__", repr(blob)).replace("__SERVING__", serving), sha),
            "serve/app.py": (APP, sha)}


class ServeBlocked(RuntimeError):
    pass


def _gate(project: Project) -> None:
    from .intake import check as intake_check
    rep = intake_check(project, "serve", "A")
    if not rep.ok:
        raise ServeBlocked("the dashboard needs these inputs first:\n" + rep.render())


def _load_dash(project: Project):
    _gate(project)
    generate.render_layer(project, "serve")
    for rel in ("serve/dash_data.py", "serve/app.py"):
        generate.load_verified(project, rel)  # refuses hand-edited files
    path = project.layout.generated("serve/dash_data.py")
    spec = importlib.util.spec_from_file_location("dash_data", path)
    mod = importlib.util.module_from_spec(spec)
    old, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # keep generated/ free of caches
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(project: Project, released: bool = False) -> int:
    import os
    try:
        D = _load_dash(project)
    except (ServeBlocked, generate.TamperedFile) as e:
        print(f"BLOCKED — {e}")
        return 2
    pointer = "RELEASED" if released else "CURRENT"
    os.environ["DWH_SERVE_POINTER"] = pointer
    try:
        D.current_snapshot(project.root, pointer)
    except D.SnapshotError as e:
        print(f"refused: {e}")
        return 2
    port = D.CONFIG["port"]
    app = project.layout.generated("serve/app.py")
    print(f"dashboard ({pointer} snapshot): http://localhost:{port}  (Ctrl+C to stop)")
    audit(project, "serve.start", port=port)
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(port),
                            "--server.address", "127.0.0.1",
                            "--server.headless", "true", "--browser.gatherUsageStats", "false",
                            "--client.toolbarMode", "viewer"], cwd=project.root)


def check(project: Project, screenshot: bool = True) -> int:
    res = Results("serve", "dashboard")
    try:
        D = _load_dash(project)
    except (generate.TamperedFile, ServeBlocked) as e:
        print(f"refused: {e}")
        return 2
    try:
        snap, manifest = D.current_snapshot(project.root)
        res.check("V42", "snapshot files match the manifest", True, "match", "match")
    except D.SnapshotError as e:
        res.check("V42", "snapshot files match the manifest", False, "match", str(e))
        return _finish(project, res)
    tables = D.load_tables(snap, manifest)
    heads = manifest.get("headlines") or {}
    for k in D.CONFIG["kpis"]:
        m = k["metric"]
        v, _ = D.kpi(tables, m)
        exp = heads.get(m)
        p = D.CONFIG["cards"][m]["precision"]
        ok = (v is None and exp is None) or (v is not None and exp is not None and abs(v - exp) <= 10 ** -p + 1e-9)
        res.check(f"V30-{k['name']}", f"KPI '{k['label']}' equals the gold-verified headline", ok, exp, v, evaluated=1)
    for ch in D.CONFIG["charts"]:
        df = D.chart_frame(tables, ch)
        card = D.CONFIG["cards"][ch["metric"]]
        src = tables[card["table"]]
        res.check(f"CH-{ch['name']}-rows", f"chart '{ch['name']}' has data", not df.empty, "> 0 points",
                  int(df.size), evaluated=len(src))
        if ch.get("color") and not df.empty:
            want = set(src[ch["color"]].dropna().astype(str))
            got = {str(c) for c in df.columns}
            res.check(f"CH-{ch['name']}-series", f"chart '{ch['name']}' shows every {ch['color']} value",
                      want <= got, sorted(want)[:10], sorted(got)[:10], evaluated=len(want))
    st, text = D.freshness(tables, manifest)
    res.facts["freshness"] = text
    res.check("V48", "freshness banner uses the declared reference clock", st in ("fresh", "stale", "replay"),
              D.CONFIG["clock"], st, fatal=False)
    _smoke(project, res, screenshot)
    return _finish(project, res)


def _smoke(project: Project, res: Results, screenshot: bool) -> None:
    try:
        import streamlit  # noqa: F401
    except ImportError:
        res.check("V45", "dashboard starts headless and answers /_stcore/health", False, "200",
                  "streamlit not installed", fatal=False, detail="pip install streamlit, then re-run serve --check")
        return
    port = _free_port()
    app = project.layout.generated("serve/app.py")
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(port),
                             "--server.address", "127.0.0.1",
                             "--server.headless", "true", "--browser.gatherUsageStats", "false",
                             "--client.toolbarMode", "viewer"],
                            cwd=project.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        code = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as r:
                    code = r.status
                    break
            except Exception:
                time.sleep(0.5)
        res.check("V45", "dashboard starts headless and answers /_stcore/health", code == 200, 200, code)
        if code == 200 and screenshot:
            _screenshot(project, res, url)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _screenshot(project: Project, res: Results, url: str) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        res.facts["screenshot"] = "playwright not installed — skipped"
        return
    out = project.loc("dashboard_png")
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_selector('[data-testid="stMetric"], [data-testid="stAlert"]', timeout=60000)
            time.sleep(2)
            errors = page.locator('[data-testid="stException"]').count()
            page.screenshot(path=str(out), full_page=True)
            b.close()
        res.check("V45-render", "dashboard renders without an exception", errors == 0, 0, errors)
        res.facts["screenshot"] = str(out.relative_to(project.root))
    except Exception as e:
        res.facts["screenshot"] = f"failed: {str(e)[:160]}"


def _finish(project: Project, res: Results) -> int:
    path = res.write(project, "serve-check", "Dashboard check (serve --check)",
                     "**PASS**" if not res.failures else "**FAILED**")
    audit(project, "serve.check", passed=not res.failures)
    for c in res.checks:
        print(f"[{'PASS' if c.passed else ('FAIL' if c.fatal else 'WARN')}] {c.id} {c.name}: {c.actual}")
    print(f"report: {path.relative_to(project.root)}")
    return 0 if not res.failures else 1
