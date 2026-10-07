"""Lineage registered by each skill in its own namespace (replaced whole on every run)."""
from __future__ import annotations

from . import config as C
from .project import Project


def register(project: Project, skill: str, nodes: list[dict], edges: list[dict]) -> None:
    path = project.loc("lineage_yaml")
    data = C.load_yaml(path) or {}
    data[skill] = {"nodes": nodes, "edges": edges}
    C.dump_yaml(data, path)
    _render(project, data)


def _render(project: Project, data: dict) -> None:
    colours = {"source": "#cfe8ff", "bronze": "#ffd9b3", "silver": "#e0e0e0",
               "gold": "#fff3b0", "consumer": "#c9f0c9", "dead_letter": "#ffb3b3"}
    lines = ["# Lineage", "", "*Generated from the registrations in `governance/lineage.yaml`.*", "",
             "```mermaid", "flowchart LR"]
    seen = set()
    styles = []
    for skill in data.values():
        for n in skill.get("nodes", []):
            if n["id"] in seen:
                continue
            seen.add(n["id"])
            lines.append(f'    {n["id"]}["{n.get("label", n["id"])}"]')
            styles.append(f'    style {n["id"]} fill:{colours.get(n.get("layer", ""), "#ffffff")}')
        for e in skill.get("edges", []):
            lines.append(f'    {e["from"]} -->|{e.get("label", "")}| {e["to"]}')
    lines += styles + ["```", ""]
    C.atomic_write_text(project.loc("lineage_md"), "\n".join(lines))
