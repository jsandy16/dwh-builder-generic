"""Human-only, hash-bound approvals (plan v2 D-12).

* `approve` refuses unless stdin is an interactive terminal and the person types their id.
  The agent drives the CLI through a non-interactive shell, so it cannot approve that way;
  a pseudo-terminal could defeat this check, so it is a guard rail, not proof of identity —
  the SKILL rule (the agent never runs approve) and the hash-chained log are the controls.
* Each approval binds the hash of every spec + answer provenance. Any later change to a
  spec invalidates it (the build may continue in fast/demo; publishing to consumers stops).
* The log is append-only and hash-chained, so editing a past entry breaks the chain.
* In the governed profile the approver must not be the builder.
"""
from __future__ import annotations

import hashlib
import json

from . import AGENT_IDS
from .intake import roles_of, stdin_is_tty
from .project import Project, audit, now_iso


class ApprovalError(RuntimeError):
    pass


def _entries(project: Project) -> list[dict]:
    if not project.approvals_file.exists():
        return []
    out = []
    for line in project.approvals_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def verify_chain(project: Project) -> tuple[bool, str]:
    prev = "genesis"
    for i, e in enumerate(_entries(project)):
        if e.get("prev") != prev or _entry_hash(e) != e.get("hash"):
            return False, f"approval log tampered at entry {i + 1}"
        prev = e["hash"]
    return True, "ok"


def approve(project: Project, by: str, meaning: str = "approve", note: str = "",
            _input=input, _tty=None) -> dict:
    tty = stdin_is_tty() if _tty is None else _tty
    if not tty:
        raise ApprovalError(
            "Approvals must be given by a person in an interactive terminal. "
            "Ask the approver to run:  dwh approve --by <their id>")
    if not by or by.lower() in AGENT_IDS:
        raise ApprovalError("an approval needs a named person")
    roles = roles_of(project, by)
    if not roles & {"PO", "GOV"}:
        raise ApprovalError(f"'{by}' needs role PO or GOV in the people list to approve")
    if project.profile_mode == "governed" and by == project.builder:
        raise ApprovalError("in the governed profile the approver cannot be the builder")
    ok, why = verify_chain(project)
    if not ok:
        raise ApprovalError(why)
    spec_hash = project.spec_hash()
    typed = _input(f"Approving spec version {spec_hash[:12]} as '{by}'. Type your id to confirm: ").strip()
    if typed != by:
        raise ApprovalError("confirmation did not match; nothing approved")
    entries = _entries(project)
    entry = {
        "at": now_iso(), "by": by, "roles": sorted(roles), "meaning": meaning,
        "spec_hash": spec_hash, "self_approved": by == project.builder,
        "note": note[:300], "prev": entries[-1]["hash"] if entries else "genesis",
    }
    entry["hash"] = _entry_hash(entry)
    project.approvals_file.parent.mkdir(parents=True, exist_ok=True)
    with open(project.approvals_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    audit(project, "approve", by=by, spec_hash=spec_hash)
    return entry


def status(project: Project) -> dict:
    ok, why = verify_chain(project)
    current = project.spec_hash()
    entries = _entries(project)
    latest = next((e for e in reversed(entries) if e.get("meaning") == "approve"), None)
    valid = bool(ok and latest and latest.get("spec_hash") == current)
    return {
        "chain_ok": ok, "chain_detail": why, "current_spec_hash": current,
        "approved": valid, "approved_by": latest.get("by") if latest else None,
        "self_approved": bool(latest and latest.get("self_approved")),
        "stale": bool(latest and latest.get("spec_hash") != current),
    }
