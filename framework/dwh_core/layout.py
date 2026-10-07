"""`dwh layout show | migrate --to v2`: move a project from the v1 layout to the v2 layout.

v2 keeps one folder per layer (specs/, decisions/, generated/, reports/), one spec file per
source, silver entity and metric, and every file holding data rows under .dwh/ — the shape a
git repository of many pipelines wants (see project.py for the full map).

The migration is content-preserving and checked: the unified document and the provenance
are read back from the new files and compared with the old ones before anything is removed,
so approvals, answers and gates stay exactly as they were. Nothing it cannot place is
deleted; what it leaves alone is listed.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import VERSION
from . import config as C
from .project import (_LOC_V1, MANIFEST, NAMESPACES, SPEC_FILES, Layout, LayoutError, Project, audit)

GITIGNORE_V2 = """# dwh (layout v2): data rows, local state and machine-specific files stay out of git
.dwh/
data/raw/
intake/current/
dwh
dwh.cmd
__pycache__/
*.pyc
"""


def show(project: Project) -> str:
    lay = project.layout
    lines = [f"layout {lay.version} — {project.root}", ""]
    for name in sorted(lay.loc):
        rel = lay.loc[name]
        lines.append(f"  {name:<17} {rel or '(none)'}")
    lines.append("")
    lines.append("spec files:")
    lines += [f"  {project.rel(p)}" for p in lay.spec_files() if p.exists()]
    return "\n".join(lines)


def _move(src: Path, dst: Path, moved: list, root: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in list(src.iterdir()):
            _move(child, dst / child.name, moved, root)
        try:
            src.rmdir()
        except OSError:
            pass
        return
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))
    moved.append((src.relative_to(root).as_posix(), dst.relative_to(root).as_posix()))


def _prune_empty(path: Path) -> None:
    if not path.is_dir():
        return
    for child in sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if child.is_dir():
            try:
                child.rmdir()
            except OSError:
                pass
    try:
        path.rmdir()
    except OSError:
        pass


def migrate(project: Project, to: str = "v2", dry_run: bool = False) -> dict:
    if to != "v2":
        raise LayoutError("only v1 → v2 is supported")
    if project.layout.version == "v2":
        return {"already": True, "moved": [], "left": []}
    root = project.root
    old = Layout(root, "v1")
    new = Layout(root, "v2")

    # 1. read everything through the old layout
    doc = {ns: old.load_namespace(ns) for ns in NAMESPACES}
    prov = project.load_provenance()
    before = _content_hash(doc, prov)

    plan = [(project.rel(root / SPEC_FILES[ns]), "→ v2 spec files") for ns in NAMESPACES
            if (root / SPEC_FILES[ns]).exists() and ns != "project"]
    if dry_run:
        return {"dry_run": True, "plan": plan}

    # The steps run so that a failure anywhere leaves a v1 project that still works (the manifest
    # says v1 and the v1 spec files are still there) and the same command can simply be run again:
    # writes are idempotent and moves skip what has already moved. The manifest switches LAST.

    # 2. write specs and provenance through the new layout, then read them back and compare
    written = []
    for ns in NAMESPACES:
        if ns == "project":
            continue
        if doc[ns] or (root / SPEC_FILES[ns]).exists():
            new.save_namespace(ns, doc[ns])
    files = new.provenance_files()
    buckets: dict[Path, dict] = {}
    for k, v in prov.items():
        ns = C.split_path(k)[0] if C.split_path(k) else "project"
        buckets.setdefault(files.get(ns, files["project"]), {})[k] = v
    for f, part in buckets.items():
        C.dump_yaml(part, f)
        written.append(project.rel(f))
    doc2 = {ns: new.load_namespace(ns) for ns in NAMESPACES}
    prov2: dict = {}
    for f in dict.fromkeys(files.values()):
        d = C.load_yaml(f)
        if isinstance(d, dict):
            prov2.update(d)
    if _content_hash(doc2, prov2) != before:
        written += [project.rel(p) for p in new.spec_files() if p.exists() and p.name != MANIFEST]
        raise LayoutError("the specs read back from the v2 files differ from the originals. Nothing was moved or "
                          "removed and the project still runs on v1. The v2 spec files written so far can be "
                          "deleted: " + ", ".join(sorted(set(written)))[:1500])

    # 3. move everything else to its v2 place
    moved: list = []
    _move(root / _LOC_V1["draft"], new.path("draft"), moved, root)
    _move(root / _LOC_V1["analysis"], new.path("analysis"), moved, root)
    _move(root / _LOC_V1["workbook_archive"], new.path("workbook_archive"), moved, root)
    old_out = root / _LOC_V1["workbook_out"]
    if old_out.is_dir():   # workbooks written to intake/ before: kept with the archive
        for f in sorted(old_out.glob("*.xlsx")):
            _move(f, new.path("workbook_archive") / f"pre-migration-{f.name}", moved, root)
    for lay in ("silver", "gold", "serve", "bronze"):
        _move(root / _LOC_V1["generated"] / lay, new.generated(lay), moved, root)
    res_dir = root / "artefacts" / "results"
    for f in sorted(res_dir.glob("*.json")) if res_dir.is_dir() else []:
        _move(f, new.report(f.stem, "json"), moved, root)
    art = root / "artefacts"
    for f in sorted(art.glob("readback-*.md")) if art.is_dir() else []:
        _move(f, new.path("readback_md", entity=f.stem[len("readback-"):]), moved, root)
    for name in ("bronze_profile", "schema_drift", "metric_cards", "dashboard_png"):
        _move(root / _LOC_V1[name], new.path(name), moved, root)
    for f in sorted(art.glob("*.md")) if art.is_dir() else []:
        _move(f, new.report(f.stem, "md"), moved, root)
    _move(root / _LOC_V1["readback_state"], new.path("readback_state"), moved, root)
    _move(root / _LOC_V1["dead_letter"], new.path("dead_letter"), moved, root)
    _move(root / _LOC_V1["synthetic_truth"], new.path("synthetic_truth"), moved, root)
    _move(root / _LOC_V1["landed"], new.path("landed"), moved, root)
    _move(root / _LOC_V1["serving"], new.path("serving"), moved, root)
    for d in ("artefacts", "pipeline", "bronze/files"):
        _prune_empty(root / d)

    # 4. publish records for snapshots that already exist (small JSON, no data)
    serving = new.path("serving")
    for mf in sorted(serving.glob("snap_*/manifest.json")) if serving.is_dir() else []:
        m = C.read_json(mf, {}) or {}
        rec = {k: m.get(k) for k in ("run_id", "published_at", "target", "spec_hash", "approved", "approved_by",
                                    "pending_decisions", "profile", "synthetic_data", "gold_verified_at")}
        rec["snapshot"] = mf.parent.name
        rec["tables"] = {t: {"rows": v.get("rows"), "sha256": v.get("sha256")}
                         for t, v in (m.get("tables") or {}).items()}
        C.atomic_write_json(new.path("releases") / f"{mf.parent.name}.json", rec)

    # 5. bronze views over landed parquet point at absolute folders: repoint them (also on a re-run)
    landed = new.path("landed")
    if landed.is_dir() and (root / ".dwh" / "warehouse.duckdb").exists():
        import duckdb
        con = duckdb.connect(str(root / ".dwh" / "warehouse.duckdb"))
        try:
            for d in sorted(landed.iterdir()):
                if d.is_dir() and any(d.glob("*.parquet")):
                    glob = (d.as_posix() + "/*.parquet").replace("'", "''")
                    con.execute(f'CREATE OR REPLACE VIEW "bronze_{d.name}" AS SELECT * FROM '
                                f"read_parquet('{glob}', union_by_name=true)")
        finally:
            con.close()

    # 6. .gitignore: add the v2 lines that are missing, keep everything the user had
    gi = root / ".gitignore"
    have = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    add = [ln for ln in GITIGNORE_V2.splitlines() if ln and not ln.startswith("#") and ln not in have]
    if add or not gi.exists():
        C.atomic_write_text(gi, "\n".join(have + ([""] if have else []) + GITIGNORE_V2.splitlines()[:1] + add) + "\n")

    # 7. remove the old spec / provenance files (their content now lives in the v2 files) …
    for ns in NAMESPACES:
        if ns != "project":
            (root / SPEC_FILES[ns]).unlink(missing_ok=True)
    (root / _LOC_V1["provenance"]).unlink(missing_ok=True)
    _prune_empty(root / "config")

    # 8. … and only now switch the manifest (layout and the kernel now running)
    proj = dict(doc["project"] or {})
    old_version = proj.get("dwh_core_version", "")
    proj["layout"] = "v2"
    proj["dwh_core_version"] = VERSION
    C.dump_yaml({"project": proj}, root / MANIFEST)

    # 9. re-render generated code for the new places (e.g. where the dashboard finds snapshots)
    regenerated = ""
    if moved and any(new.generated_roots()[i].exists() for i in range(4)):
        try:
            from . import generate
            generate.render_layer(Project(root), "all")
            regenerated = "yes"
        except Exception as e:   # incomplete specs: rendered later by the next build
            regenerated = f"not yet ({type(e).__name__}: {str(e)[:120]}) — run `dwh generate`"

    left = sorted(p.name for p in root.iterdir()
                  if p.name not in {".dwh", ".gitignore", MANIFEST, "dwh", "dwh.cmd", "dwh_core", "project", "bronze",
                                    "silver", "gold", "serve", "intake", "governance", "data", "custom",
                                    "README.md", "requirements.txt", "requirements"})
    audit(project, "layout.migrate", to="v2", moved=len(moved), kernel_from=old_version, kernel_to=VERSION)
    return {"moved": moved, "left": left, "kernel_from": old_version, "kernel_to": VERSION,
            "regenerated": regenerated}


def _drop_empty(x):
    """Empty dicts / lists / strings carry no answer: v1 and v2 may store them differently."""
    if isinstance(x, dict):
        out = {k: _drop_empty(v) for k, v in x.items()}
        return {k: v for k, v in out.items() if v not in ({}, [], "", None)}
    if isinstance(x, list):
        return [_drop_empty(v) for v in x]
    return x


def _content_hash(doc: dict, prov: dict) -> str:
    return C.canonical_hash({"doc": _drop_empty({k: v for k, v in doc.items() if k != "project"}), "prov": prov})


def cli(project: Project, action: str, to: str = "v2", dry_run: bool = False) -> int:
    if action == "show":
        print(show(project))
        return 0
    res = migrate(project, to, dry_run)
    if res.get("already"):
        print("already on layout v2")
        return 0
    if res.get("dry_run"):
        print("would move these specs to one-file-per-item v2 files (nothing changed):")
        for a, b in res["plan"]:
            print(f"  {a} {b}")
        return 0
    print(f"migrated to layout v2: {len(res['moved'])} file(s) moved; specs and answers read back identical.")
    if res["kernel_from"] != res["kernel_to"]:
        print(f"dwh_core_version {res['kernel_from'] or '?'} → {res['kernel_to']} in {MANIFEST} "
              "(an approval given before this is stale: approve again).")
    if res["left"]:
        print("left in place (not part of the kernel layout): " + ", ".join(res["left"]))
    if res.get("regenerated") and res["regenerated"] != "yes":
        print(f"generated code: {res['regenerated']}")
    print("next: `dwh intake check all`, then rebuild (`dwh build silver --rebuild`, `dwh build gold`).")
    return 0
