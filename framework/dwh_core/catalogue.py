"""Intake catalogues: the list of every input a skill needs, with its level, owner and gate.

Levels
  M   mandatory                          NA/blank rejected
  M*  mandatory, human-owned             NA/blank/default/infer rejected; only a listed owner's answer
                                         counts (the intake workbook may show a proposed default —
                                         the owner keeping it is their answer, flagged default_kept)
  C   mandatory when `condition` holds   auto-NA when the condition is false
  C*  human-owned when `condition` holds
  O   optional                           NA/blank accepted, consequence logged
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config as C

CATALOGUE_DIR = Path(__file__).parent / "catalogues"
LEVELS = {"M", "M*", "C", "C*", "O"}
OWNERS = {"DE", "PO", "SME", "GOV", "CON"}


@dataclass
class Field:
    path: str
    level: str
    owner: str
    gate: str
    type: str = "string"
    prompt: str = ""
    section: str = ""
    choices: list = field(default_factory=list)
    min_items: int = 0
    condition: Any = None
    none_only: bool = False
    allow_infer: bool = False
    default: Any = None
    why: str = ""
    consequence: str = ""
    validate: list = field(default_factory=list)
    prefill: str = ""
    profiles: list = field(default_factory=list)
    skill: str = ""
    pending_ok: bool = False  # a ★ decision the build does not compute with may wait (fast profile)

    @property
    def human_owned(self) -> bool:
        return self.level.endswith("*")

    @property
    def label(self) -> str:
        return self.level.replace("*", "★")

    def matches(self, concrete: str) -> list[str] | None:
        """Return wildcard captures if `concrete` matches this field's pattern."""
        pat = C.split_path(self.path)
        got = C.split_path(concrete)
        if len(pat) != len(got):
            return None
        caps = []
        for p, g in zip(pat, got):
            if p == "*":
                caps.append(g)
            elif p != g:
                return None
        return caps


@dataclass
class Catalogue:
    skill: str
    title: str
    fields: list[Field]
    validators: list = field(default_factory=list)


def _bool(v: Any) -> bool:
    return str(v).strip().lower() in C.TRUE_WORDS


@functools.lru_cache(maxsize=None)
def load(skill: str) -> Catalogue:
    """Catalogues are read once per process (they are part of the pinned kernel, never edited at runtime)."""
    path = CATALOGUE_DIR / f"{skill}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no intake catalogue for skill '{skill}'")
    raw = C.load_yaml(path)
    fields = []
    for f in raw.get("fields", []):
        level = f["level"]
        if level not in LEVELS:
            raise ValueError(f"{skill}: bad level {level} on {f['path']}")
        owner = f.get("owner", "DE")
        if owner not in OWNERS:
            raise ValueError(f"{skill}: bad owner {owner} on {f['path']}")
        if level.startswith("C") and not f.get("condition"):
            raise ValueError(f"{skill}: conditional field {f['path']} has no condition")
        fields.append(Field(
            path=f["path"], level=level, owner=owner, gate=f.get("gate", "A"),
            type=f.get("type", "string"), prompt=f.get("prompt", ""), section=f.get("section", ""),
            choices=C.as_list(f.get("choices")), min_items=int(f.get("min_items", "0") or 0),
            condition=f.get("condition"), none_only=_bool(f.get("none_only", "false")),
            allow_infer=_bool(f.get("allow_infer", "false")), default=f.get("default"),
            why=f.get("why", ""), consequence=f.get("consequence", ""),
            validate=C.as_list(f.get("validate")), prefill=f.get("prefill", ""),
            profiles=C.as_list(f.get("profiles")), skill=skill,
            pending_ok=_bool(f.get("pending_ok", "false"))))
    return Catalogue(skill=skill, title=raw.get("title", skill), fields=fields,
                     validators=C.as_list(raw.get("validators")))


@functools.lru_cache(maxsize=None)
def _all() -> tuple:
    return tuple(load(p.stem) for p in sorted(CATALOGUE_DIR.glob("*.yaml")))


def all_catalogues() -> list[Catalogue]:
    return list(_all())


@functools.lru_cache(maxsize=4096)
def _find(concrete: str):
    for cat in _all():
        for f in cat.fields:
            caps = f.matches(concrete)
            if caps is not None:
                return f, tuple(caps)
    return None, None


def find_field(concrete: str) -> tuple[Field, list[str]] | tuple[None, None]:
    f, caps = _find(concrete)
    return (f, list(caps)) if f is not None else (None, None)


def descendant_fields(prefix: str) -> list[Field]:
    """Fields whose pattern lives under `prefix` (used when a whole subtree is set)."""
    out = []
    pre = C.split_path(prefix)
    for cat in all_catalogues():
        for f in cat.fields:
            pat = C.split_path(f.path)
            if len(pat) > len(pre) and all(p == "*" or p == q for p, q in zip(pat, pre)):
                out.append(f)
    return out


# ---------------------------------------------------------------- expansion
def expand(pattern: str, doc: Any) -> list[tuple[str, list[str]]]:
    """All concrete paths in `doc` matching `pattern`, with their wildcard captures."""
    parts = C.split_path(pattern)
    out: list[tuple[str, list[str]]] = []

    def walk(node: Any, i: int, acc: list[str], caps: list[str]) -> None:
        if i == len(parts):
            out.append((".".join(acc), caps))
            return
        part = parts[i]
        if part == "*":
            if isinstance(node, dict):
                for k in node:
                    walk(node[k], i + 1, acc + [k], caps + [k])
            elif isinstance(node, list):
                for idx, item in enumerate(node):
                    walk(item, i + 1, acc + [str(idx)], caps + [str(idx)])
            return
        if i == len(parts) - 1:
            # leaf: include even when absent so "missing" can be reported
            walk(node.get(part) if isinstance(node, dict) else None, i + 1, acc + [part], caps)
            return
        child = node.get(part) if isinstance(node, dict) else None
        if child is None and "*" not in parts[i + 1:]:
            walk(None, i + 1, acc + [part], caps)  # still reach the leaf to report missing
            return
        walk(child, i + 1, acc + [part], caps)

    walk(doc, 0, [], [])
    return out


# ---------------------------------------------------------------- conditions
def _subst(path: str, caps: list[str]) -> str:
    return re.sub(r"\{(\d+)\}", lambda m: caps[int(m.group(1)) - 1], path)


def _val(doc: Any, path: str, caps: list[str]) -> Any:
    return C.get_path(doc, _subst(path, caps), None)


def _norm(v: Any) -> str:
    return str(v).strip().lower()


def eval_condition(cond: Any, doc: Any, caps: list[str]) -> bool:
    if cond is None:
        return True
    if not isinstance(cond, dict) or len(cond) != 1:
        raise ValueError(f"malformed condition: {cond!r}")
    (op, arg), = cond.items()
    if op == "all":
        return all(eval_condition(c, doc, caps) for c in arg)
    if op == "any":
        return any(eval_condition(c, doc, caps) for c in arg)
    if op == "not":
        return not eval_condition(arg, doc, caps)
    if op in ("eq", "ne"):
        v = _val(doc, arg[0], caps)
        res = v is not None and _norm(v) == _norm(arg[1])
        return res if op == "eq" else not res
    if op == "in":
        v = _val(doc, arg[0], caps)
        return v is not None and _norm(v) in {_norm(x) for x in arg[1]}
    if op == "nonempty":
        v = _val(doc, arg, caps)
        return not C.is_blank(v) and not C.is_token(v, C.NA_TOKEN) and not C.is_token(v, C.NONE_TOKEN)
    if op == "empty":
        return not eval_condition({"nonempty": arg}, doc, caps)
    if op == "truthy":
        v = _val(doc, arg, caps)
        return v is not None and _norm(v) in C.TRUE_WORDS
    if op == "count_gt":
        v = _val(doc, arg[0], caps)
        n = len(v) if isinstance(v, (list, dict)) else 0
        return n > int(arg[1])
    raise ValueError(f"unknown condition op: {op}")
