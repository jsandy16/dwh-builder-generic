"""Where a pipeline stands in the life cycle, worked out from its files and the engine's own gates.

The stage decides what the agent is asked to do next, and where it must stop for a person.
Stages that need a person (SETUP, AWAIT_ANSWERS) are never handed to the model.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

SETUP = "setup"                 # person: write the request, add the data
DRAFT = "draft"                 # agent: analyse, draft, write the intake workbook
AWAIT_ANSWERS = "await"         # person: answer the workbook in intake/current/
IMPORT = "import"               # agent: import the answered workbook (person confirmed it is done)
REWORK = "rework"               # agent: answers incomplete or invalid -> explain, regenerate the workbook
BRONZE = "bronze"               # agent: load bronze
AFTER_LOAD = "after_load"       # agent: after-first-load workbook (read-backs, dates)
BUILD = "build"                 # agent: silver, gold, publish, dashboard check, local commit
OPERATE = "operate"             # built: free requests (new batch, questions, changes via the workbook)

PERSON_STAGES = {SETUP, AWAIT_ANSWERS}
SKILLS = ("project", "bronze", "silver", "gold", "serve")


@dataclass
class State:
    stage: str
    why: str
    workbook: Path | None = None
    facts: dict = field(default_factory=dict)


def _kernel(repo: Path):
    fw = str(repo / "framework")
    if fw not in sys.path:
        sys.path.insert(0, fw)
    import dwh_core.gold as gold
    import dwh_core.intake as intake
    from dwh_core.project import Project
    from dwh_core.runtime import ledger
    return Project, intake, gold, ledger


def request_written(pipeline: Path) -> bool:
    f = pipeline / "requirements" / "request.md"
    if not f.exists():
        return False
    text, inside = [], False
    for line in f.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("<!--"):
            inside = not s.endswith("-->")
            continue
        if inside:
            inside = not s.endswith("-->")
            continue
        if s and not s.startswith(("#", "*")):
            text.append(s)
    return len(" ".join(text)) >= 40


def raw_files(pipeline: Path) -> int:
    raw = pipeline / "data" / "raw"
    return sum(1 for f in raw.rglob("*") if f.is_file() and not f.name.startswith(".")) if raw.is_dir() else 0


def newest_workbook(pipeline: Path) -> Path | None:
    cur = pipeline / "intake" / "current"
    books = [f for f in cur.glob("*.xlsx") if not f.stem.endswith("-issues") and not f.name.startswith("~$")] \
        if cur.is_dir() else []
    return max(books, key=lambda f: f.stat().st_mtime) if books else None


def _sha16(f: Path) -> str:
    return hashlib.sha256(f.read_bytes()).hexdigest()[:16]


def detect(repo: Path, pipeline: Path) -> State:
    repo, pipeline = Path(repo).resolve(), Path(pipeline).resolve()
    facts = {"request_written": request_written(pipeline), "raw_files": raw_files(pipeline)}
    if not facts["request_written"] or not facts["raw_files"]:
        missing = [m for m, ok in (("the request (requirements/request.md)", facts["request_written"]),
                                   ("the source files (data/raw/)", facts["raw_files"])) if not ok]
        return State(SETUP, "waiting for " + " and ".join(missing), facts=facts)
    Project, intake, gold, ledger = _kernel(repo)
    project = Project(pipeline)
    prov = project.load_provenance()
    wb = newest_workbook(pipeline)
    imported = bool(wb) and _sha16(wb) in {str(r.get("workbook_sha256", ""))[:16] for r in prov.values()
                                           if isinstance(r, dict)}
    facts.update(answers=len(prov), workbook=str(wb.relative_to(pipeline)) if wb else None, workbook_imported=imported)
    waiting = bool(wb) and not imported
    if not prov:
        if waiting:
            return State(AWAIT_ANSWERS, "the intake workbook is with the owners", wb, facts)
        return State(DRAFT, "no answers recorded yet", facts=facts)
    blocked = [s for s in SKILLS if not intake.check(project, s, "A").ok]
    facts["gate_a_blocked"] = blocked
    if blocked:
        if waiting:
            return State(AWAIT_ANSWERS, "a workbook is with the owners", wb, facts)
        return State(REWORK, f"answers missing or invalid for {', '.join(blocked)}", facts=facts)
    if not ledger(project, "bronze"):
        return State(BRONZE, "answers recorded; nothing loaded yet", facts=facts)
    if not intake.check(project, "silver", "B").ok:
        if waiting:
            return State(AWAIT_ANSWERS, "the after-first-load workbook is with the owners", wb, facts)
        return State(AFTER_LOAD, "bronze loaded; questions only the loaded data can raise", facts=facts)
    current, why = gold.is_current(project)
    serving = project.loc("serving") / "CURRENT"
    gl = ledger(project, "gold")
    published = False
    if serving.exists():
        import json
        mf = serving.parent / serving.read_text(encoding="utf-8").strip() / "manifest.json"
        published = mf.exists() and json.loads(mf.read_text(encoding="utf-8")).get("gold_verified_at") == gl.get("at")
    facts.update(gold_current=current, published=published)
    if not current or not published:
        return State(BUILD, why if not current else "gold verified but not published yet", facts=facts)
    if waiting:
        return State(AWAIT_ANSWERS, "a workbook with changes is with the owners", wb, facts)
    return State(OPERATE, "built, verified and published", facts=facts)
