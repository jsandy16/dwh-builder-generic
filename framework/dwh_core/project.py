"""Project layout. Every path is anchored to the project root, never to the cwd.

Two layouts exist, chosen by `project.layout` in dwh-project.yaml (absent = v1):

* v1 — one file per spec namespace under config/, proofs in artefacts/, generated code in
  pipeline/generated/ (the self-contained project the dwh-init installer has always made);
* v2 — one folder per layer (bronze/ silver/ gold/ serve/), each holding specs/, decisions/,
  generated/ and reports/; sources, silver entities and metrics are ONE FILE EACH; everything
  that holds data rows (warehouse, landed files, dead letters, snapshots) lives in .dwh/.
  Made for a git repository with many pipelines (see `dwh layout migrate`).

Whatever the layout, the kernel sees the same unified document and the same provenance, so
hashes, approvals and gates do not depend on how the files are arranged on disk.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config as C

MANIFEST = "dwh-project.yaml"

# Top-level spec namespaces -> the file that stores them (layout v1). The unified "document" the
# intake engine validates is the merge of these files, so every catalogue path is
# absolute (e.g. sources.yellow.format, metrics.churn_rate.dispute_owner).
SPEC_FILES = {
    "project": MANIFEST,
    "people": "governance/people.yaml",
    "policies": "config/policies.yaml",
    "sources": "config/sources.yaml",
    "silver": "config/silver.yaml",
    "metrics": "config/metrics.yaml",
    "serve": "config/serve.yaml",
    "synthetic": "config/synthetic.yaml",
}
NAMESPACES = tuple(SPEC_FILES)
READ_ONLY_NAMESPACES = {"profile"}  # derived from data, never answered

# Which layer folder each namespace's decisions belong to (layout v2).
NS_LAYER = {"project": "project", "people": "project", "policies": "project", "sources": "bronze",
            "silver": "silver", "metrics": "gold", "serve": "serve", "synthetic": "bronze"}

# Named locations. {layer}, {name}, {entity} are filled in by Layout.path().
_LOC_V1 = {
    "provenance": "config/intake/provenance.yaml",
    "draft": "config/intake/draft.yaml",
    "analysis": ".dwh/analysis.json",
    "workbook_out": "intake",
    "workbook_archive": "config/intake/workbooks",
    "generated": "pipeline/generated",
    "report_md": "artefacts/{name}.md",
    "report_json": "artefacts/results/{name}.json",
    "bronze_profile": "artefacts/bronze-profile.md",
    "schema_drift": "artefacts/schema-drift.json",
    "metric_cards": "artefacts/metric-cards.md",
    "readback_md": "artefacts/readback-{entity}.md",
    "readback_state": ".dwh/readback",
    "dashboard_png": "artefacts/dashboard.png",
    "dead_letter": "dead_letter",
    "landed": "bronze/files",
    "serving": "serving",
    "synthetic_truth": "synthetic",
    "approvals": "governance/approvals.log",
    "debt": "governance/debt.md",
    "lineage_yaml": "governance/lineage.yaml",
    "lineage_md": "governance/lineage.md",
    "releases": "",          # v1 keeps the publish record only in serving/ (git-ignored)
    "custom": "custom",
}
_LOC_V2 = {
    "provenance": "{layer}/decisions/provenance.yaml",
    "draft": "intake/draft.yaml",
    "analysis": "intake/analysis.json",
    "workbook_out": "intake/current",
    "workbook_archive": "intake/workbooks",
    "generated": "{layer}/generated",
    "report_md": "{layer}/reports/{name}.md",
    "report_json": "{layer}/reports/{name}.json",
    "bronze_profile": "bronze/reports/bronze-profile.md",
    "schema_drift": "bronze/reports/schema-drift.json",
    "metric_cards": "gold/reports/metric-cards.md",
    "readback_md": "silver/decisions/readbacks/{entity}.md",
    "readback_state": "silver/decisions/readbacks",
    "dashboard_png": "serve/reports/dashboard.png",
    "dead_letter": ".dwh/dead_letter",
    "landed": ".dwh/landed",
    "serving": ".dwh/serving",
    "synthetic_truth": "data/synthetic",
    "approvals": "governance/approvals.log",
    "debt": "governance/debt.md",
    "lineage_yaml": "governance/lineage.yaml",
    "lineage_md": "governance/lineage.md",
    "releases": "governance/releases",
    "custom": "custom",
}
# v2: namespaces stored one item per file -> (folder, the key under the namespace that is split)
_SPLIT_V2 = {"sources": ("bronze/specs/sources", ""),
             "silver": ("silver/specs/entities", "entities"),
             "metrics": ("gold/specs/metrics", "")}
# v2: namespaces (or the rest of a split namespace) stored in one file
_FILES_V2 = {"project": MANIFEST, "people": "project/people.yaml", "policies": "project/policies.yaml",
             "silver": "silver/specs/silver.yaml", "serve": "serve/specs/serve.yaml",
             "synthetic": "data/synthetic/synthetic.yaml"}
LAYOUTS = ("v1", "v2")


class LayoutError(RuntimeError):
    pass


def _manifest_layout(root: Path) -> str:
    data = C.load_yaml(root / MANIFEST)
    proj = data.get("project", {}) if isinstance(data, dict) else {}
    lay = str((proj or {}).get("layout") or "v1").strip().lower() if isinstance(proj, dict) else "v1"
    if lay not in LAYOUTS:
        raise LayoutError(f"{MANIFEST}: project.layout '{lay}' is not one of {', '.join(LAYOUTS)}")
    return lay


class Layout:
    """Where each kind of file lives. All paths are relative to the project root."""

    def __init__(self, root: Path, version: str | None = None):
        self.root = Path(root)
        self.version = version or _manifest_layout(self.root)
        self.loc = _LOC_V2 if self.version == "v2" else _LOC_V1

    def rel(self, key: str, /, **kw: str) -> str:
        pattern = self.loc[key]
        return pattern.format(**kw) if pattern else ""

    def path(self, key: str, /, **kw: str) -> Path:
        r = self.rel(key, **kw)
        if not r:
            raise LayoutError(f"layout {self.version} has no '{key}' location")
        return self.root / r

    # ---- reports: the layer is the part of the report name before the first dash
    def report(self, name: str, kind: str = "md") -> Path:
        layer = name.split("-", 1)[0]
        layer = {"synthetic": "silver"}.get(layer, layer)   # the synthetic score grades silver
        layer = layer if layer in ("bronze", "silver", "gold", "serve") else "governance"
        return self.path("report_md" if kind == "md" else "report_json", name=name, layer=layer)

    # ---- generated code: rel is '<layer>/<file>' in every layout
    def generated(self, rel: str = "") -> Path:
        if self.version == "v1":
            return self.root.joinpath(self.loc["generated"], *([rel] if rel else []))
        layer, _, rest = rel.partition("/")
        if not layer:
            return self.root  # all layers: callers walk the layer folders
        return self.root / layer / "generated" / rest if rest else self.root / layer / "generated"

    def generated_roots(self) -> list[Path]:
        if self.version == "v1":
            return [self.root / self.loc["generated"]]
        return [self.root / lay / "generated" for lay in ("bronze", "silver", "gold", "serve")]

    # ---- provenance files
    def provenance_files(self) -> dict[str, Path]:
        """namespace -> provenance file (several namespaces may share one)."""
        if self.version == "v1":
            return {ns: self.root / self.loc["provenance"] for ns in NAMESPACES}
        return {ns: self.root / self.loc["provenance"].format(layer=NS_LAYER[ns]) for ns in NAMESPACES}

    # ---- specs
    def spec_files(self) -> list[Path]:
        """Every file that holds specs or answers (what an import scratch copy needs)."""
        out: list[Path] = []
        if self.version == "v1":
            out = [self.root / r for r in SPEC_FILES.values()]
        else:
            out = [self.root / r for r in _FILES_V2.values()]
            for folder, _ in _SPLIT_V2.values():
                d = self.root / folder
                if d.is_dir():
                    out += sorted(d.glob("*.yaml"))
        out += sorted(set(self.provenance_files().values()))
        return [p for p in dict.fromkeys(out)]

    def load_namespace(self, ns: str) -> Any:
        if self.version == "v1" or ns not in _SPLIT_V2 and ns not in _FILES_V2:
            data = C.load_yaml(self.root / SPEC_FILES[ns])
            return data.get(ns, {}) if isinstance(data, dict) else {}
        base: Any = {}
        if ns in _FILES_V2:
            data = C.load_yaml(self.root / _FILES_V2[ns])
            base = data.get(ns, {}) if isinstance(data, dict) else {}
            base = base if isinstance(base, dict) else {}
        if ns in _SPLIT_V2:
            folder, sub = _SPLIT_V2[ns]
            items: dict = {}
            d = self.root / folder
            for f in sorted(d.glob("*.yaml")) if d.is_dir() else []:
                data = C.load_yaml(f)
                if not isinstance(data, dict):
                    raise LayoutError(f"{f.relative_to(self.root)}: expected one '<name>:' block at the top")
                for k, v in data.items():
                    if k in items:
                        raise LayoutError(f"'{k}' is defined twice under {folder}/ "
                                          f"({f.name} and another file); keep one")
                    items[k] = v
            if items:
                if sub:
                    base = {**base, sub: items}
                else:
                    base = items if not base else {**base, **items}
        return base

    def save_namespace(self, ns: str, value: Any) -> None:
        if self.version == "v1" or ns not in _SPLIT_V2 and ns not in _FILES_V2:
            C.dump_yaml({ns: value}, self.root / SPEC_FILES[ns])
            return
        if ns not in _SPLIT_V2:
            C.dump_yaml({ns: value}, self.root / _FILES_V2[ns])
            return
        folder, sub = _SPLIT_V2[ns]
        value = value if isinstance(value, dict) else {}
        items = (value.get(sub) if sub else value) or {}
        items = items if isinstance(items, dict) else {}
        rest = {k: v for k, v in value.items() if k != sub} if sub else {}
        d = self.root / folder
        # every file name is decided and checked BEFORE anything is written: a refused save changes nothing.
        # Names are compared without case, because Windows and macOS file systems ignore it.
        targets: dict[str, tuple[str, Any]] = {}
        for k, v in items.items():
            name = f"{spec_file_stem(k)}.yaml"
            if name.lower() in targets:
                other = targets[name.lower()][0]
                raise LayoutError(f"{ns} items '{other}' and '{k}' would share the file {name}; rename one")
            targets[name.lower()] = (k, v)
        d.mkdir(parents=True, exist_ok=True)
        existing = {f.name.lower(): f for f in d.glob("*.yaml")}
        for low, (k, v) in targets.items():
            f = d / f"{spec_file_stem(k)}.yaml"
            old = existing.get(low)
            if old is not None and old.name != f.name:   # same item, file name differs only in case
                old.unlink()
            if not f.exists() or C.load_yaml(f) != C.to_strings({k: v}):
                C.dump_yaml({k: v}, f)
        for low, f in existing.items():
            if low not in targets and f.exists():
                f.unlink()   # the item was removed from the spec
        if sub:
            rest_file = self.root / _FILES_V2[ns]
            if rest:
                C.dump_yaml({ns: rest}, rest_file)
            elif rest_file.exists():
                rest_file.unlink()


def spec_file_stem(key: str) -> str:
    """File name (without .yaml) of one source / entity / metric in layout v2: the item's own name,
    with characters a file system may reject replaced by '_'."""
    import re
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(key)).strip(".") or "_"


class ProjectNotFound(RuntimeError):
    pass


def find_root(start: Path | None = None) -> Path:
    env = os.environ.get("DWH_PROJECT")
    if env:
        root = Path(env).resolve()
        if (root / MANIFEST).exists():
            return root
        raise ProjectNotFound(f"DWH_PROJECT={env} has no {MANIFEST}")
    cur = Path(start or Path.cwd()).resolve()
    for cand in [cur, *cur.parents]:
        if (cand / MANIFEST).exists():
            return cand
    raise ProjectNotFound(
        f"No {MANIFEST} found from {cur} upwards. Run the dwh-init skill first "
        "(python <dwh-init>/scripts/install.py --project <dir>).")


class Project:
    def __init__(self, root: Path | None = None):
        self.root = Path(root).resolve() if root else find_root()
        self.state = self.root / ".dwh"
        self.state.mkdir(exist_ok=True)
        self.layout = Layout(self.root)

    # ---- well-known locations
    def p(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def loc(self, key: str, /, **kw: str) -> Path:
        """A named location of the project's layout (see project.LAYOUTS)."""
        return self.layout.path(key, **kw)

    def rel(self, path: Path) -> str:
        """Path relative to the project root, for messages."""
        try:
            return Path(path).relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    @property
    def warehouse(self) -> Path:
        return self.state / "warehouse.duckdb"

    @property
    def provenance_file(self) -> Path:
        """v1: the single provenance file. v2: the project-level one (use load/save_provenance)."""
        return self.layout.provenance_files()["project"]

    @property
    def profile_file(self) -> Path:
        return self.state / "profile.json"

    @property
    def audit_file(self) -> Path:
        return self.state / "actions.jsonl"

    @property
    def approvals_file(self) -> Path:
        return self.loc("approvals")

    # ---- specs
    def spec_path(self, namespace: str) -> Path:
        """v1 file of a namespace (v2 namespaces may span several files: use load/save_namespace)."""
        return self.p(SPEC_FILES[namespace])

    def spec_files(self) -> list[Path]:
        return self.layout.spec_files()

    def load_namespace(self, namespace: str) -> Any:
        if namespace == "profile":
            return C.read_json(self.profile_file, {}) or {}
        return self.layout.load_namespace(namespace)

    def document(self) -> dict:
        """The unified, strings-only view of every spec plus the (read-only) profile."""
        doc = {ns: self.load_namespace(ns) for ns in SPEC_FILES}
        doc["profile"] = self.load_namespace("profile")
        return doc

    def save_namespace(self, namespace: str, value: Any) -> None:
        if namespace in READ_ONLY_NAMESPACES:
            raise PermissionError(f"'{namespace}' is derived from data and cannot be answered")
        self.layout.save_namespace(namespace, value)

    # ---- provenance (one dict keyed by answer path, stored per layer in v2)
    def load_provenance(self) -> dict:
        out: dict = {}
        for f in dict.fromkeys(self.layout.provenance_files().values()):
            data = C.load_yaml(f)
            if isinstance(data, dict):
                out.update(data)
        return out

    def save_provenance(self, prov: dict) -> None:
        files = self.layout.provenance_files()
        buckets: dict[Path, dict] = {f: {} for f in files.values()}
        for k, v in prov.items():
            ns = C.split_path(k)[0] if C.split_path(k) else "project"
            buckets[files.get(ns, files["project"])][k] = v
        for f, part in buckets.items():
            if part or f.exists():
                C.dump_yaml(part, f)

    def spec_hash(self) -> str:
        """Hash of everything a human approves: all specs + the provenance of answers."""
        payload = {ns: self.load_namespace(ns) for ns in SPEC_FILES}
        if isinstance(payload.get("project"), dict):   # where files live is not something anyone approves
            payload["project"] = {k: v for k, v in payload["project"].items() if k != "layout"}
        payload["_provenance"] = self.load_provenance()
        return C.canonical_hash(payload)

    # ---- manifest helpers
    @property
    def manifest(self) -> dict:
        return self.load_namespace("project")

    @property
    def profile_mode(self) -> str:
        return (self.manifest.get("profile") or "fast").strip().lower()

    @property
    def builder(self) -> str:
        return (self.manifest.get("builder") or "").strip()


def now_iso() -> str:
    fixed = os.environ.get("DWH_FIXED_NOW")  # deterministic runs in tests
    if fixed:
        return fixed
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def audit(project: Project, command: str, **fields: Any) -> None:
    rec = {"at": now_iso(), "command": command, "pid": os.getpid(), **fields}
    with open(project.audit_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str, sort_keys=True) + "\n")


def interpreter() -> str:
    return sys.executable
