# dwh_core:generated v=1.2.0 template=serve/v1 template_sha=e85d92d4cec5f923 spec_sha=393c5d2223f8ea46 body_sha=68a8670af3e99567ea2c9b7a5554e76ec873825e797d2bebf6f8c10f1ca1994e
# DO NOT EDIT — change the specs and run `dwh generate`. Custom logic goes in custom/.
"""Streamlit dashboard bound to the metric cards."""
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
