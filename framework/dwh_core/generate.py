"""Deterministic rendering of runtime code from specs, with tamper-evident headers.

Every generated file starts with a header carrying the kernel version, the template hash,
the spec hash and the hash of the body. The runner refuses to execute a file whose body no
longer matches its header (a hand edit), and the generator refuses to overwrite one. Logic the
templates cannot express belongs in custom/ (see the dwh-silver skill), never in these files.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
from pathlib import Path

from . import VERSION
from . import config as C
from .project import Project, audit

LAYERS = {"silver": "silver", "gold": "gold", "serve": "serve"}
MARK = "dwh_core:generated"


class TamperedFile(RuntimeError):
    pass


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def template_sha(module_name: str) -> str:
    mod = importlib.import_module(f"dwh_core.{module_name}")
    return _sha(inspect.getsource(mod))[:16]


def _comment(path: Path) -> str:
    return "#" if path.suffix == ".py" else "--"


def header(path: Path, template: str, tsha: str, spec_sha: str, body: str) -> str:
    c = _comment(path)
    return (f"{c} {MARK} v={VERSION} template={template} template_sha={tsha} "
            f"spec_sha={spec_sha[:16]} body_sha={_sha(body)}\n"
            f"{c} DO NOT EDIT — change the specs and run `dwh generate`. "
            f"Custom logic goes in custom/.\n")


def parse_header(text: str) -> dict:
    first = text.split("\n", 1)[0]
    if MARK not in first:
        return {}
    return dict(tok.split("=", 1) for tok in first.split() if "=" in tok)


def body_of(text: str) -> str:
    return text.split("\n", 2)[2] if text.count("\n") >= 2 else ""


def is_intact(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    h = parse_header(text)
    return bool(h) and h.get("body_sha") == _sha(body_of(text))


def write_generated(project: Project, rel: str, body: str, template: str, module: str, spec_sha: str) -> Path:
    path = project.layout.generated(rel)
    if path.exists() and not is_intact(path):
        raise TamperedFile(f"{path.relative_to(project.root)} was edited by hand; refusing to overwrite. "
                           "Move the custom logic into custom/ and restore the file with `dwh generate`.")
    text = header(path, template, template_sha(module), spec_sha, body) + body
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        C.atomic_write_text(path, text)
    return path


def load_verified(project: Project, rel: str) -> str:
    path = project.layout.generated(rel)
    if not path.exists():
        raise TamperedFile(f"{rel} has not been generated; run `dwh generate`")
    text = path.read_text(encoding="utf-8")
    if not is_intact(path):
        raise TamperedFile(f"{path.relative_to(project.root)} does not match its header (edited by hand); "
                           "refusing to run it")
    return body_of(text)


def render_layer(project: Project, layer: str = "all") -> list[Path]:
    layers = list(LAYERS) if layer == "all" else [layer]
    out = []
    for lay in layers:
        mod = importlib.import_module(f"dwh_core.{LAYERS[lay]}")
        for rel, (body, spec_sha) in mod.render(project).items():
            out.append(write_generated(project, rel, body, f"{lay}/v1", LAYERS[lay], spec_sha))
    audit(project, "generate", layer=layer, files=[str(p.relative_to(project.root)) for p in out])
    return out


def verify_all(project: Project) -> list[str]:
    out = []
    for root in project.layout.generated_roots():
        if root.exists():
            out += [str(p.relative_to(project.root)) for p in sorted(root.rglob("*"))
                    if p.is_file() and p.suffix in (".sql", ".py") and "__pycache__" not in p.parts
                    and not is_intact(p)]
    return out
