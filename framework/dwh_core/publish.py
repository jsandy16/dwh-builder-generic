"""Publish = copy verified gold into a versioned snapshot, then swap one pointer.

    serving/snap_<run_id>/<table>.parquet + manifest.json   (rows, sha256, columns, provenance)
    serving/CURRENT   → the snapshot the dashboard reads (local publish)
    serving/RELEASED  → the snapshot released to consumers (needs 0 pending ★ and a valid approval)

The pointer is written last and atomically, so a crash mid-publish leaves the previous snapshot
live (V42). The dashboard re-checks every file hash against the manifest before rendering.
"""
from __future__ import annotations

import hashlib
import os
import shutil

from . import config as C
from .project import Project, audit, now_iso
from .runtime import Lease, connect, ledger, qpath, run_id

KEEP = 3


class PublishRefused(RuntimeError):
    pass


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def publish(project: Project, target: str = "local") -> dict:
    from . import approvals, gold, runner
    ok, why = gold.is_current(project)
    if not ok:
        raise PublishRefused(f"{why} — run `dwh build gold` first")
    gate_ok, text, _ = runner.gate(project, "publish" if target == "consumers" else "gold",
                                   unattended=(target == "consumers"))
    if not gate_ok:
        raise PublishRefused("intake is incomplete:\n" + text)
    pending = runner.pending_decisions(project)
    appr = approvals.status(project)
    if target == "consumers":
        if pending:
            raise PublishRefused(f"{len(pending)} human-owned decision(s) still pending: "
                                 + ", ".join(p["path"] for p in pending[:8]))
        if not appr["chain_ok"]:
            raise PublishRefused(appr["chain_detail"])
        if not appr["approved"]:
            raise PublishRefused("the current specs are not approved"
                                 + (" (they changed after the last approval)" if appr["stale"] else "")
                                 + ". The approver runs `dwh approve --by <id>` in their own terminal.")
        if project.profile_mode == "governed" and appr.get("self_approved"):
            raise PublishRefused("governed profile: the approver cannot be the builder")
        reg = str(C.get_path(project.document(), "policies.compliance") or "none").lower()
        if reg != "none":
            raise PublishRefused(f"compliance regime '{reg}': the regulated-mode controls (validation pack, "
                                 "versioned silver, retained gold, identity-bound approvals) arrive with the "
                                 "governed phase; dwh_core v1 does not release regulated data to consumers")
    doc = project.document()
    rid = run_id()
    serving = project.loc("serving")
    snap = serving / f"snap_{rid}"
    gl = ledger(project, "gold")
    with Lease(project, "dwh-publish"):
        snap.mkdir(parents=True, exist_ok=False)
        con = connect(project, read_only=False)
        tables = {}
        try:
            for t in gold.tables(doc):
                f = snap / f"{t}.parquet"
                con.execute(f'COPY (SELECT * FROM "{t}") TO {qpath(f)} (FORMAT PARQUET)')
                cols = [[r[0], r[1]] for r in con.execute(f'DESCRIBE "{t}"').fetchall()]
                rows = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                tables[t] = {"file": f.name, "rows": rows, "sha256": sha256(f), "columns": cols}
        finally:
            con.close()
        synthetic = C.read_json(project.state / "synthetic.json", None)
        manifest = {"run_id": rid, "published_at": now_iso(), "target": target, "tables": tables,
                    "spec_hash": project.spec_hash(), "approved": appr["approved"],
                    "approved_by": appr.get("approved_by"), "pending_decisions": pending,
                    "profile": project.profile_mode, "headlines": gl.get("headlines", {}),
                    "synthetic_data": bool(synthetic), "gold_verified_at": gl.get("at")}
        C.atomic_write_json(snap / "manifest.json", manifest)
        if os.environ.get("DWH_FAULT") == "before_pointer":
            raise RuntimeError("injected fault before the pointer swap (DWH_FAULT=before_pointer)")
        C.atomic_write_text(serving / "CURRENT", snap.name + "\n")
        if target == "consumers":
            C.atomic_write_text(serving / "RELEASED", snap.name + "\n")
        _prune(serving)
    if project.layout.rel("releases"):   # a small, committed record of every publish (no data)
        rec = {k: manifest[k] for k in ("run_id", "published_at", "target", "spec_hash", "approved", "approved_by",
                                        "pending_decisions", "profile", "synthetic_data", "gold_verified_at")}
        rec["snapshot"] = snap.name
        rec["tables"] = {t: {"rows": v["rows"], "sha256": v["sha256"]} for t, v in tables.items()}
        C.atomic_write_json(project.loc("releases") / f"{snap.name}.json", rec)
    audit(project, "publish", target=target, snapshot=snap.name, tables={t: v["rows"] for t, v in tables.items()})
    return manifest


def _prune(serving) -> None:
    live = {(serving / p).read_text().strip() for p in ("CURRENT", "RELEASED") if (serving / p).exists()}
    snaps = sorted((p for p in serving.glob("snap_*") if p.is_dir()), key=lambda p: p.name)
    for p in snaps[:-KEEP]:
        if p.name not in live:
            shutil.rmtree(p, ignore_errors=True)


def publish_cli(project: Project, target: str = "local") -> int:
    try:
        m = publish(project, target)
    except PublishRefused as e:
        print(f"refused: {e}")
        audit(project, "publish.refused", target=target, reason=str(e)[:400])
        return 2
    tables = ", ".join(f"{t} ({v['rows']} rows)" for t, v in m["tables"].items())
    print(f"published {tables} "
          f"→ {project.layout.rel('serving')}/CURRENT = snap_{m['run_id']}" + (" and RELEASED to consumers" if target == "consumers" else ""))
    if m["pending_decisions"]:
        print(f"note: {len(m['pending_decisions'])} ★ decision(s) pending — the dashboard shows an "
              "'unreleased' banner and consumer release is blocked (governance/debt.md).")
    return 0
