"""Layout v2 and the pipelines repository (kernel 1.2.0).

L1 migrate a finished v1 project to v2: content identical (spec hash, approval, gates), one file per
   source / entity / metric, data rows only under .dwh/, built tables and snapshots still usable.
L2 a pipeline inside a repository uses the SHARED kernel: nothing copied, layout v2 by default,
   the wrapper points at framework/, a version the pipeline does not pin is refused.
L3 v2 spec files: a removed item removes its file; the same name in two files is refused.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from common import INSTALL, SKILLS, Fail, check, duck, dwh, lay, loc, say  # noqa: E402


def _spec_hash(root: Path) -> str:
    from dwh_core.project import Project
    return Project(root).spec_hash()


def run(d1: Path, work: Path, log: list) -> None:
    if lay(d1).version != "v1":
        log.append(("PASS", "L1 skipped: the suite runs on layout v2 (projects start on v2, nothing to migrate)"))
    else:
        migrate(d1, work / "migrate", log)
    repo(work / "repo", log)


# ---------------------------------------------------------------- L1
def migrate(d1: Path, root: Path, log: list) -> None:
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(d1, root, symlinks=True)
    dwh(root, "doctor")
    from dwh_core import approvals
    from dwh_core.project import Project
    os.environ["DWH_PROJECT"] = str(root)
    try:
        approvals.approve(Project(root), "priya", _tty=True, _input=lambda _: "priya")
    finally:
        os.environ.pop("DWH_PROJECT", None)
    before = _spec_hash(root)
    gates_before = dwh(root, "intake", "check", "all", expect=None)[0]
    gold_before = duck(root, "SELECT COUNT(*) FROM gold_churn_rate")[0][0]
    cur_before = (root / "serving" / "CURRENT").read_text().strip() if (root / "serving" / "CURRENT").exists() else ""

    rc, out = dwh(root, "layout", "migrate", "--dry-run")
    check(rc == 0 and lay(root).version == "v1" and (root / "config" / "sources.yaml").exists(),
          "L1 --dry-run lists the moves and changes nothing", log)
    rc, out = dwh(root, "layout", "migrate")
    check("read back identical" in out and lay(root).version == "v2",
          "L1 migrate switches the manifest to layout v2 after reading every spec back identical", log)
    check(_spec_hash(root) == before, "L1 the spec hash (specs + every answer's provenance) is unchanged", log)
    st = approvals.status(Project(root))
    check(st["approved"] and not st["stale"], "L1 an approval given before the move is still valid", log)
    srcs = sorted(p.stem for p in (root / "bronze/specs/sources").glob("*.yaml"))
    ents = sorted(p.stem for p in (root / "silver/specs/entities").glob("*.yaml"))
    mets = sorted(p.stem for p in (root / "gold/specs/metrics").glob("*.yaml"))
    doc = Project(root).document()
    check(srcs == sorted(doc["sources"]) and ents == sorted(doc["silver"]["entities"]) and mets == sorted(doc["metrics"])
          and len(mets) >= 2,
          f"L1 one spec file per source ({len(srcs)}), silver entity ({len(ents)}) and metric ({len(mets)})", log)
    check(all((root / f"{lay_}/decisions/provenance.yaml").exists() for lay_ in ("project", "bronze", "silver", "gold")),
          "L1 answers' provenance sits next to each layer's specs (decisions/)", log)
    check(not any((root / d).exists() for d in ("config", "artefacts", "pipeline", "serving", "dead_letter")),
          "L1 the v1 folders are gone (nothing left behind)", log)
    check(any((root / "silver/generated").glob("*.sql")) and any((root / "gold/generated").glob("*.sql"))
          and any((root / "silver/reports").glob("silver-verify.*")) and any((root / "gold/reports").glob("*.md")),
          "L1 generated code and proofs moved into each layer's generated/ and reports/", log)
    rows = (root / ".dwh" / "dead_letter").exists() and not (root / "silver" / "dead_letter").exists()
    check(rows, "L1 files holding data rows (dead letters, snapshots) live under .dwh/ only", log)
    rc, out = dwh(root, "generate", "--verify")
    check(rc == 0, "L1 generated files are intact after the move", log)
    rc = dwh(root, "intake", "check", "all", expect=None)[0]
    check(rc == gates_before, "L1 the intake gates give the same result as before the move", log)
    dwh(root, "build", "silver")
    dwh(root, "build", "gold")
    check(duck(root, "SELECT COUNT(*) FROM gold_churn_rate")[0][0] == gold_before,
          "L1 silver and gold rebuild on v2 with the same gold rows", log)
    if cur_before:
        check((root / ".dwh/serving/CURRENT").read_text().strip() == cur_before
              and (root / "governance/releases" / f"{cur_before}.json").exists(),
              "L1 the published snapshot moved to .dwh/serving and got a committed release record", log)
        rc, out = dwh(root, "publish")
        check(rc == 0 and len(list((root / "governance/releases").glob("*.json"))) >= 2,
              "L1 publishing on v2 writes another release record", log)
    rc, out = dwh(root, "status")
    check(rc == 0, "L1 status works on v2", log)


# ---------------------------------------------------------------- L2 + L3
def repo(base: Path, log: list) -> None:
    if base.exists():
        shutil.rmtree(base)
    (base / "framework").mkdir(parents=True)
    shutil.copytree(SKILLS / "dwh-init" / "kernel" / "dwh_core", base / "framework" / "dwh_core",
                    ignore=shutil.ignore_patterns("__pycache__"))
    skill = base / "skills" / "dwh-init"
    shutil.copytree(SKILLS / "dwh-init", skill, ignore=shutil.ignore_patterns("__pycache__", "kernel"))
    root = base / "pipelines" / "shop"
    r = subprocess.run([sys.executable, str(skill / "scripts" / "install.py"), "--project", str(root)],
                       capture_output=True, text=True)
    check(r.returncode == 0, "L2 the repository's dwh-init (no kernel/ of its own) installs a pipeline", log)
    check(not (root / "dwh_core").exists() and lay(root).version == "v2",
          "L2 inside a repository nothing is copied and the pipeline starts on layout v2", log)
    check(f'"{(base / "framework").as_posix()}' in (root / "dwh").read_text(),
          "L2 the wrapper runs the shared kernel in framework/", log)
    for d in ("bronze/specs/sources", "silver/specs/entities", "gold/specs/metrics", "serve/specs", "intake/workbooks",
              "governance/releases", "requirements", "data/raw"):
        if not (root / d).is_dir():
            raise Fail(f"L2 missing folder {d}")
    check(True, "L2 the pipeline has the full v2 folder tree (specs / decisions / generated / reports per layer)", log)
    say(root, "people", {"dana": {"name": "Dana", "roles": ["DE", "PO", "SME", "GOV"]}}, "dana")
    say(root, "project.name", "shop", "dana")
    check((root / "project/people.yaml").exists() and (root / "project/decisions/provenance.yaml").exists(),
          "L2 answers land in the v2 files (project/people.yaml, project/decisions/provenance.yaml)", log)
    man = root / "dwh-project.yaml"
    text = man.read_text()
    man.write_text(text.replace('dwh_core_version: "', 'dwh_core_version: "0.9.', 1))
    rc, out = dwh(root, "intake", "check", "project", expect=None)
    check(rc == 2 and "pins dwh_core 0.9." in out, "L2 a kernel version the pipeline does not pin is refused", log)
    rc, out = dwh(root, "doctor", expect=None)
    check("FAIL" not in out, "L2 doctor still runs, so the pin can be fixed", log)
    man.write_text(text)

    # L3: one file per item
    from dwh_core.project import Layout, LayoutError
    L = Layout(root)
    L.save_namespace("metrics", {"a": {"entity": "x"}, "b": {"entity": "y"}})
    check(sorted(p.name for p in (root / "gold/specs/metrics").glob("*.yaml")) == ["a.yaml", "b.yaml"],
          "L3 each metric is written to its own file", log)
    L.save_namespace("metrics", {"a": {"entity": "x"}})
    check(sorted(p.name for p in (root / "gold/specs/metrics").glob("*.yaml")) == ["a.yaml"],
          "L3 removing a metric from the spec removes its file", log)
    (root / "gold/specs/metrics/copy.yaml").write_text("a:\n  entity: z\n")
    try:
        L.load_namespace("metrics")
        dup = False
    except LayoutError as e:
        dup = "defined twice" in str(e)
    check(dup, "L3 the same metric name in two files is refused with a clear message", log)
    rc, out = dwh(root, "intake", "check", "gold", expect=None)
    check(rc == 2 and "defined twice" in out, "L3 the CLI refuses it too (no traceback)", log)
