"""Intake engine: record answers with provenance, and gate every build on them.

The rule this enforces (the user's requirement):
  * every input a step needs is collected BEFORE that step builds;
  * NA (whole answer) / blank mean "not applicable" — accepted for optional fields only;
  * mandatory specs such as the schema can never be NA;
  * human-owned (M*) answers are never defaulted, inferred, or recorded as the agent.

`check` is deterministic: the build commands refuse to run unless it returns no errors.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from . import AGENT_IDS
from . import catalogue as K
from . import config as C
from .project import Project, audit, now_iso


class IntakeError(ValueError):
    pass


# ---------------------------------------------------------------- provenance store
def load_provenance(project: Project) -> dict:
    return project.load_provenance()


def save_provenance(project: Project, prov: dict) -> None:
    project.save_provenance(prov)


def people(project: Project) -> dict:
    return project.load_namespace("people") or {}


def roles_of(project: Project, person: str) -> set[str]:
    rec = people(project).get(person)
    if not isinstance(rec, dict):
        return set()
    return {r.strip().upper() for r in C.as_list(rec.get("roles"))}


def _check_person(project: Project, f: K.Field, by: str) -> None:
    if not by:
        raise IntakeError(f"{f.path} is human-owned ({f.owner}); record it with --by <person id>.")
    if by.strip().lower() in AGENT_IDS:
        raise IntakeError(f"{f.path} is human-owned; the agent cannot be its author. "
                          f"Ask the {f.owner} owner and record their answer with --by <their id>.")
    if f.owner not in roles_of(project, by):
        raise IntakeError(f"'{by}' does not hold role {f.owner} in the people list, "
                          f"so cannot answer {f.path}. Mark it pending for the right owner instead.")


# ---------------------------------------------------------------- answering
def set_answer(project: Project, path: str, value: Any, by: str = "", source: str = "chat",
               quote: str = "", reason: str = "", drafted: bool = False) -> str:
    """Record one answer (a value or a whole YAML subtree) with provenance.

    Every catalogue field at or below `path` is checked: tokens (NA / none / default / infer)
    are resolved per field, and each human-owned (★) field present in the answer must be
    given by a listed person holding that field's owner role.
    """
    ns = C.split_path(path)[0]
    if ns not in project.document() or ns in {"profile"}:
        raise IntakeError(f"'{ns}' is not an answerable namespace")
    f, caps = K.find_field(path)
    subtree = K.descendant_fields(path)
    if f is None and not subtree:
        raise IntakeError(f"unknown intake field '{path}'. Run `dwh intake show <skill>` "
                          "for the valid paths.")
    prov = load_provenance(project)
    state = "answered"

    if f is not None:
        if _is_choice(f, value):
            pass  # the token is one of the field's own choices (e.g. compliance: none)
        elif C.is_token(value, C.NA_TOKEN):
            state = "na"
        elif C.is_token(value, C.NONE_TOKEN):
            state = "none"
        elif C.is_token(value, C.DEFAULT_TOKEN):
            if f.human_owned:
                raise IntakeError(f"{path} is human-owned (★); it has no default. Ask the {f.owner} owner.")
            if f.default is None:
                raise IntakeError(f"{path} has no documented default; a value is needed.")
            value, state = f.default, "default"
        elif C.is_token(value, C.INFER_TOKEN):
            if f.human_owned or not f.allow_infer:
                raise IntakeError(f"{path} cannot be inferred; it needs an explicit answer.")
            state = "inferred"
        if f.human_owned:
            _check_person(project, f, by)  # even "not applicable" is the owner's call

    resolved_defaults: set[str] = set()
    sub_paths: list[tuple[str, K.Field]] = []
    if subtree and isinstance(value, (dict, list)):
        tmp: dict = {}
        C.set_path(tmp, path, value)
        for d in subtree:
            for cp, _ in K.expand(d.path, tmp):
                if not (cp.startswith(path + ".")):
                    continue
                v = C.get_path(tmp, cp)
                if C.is_blank(v):
                    continue
                sub_paths.append((cp, d))
                if d.human_owned:
                    _check_person(project, d, by)
                if C.is_token(v, C.DEFAULT_TOKEN) and not _is_choice(d, v):
                    if d.human_owned or d.default is None:
                        raise IntakeError(f"{cp} has no default{' (it is human-owned ★)' if d.human_owned else ''}; "
                                          "a value is needed.")
                    C.set_path(tmp, cp, d.default)
                    resolved_defaults.add(cp)
                elif C.is_token(v, C.INFER_TOKEN) and (d.human_owned or not d.allow_infer):
                    raise IntakeError(f"{cp} cannot be inferred; it needs an explicit answer.")
        value = C.get_path(tmp, path)

    if drafted:
        if (f is not None and f.human_owned) or any(d.human_owned for _, d in sub_paths):
            raise IntakeError(f"{path} contains a human-owned (★) answer; ★ answers are never drafted — ask the owner.")
        if not by:
            raise IntakeError("a drafted value needs --by <the person who must confirm it>")
    data = project.load_namespace(ns)
    if not isinstance(data, dict):
        data = {}
    rel = ".".join(C.split_path(path)[1:])
    if rel:
        C.set_path(data, rel, value)
    else:
        data = value
    project.save_namespace(ns, data)

    stamp = {"by": by or project.builder or "unknown", "source": source, "at": now_iso()}
    if drafted:
        stamp["drafted"] = "assistant"
    if quote:
        stamp["quote"] = quote[:500]
    if reason:
        stamp["reason"] = reason[:500]
    # a new answer for a subtree replaces the old provenance below it
    for old in [k for k in prov if k.startswith(path + ".")]:
        prov.pop(old)
    if f is not None:
        prov[path] = {**stamp, "state": "drafted" if drafted and state in ("answered", "default") else state,
                      "value_hash": C.canonical_hash(value)}
    doc = project.document()
    for cp, d in sub_paths:
        v = C.get_path(doc, cp)
        st = "na" if C.is_token(v, C.NA_TOKEN) and not _is_choice(d, v) else \
            "none" if C.is_token(v, C.NONE_TOKEN) and not _is_choice(d, v) else \
            "inferred" if C.is_token(v, C.INFER_TOKEN) else \
            "default" if cp in resolved_defaults else "answered"
        if drafted and st in ("answered", "default"):
            st = "drafted"
        prov[cp] = {**stamp, "state": st, "value_hash": C.canonical_hash(v)}
    save_provenance(project, prov)
    audit(project, "intake.set", path=path, by=by, source=source, state="drafted" if drafted else state)
    return "drafted" if drafted else state


def infer_schema(project: Project, source: str, sample: str, by: str) -> dict:
    """Propose sources.<source>.schema.columns from a sample file. The proposal is recorded as
    INFERRED: nothing builds until a DE confirms it (`dwh intake confirm …`). Types only —
    yes/no-looking columns stay VARCHAR (never BOOLEAN), classification is never inferred."""
    import duckdb
    from pathlib import Path
    spec = C.get_path(project.document(), f"sources.{source}") or {}
    if not spec:
        raise IntakeError(f"describe source '{source}' (format, dialect) before inferring its schema")
    path = Path(sample) if Path(sample).is_absolute() else project.root / sample
    if not path.exists():
        raise IntakeError(f"sample file not found: {sample}")
    fmt = str(spec.get("format", "")).lower()
    con = duckdb.connect()
    try:
        if fmt == "parquet":
            desc = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
        elif fmt == "csv":
            c = spec.get("csv") or {}
            desc = con.execute(
                "DESCRIBE SELECT * FROM read_csv(?, delim=?, header=?, sample_size=20000)",
                [str(path), c.get("delimiter", ","), C.as_bool(c.get("header", "yes"))]).fetchall()
        elif fmt in ("json", "jsonl"):
            desc = con.execute("DESCRIBE SELECT * FROM read_json_auto(?)", [str(path)]).fetchall()
        else:
            raise IntakeError(f"schema inference supports csv, parquet and json, not {fmt}")
    finally:
        con.close()
    keep = ("BIGINT", "INTEGER", "DOUBLE", "DATE", "TIMESTAMP", "VARCHAR", "SMALLINT", "TINYINT", "FLOAT")
    cols = {}
    for name, typ, *_ in desc:
        t = str(typ).upper()
        base = t.split("(")[0]
        if base.startswith("DECIMAL"):
            proposal = t
        elif base in keep:
            proposal = base
        elif base.startswith("TIMESTAMP"):
            proposal = "TIMESTAMP"
        else:
            proposal = "VARCHAR"  # BOOLEAN from Y/N, TIME, lists … stay text: decided in silver, not guessed here
        cols[name] = {"type": proposal, "required": "yes", "key": "no"}
    set_answer(project, f"sources.{source}.schema.columns", "infer", by=by)
    data = project.load_namespace("sources")
    C.set_path(data, f"{source}.schema.columns", cols)
    project.save_namespace("sources", data)
    prov = load_provenance(project)
    prov[f"sources.{source}.schema.columns"] = {"by": by, "source": "file", "at": now_iso(), "state": "inferred",
                                                "sample": str(sample), "value_hash": C.canonical_hash(cols)}
    save_provenance(project, prov)
    audit(project, "intake.infer", source=source, sample=str(sample), columns=len(cols))
    return cols


def mark_pending(project: Project, path: str, owner: str, due: str = "") -> None:
    f, _ = K.find_field(path)
    if f is None or not f.human_owned:
        raise IntakeError("only human-owned (★) fields can be pending; other fields need an answer now.")
    if not f.pending_ok:
        raise IntakeError(f"{path} is needed to build, so it cannot wait — ask the {f.owner} owner for it now.")
    if f.owner not in roles_of(project, owner):
        raise IntakeError(f"'{owner}' does not hold role {f.owner}.")
    prov = load_provenance(project)
    prov[path] = {"state": "pending", "owner": owner, "due": due, "at": now_iso()}
    save_provenance(project, prov)
    audit(project, "intake.pending", path=path, owner=owner, due=due)


def confirm(project: Project, path: str, by: str) -> None:
    """A person confirms an inferred or assistant-drafted value (and everything drafted below it)."""
    prov = load_provenance(project)
    targets = [k for k, r in prov.items() if (k == path or k.startswith(path + "."))
               and isinstance(r, dict) and r.get("state") in ("inferred", "drafted")]
    if not targets:
        raise IntakeError(f"{path} is not awaiting confirmation")
    if not by or by.strip().lower() in AGENT_IDS:
        raise IntakeError("a value must be confirmed by a person, not the assistant")
    doc = project.document()
    for k in targets:
        f, _ = K.find_field(k)
        if f is not None and f.owner not in roles_of(project, by) and prov[k].get("by") != by:
            raise IntakeError(f"'{by}' neither holds role {f.owner} nor is the person {k} was drafted for")
        v = C.get_path(doc, k)
        prov[k].update({"state": "confirmed", "confirmed_by": by, "at": now_iso(), "value_hash": C.canonical_hash(v)})
    save_provenance(project, prov)
    audit(project, "intake.confirm", path=path, by=by, fields=len(targets))


# ---------------------------------------------------------------- checking
@dataclass
class Issue:
    path: str
    level: str
    owner: str
    problem: str
    fix: str = ""


@dataclass
class Report:
    skill: str
    gate: str
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    not_applicable: list[Issue] = field(default_factory=list)
    checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = [f"## Intake check — {self.skill}, gate {self.gate}: "
                 f"{'PASS' if self.ok else 'BLOCKED'} ({self.checked} fields checked)"]
        for title, items in (("Blocking", self.errors), ("Warnings", self.warnings),
                             ("Not applicable (recorded)", self.not_applicable)):
            if items:
                lines.append(f"\n**{title}**")
                for i in items:
                    fix = f" → {i.fix}" if i.fix else ""
                    lines.append(f"- `{i.path}` [{i.level}, {i.owner}] {i.problem}{fix}")
        return "\n".join(lines)


def _is_choice(f: K.Field, v: Any) -> bool:
    return f.type == "enum" and isinstance(v, str) and v.strip().lower() in {c.lower() for c in f.choices}


def _value_kind(v: Any) -> str:
    if C.is_blank(v):
        return "blank"
    if C.is_token(v, C.NA_TOKEN):
        return "na"
    if C.is_token(v, C.NONE_TOKEN):
        return "none"
    if C.is_token(v, C.INFER_TOKEN):
        return "infer"
    if C.is_token(v, C.DEFAULT_TOKEN):
        return "default"
    return "value"


def check(project: Project, skill: str, gate: str = "A", unattended: bool = False) -> Report:
    from . import validators as V  # local import: validators use sqlfrag/duckdb

    cat = K.load(skill)
    doc = project.document()
    prov = load_provenance(project)
    mode = project.profile_mode
    strict = unattended or mode == "governed"
    gates = {"A"} if gate == "A" else {"A", "B"}
    rep = Report(skill=skill, gate=gate)

    for f in cat.fields:
        if f.gate not in gates:
            continue
        if f.profiles and mode not in {p.lower() for p in f.profiles}:
            continue
        for path, caps in K.expand(f.path, doc):
            rep.checked += 1
            required = f.level in ("M", "M*") or (
                f.level in ("C", "C*") and K.eval_condition(f.condition, doc, caps))
            if f.level in ("C", "C*") and not required:
                continue
            v = C.get_path(doc, path)
            kind = _value_kind(v)
            if kind in ("none", "na") and _is_choice(f, v):
                kind = "value"  # e.g. compliance: none, egress: none — a real choice, not a token
            rec = prov.get(path, {})
            st = rec.get("state")
            issue = lambda problem, fix="": Issue(path, f.label, f.owner, problem, fix)

            if st == "conflict":
                rep.errors.append(issue("conflicting answers recorded", "the owner must resolve it"))
                continue
            if st == "pending":
                msg = f"pending — waiting for {rec.get('owner')}" + (f" (due {rec['due']})" if rec.get("due") else "")
                if strict or not f.pending_ok:
                    rep.errors.append(issue(msg, "unattended/governed runs need every ★ answer"))
                else:
                    rep.warnings.append(issue(msg + "; build may continue, publishing to consumers is blocked"))
                continue

            if kind == "blank":
                if required:
                    fix = "answer 'none' if there are none" if f.none_only else (f.prompt or "provide a value")
                    rep.errors.append(issue("missing", fix))
                elif f.consequence:
                    rep.not_applicable.append(issue(f"blank → {f.consequence}"))
                continue
            if kind == "na":
                if required:
                    why = f.why or "this input is required for a correct build"
                    extra = " (answer 'none' if there are none)" if f.none_only else ""
                    rep.errors.append(issue(f"NA is not allowed — {why}{extra}"))
                else:
                    if f.human_owned or f.level == "C*":
                        _attest(project, f, path, v, rec, rep, issue)
                    rep.not_applicable.append(issue(f"NA → {f.consequence or 'not applicable'}"))
                continue
            if kind == "none":
                if f.none_only or not required:
                    if f.human_owned:
                        _attest(project, f, path, v, rec, rep, issue)
                    continue
                rep.errors.append(issue("'none' is not a valid answer here; a value is needed"))
                continue
            if kind == "infer" or st == "inferred":
                rep.errors.append(issue("inferred value awaiting confirmation",
                                        f"show it to the {f.owner} owner, then `dwh intake confirm`"))
                continue
            if st == "drafted":
                rep.errors.append(issue(f"drafted by the assistant, not yet confirmed by {rec.get('by')}",
                                        f"show it to them, then `dwh intake confirm {path} --by {rec.get('by')}`"))
                continue
            if kind == "default" or (st == "default" and f.human_owned):
                rep.errors.append(issue("defaults are not allowed for human-owned answers" if f.human_owned
                                        else "unresolved 'default' — record this field again with `dwh intake set`"))
                continue

            err = V.check_type(f, v)
            if err:
                rep.errors.append(issue(err))
                continue
            for spec in f.validate:
                err = V.run_field_validator(spec, project, doc, f, path, caps, v)
                if err:
                    rep.errors.append(issue(err))
            if f.min_items and isinstance(v, (list, dict)) and len(v) < f.min_items:
                rep.errors.append(issue(f"needs at least {f.min_items} entries"))
            if f.human_owned:
                _attest(project, f, path, v, rec, rep, issue)

    for name in cat.validators:
        for problem in V.run_skill_validator(name, project, doc, gate):
            rep.errors.append(Issue(problem[0], "X", problem[1], problem[2], problem[3] if len(problem) > 3 else ""))
    audit(project, "intake.check", skill=skill, gate=gate, ok=rep.ok,
          errors=len(rep.errors), warnings=len(rep.warnings), unattended=unattended)
    return rep


def _attest(project, f, path, v, rec, rep, issue) -> None:
    """A human-owned value counts only if a named owner recorded exactly this value."""
    if not rec:
        rep.errors.append(issue("human-owned answer has no recorded owner",
                                f"record it with `dwh intake set {path} … --by <{f.owner} person>`"))
        return
    by = (rec.get("by") or "").strip()
    if by.lower() in AGENT_IDS or f.owner not in roles_of(project, by):
        rep.errors.append(issue(f"recorded by '{by}', who is not a {f.owner} owner"))
        return
    if rec.get("value_hash") != C.canonical_hash(v):
        rep.errors.append(issue("value changed after the owner answered it",
                                "the owner must re-confirm the current value"))


# ---------------------------------------------------------------- presenting
def show(project: Project, skill: str, gate: str = "A") -> str:
    """Markdown questionnaire for the agent to present, with current state per field."""
    cat = K.load(skill)
    doc = project.document()
    prov = load_provenance(project)
    mode = project.profile_mode
    gates = {"A"} if gate == "A" else {"A", "B"}
    out = [f"# {cat.title} — intake (gate {gate}, profile {mode})",
           "Legend: M = mandatory · M★ = mandatory, answered by the named owner role only · "
           "C/C★ = needed when its condition applies · O = optional (NA or blank is fine)",
           "Answer NA for 'not applicable' (optional fields only) and 'none' where there are none."]
    section = None
    for f in cat.fields:
        if f.gate not in gates or (f.profiles and mode not in {p.lower() for p in f.profiles}):
            continue
        if f.section and f.section != section:
            section = f.section
            out.append(f"\n## {section}")
        exp = K.expand(f.path, doc)
        choices = f" Choices: {', '.join(f.choices)}." if f.choices else ""
        dflt = f" Default: `{f.default}`." if f.default is not None and not f.human_owned else ""
        extra = " Answer 'none' explicitly if there are none." if f.none_only else ""
        cond = ""
        if f.level.startswith("C"):
            cond = " (only when it applies)"
        head = f"- **`{f.path}`** [{f.label}, owner {f.owner}]{cond} — {f.prompt}{choices}{dflt}{extra}"
        if not exp:
            out.append(head + " _(asked once the parent entry exists)_")
            continue
        states = []
        for p, caps in exp:
            if f.level.startswith("C") and not K.eval_condition(f.condition, doc, caps):
                continue
            v = C.get_path(doc, p)
            rec = prov.get(p, {})
            kind = _value_kind(v)
            st = rec.get("state") or ("unanswered" if kind == "blank" else "answered")
            shown = "" if kind == "blank" else f" = `{_short(v)}`"
            states.append(f"`{p}`: {st}{shown}")
        if not states:
            continue
        out.append(head)
        out.extend(f"    - {s}" for s in states)
    return "\n".join(out)


def _short(v: Any) -> str:
    s = f"{len(v)} entries" if isinstance(v, (dict, list)) else str(v)
    return s if len(s) <= 60 else s[:57] + "…"


def export_form(project: Project, skill: str, role: str) -> str:
    """Plain-language form for one owner role, to fill outside the chat."""
    cat = K.load(skill)
    doc = project.document()
    lines = [f"# {cat.title} — questions for the {role} owner",
             "Write your answer after `answer:`. Use NA only where it says optional.", ""]
    for f in cat.fields:
        if f.owner != role.upper():
            continue
        for p, caps in K.expand(f.path, doc):
            if f.level.startswith("C") and not K.eval_condition(f.condition, doc, caps):
                continue
            need = "optional" if f.level == "O" else "required"
            lines += [f"## {p} ({need})", f.prompt or f.path,
                      f"choices: {', '.join(f.choices)}" if f.choices else "", "answer: ", ""]
    return "\n".join(l for l in lines if l is not None)


def stdin_is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False
