"""Unit tests for the project layouts (v1 / v2): spec files, provenance, named locations."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dwh_core import config as C  # noqa: E402
from dwh_core.project import Layout, LayoutError, Project  # noqa: E402

SOURCES = {"orders": {"format": "csv", "location": "data/raw/{batch}/orders.csv"},
           "customers": {"format": "csv", "location": "data/raw/{batch}/customers.csv"}}
SILVER = {"entities": {"orders": {"sources": ["orders"]}, "customers": {"sources": ["customers"]}}}
METRICS = {"gmv": {"entity": "orders", "golden_values": [{"key": "d=2024-01-01", "value": "10.50"}]}}


def make(tmp: Path, layout: str) -> Project:
    extra = "  layout: v2\n" if layout == "v2" else ""
    (tmp / "dwh-project.yaml").write_text(f'project:\n  name: t\n  dwh_core_version: "x"\n{extra}', encoding="utf-8")
    p = Project(tmp)
    for ns, val in (("sources", SOURCES), ("silver", SILVER), ("metrics", METRICS),
                    ("policies", {"egress": "stats_only"}), ("serve", {"title": "T"})):
        p.save_namespace(ns, val)
    p.save_provenance({"sources.orders.format": {"by": "dana"}, "metrics.gmv": {"by": "pat"},
                       "policies.egress": {"by": "gina"}, "silver.entities.orders": {"by": "sam"}})
    return p


@pytest.mark.parametrize("layout", ["v1", "v2"])
def test_round_trip_is_identical(tmp_path, layout):
    p = make(tmp_path, layout)
    doc = p.document()
    assert doc["sources"] == C.to_strings(SOURCES)
    assert doc["silver"] == C.to_strings(SILVER)
    assert doc["metrics"] == C.to_strings(METRICS)
    assert set(p.load_provenance()) == {"sources.orders.format", "metrics.gmv", "policies.egress",
                                        "silver.entities.orders"}


def test_v2_one_file_per_item_and_per_layer_provenance(tmp_path):
    make(tmp_path, "v2")
    assert sorted(f.name for f in (tmp_path / "bronze/specs/sources").glob("*.yaml")) == ["customers.yaml", "orders.yaml"]
    assert sorted(f.name for f in (tmp_path / "silver/specs/entities").glob("*.yaml")) == ["customers.yaml", "orders.yaml"]
    assert [f.name for f in (tmp_path / "gold/specs/metrics").glob("*.yaml")] == ["gmv.yaml"]
    assert "sources.orders.format" in C.load_yaml(tmp_path / "bronze/decisions/provenance.yaml")
    assert "metrics.gmv" in C.load_yaml(tmp_path / "gold/decisions/provenance.yaml")
    assert "policies.egress" in C.load_yaml(tmp_path / "project/decisions/provenance.yaml")
    assert not (tmp_path / "config").exists()


def test_v2_removed_item_removes_its_file(tmp_path):
    p = make(tmp_path, "v2")
    p.save_namespace("sources", {"orders": SOURCES["orders"]})
    assert [f.name for f in (tmp_path / "bronze/specs/sources").glob("*.yaml")] == ["orders.yaml"]


def test_v2_duplicate_name_is_refused(tmp_path):
    make(tmp_path, "v2")
    (tmp_path / "gold/specs/metrics/copy.yaml").write_text("gmv:\n  entity: x\n", encoding="utf-8")
    with pytest.raises(LayoutError, match="defined twice"):
        Layout(tmp_path).load_namespace("metrics")


def test_layout_does_not_change_the_spec_hash(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert make(a, "v1").spec_hash() == make(b, "v2").spec_hash()


def test_named_locations(tmp_path):
    v1, v2 = Layout(tmp_path, "v1"), Layout(tmp_path, "v2")
    assert v1.report("silver-verify").as_posix().endswith("artefacts/silver-verify.md")
    assert v2.report("silver-verify").as_posix().endswith("silver/reports/silver-verify.md")
    assert v2.report("synthetic-score", "json").as_posix().endswith("silver/reports/synthetic-score.json")
    assert v2.generated("gold/x.sql").as_posix().endswith("gold/generated/x.sql")
    assert v1.generated("gold/x.sql").as_posix().endswith("pipeline/generated/gold/x.sql")
    for key in ("dead_letter", "serving", "landed"):
        assert v2.rel(key).startswith(".dwh/"), key   # data rows never sit in a committed folder


def test_unknown_layout_is_refused(tmp_path):
    (tmp_path / "dwh-project.yaml").write_text("project:\n  layout: v9\n", encoding="utf-8")
    with pytest.raises(LayoutError):
        Layout(tmp_path)


# ---------------------------------------------------------------- regressions (independent review)
def test_refused_save_changes_nothing(tmp_path):
    p = make(tmp_path, "v2")
    before = sorted((f.name, f.read_text()) for f in (tmp_path / "bronze/specs/sources").glob("*.yaml"))
    with pytest.raises(LayoutError, match="would share the file"):
        p.save_namespace("sources", {**SOURCES, "Orders": {"format": "csv"}})   # same file on Windows/macOS
    after = sorted((f.name, f.read_text()) for f in (tmp_path / "bronze/specs/sources").glob("*.yaml"))
    assert before == after


def test_underscore_names_keep_their_own_file(tmp_path):
    p = make(tmp_path, "v2")
    p.save_namespace("sources", {**SOURCES, "_orders": {"format": "csv"}})
    names = sorted(f.name for f in (tmp_path / "bronze/specs/sources").glob("*.yaml"))
    assert names == ["_orders.yaml", "customers.yaml", "orders.yaml"]
    assert set(p.load_namespace("sources")) == {"orders", "customers", "_orders"}


def test_file_name_differing_only_in_case_is_not_lost(tmp_path):
    p = make(tmp_path, "v2")
    d = tmp_path / "bronze/specs/sources"
    (d / "orders.yaml").rename(d / "Orders.yaml")            # a hand-renamed file, key still 'orders'
    p.save_namespace("sources", SOURCES)
    assert sorted(f.name for f in d.glob("*.yaml")) == ["customers.yaml", "orders.yaml"]
    assert p.load_namespace("sources") == C.to_strings(SOURCES)


def test_migration_interrupted_then_resumed(tmp_path, monkeypatch):
    from dwh_core import layout as L
    p = make(tmp_path, "v1")
    (tmp_path / "serving").mkdir()
    (tmp_path / "serving" / "CURRENT").write_text("snap_x\n")
    (tmp_path / "dead_letter").mkdir()
    (tmp_path / "dead_letter" / "x.csv").write_text("a\n")
    want = p.spec_hash()
    want_doc = {k: v for k, v in p.document().items() if k != "project"}
    real, calls = L._move, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 5:
            raise OSError("file in use")
        return real(*a, **k)
    monkeypatch.setattr(L, "_move", flaky)
    with pytest.raises(OSError):
        L.migrate(Project(tmp_path))
    assert Layout(tmp_path).version == "v1" and (tmp_path / "config/sources.yaml").exists()
    assert Project(tmp_path).spec_hash() == want              # the v1 project still works as before
    monkeypatch.setattr(L, "_move", real)
    L.migrate(Project(tmp_path))                              # simply run again
    q = Project(tmp_path)
    assert q.layout.version == "v2" and not (tmp_path / "config").exists()
    assert (tmp_path / ".dwh/serving/CURRENT").exists() and (tmp_path / ".dwh/dead_letter/x.csv").exists()
    assert {k: v for k, v in q.document().items() if k != "project"} == want_doc


def test_migration_accepts_empty_namespaces_and_keeps_gitignore(tmp_path):
    from dwh_core import layout as L
    p = make(tmp_path, "v1")
    p.save_namespace("silver", {"entities": {}})
    (tmp_path / ".gitignore").write_text(".env\nserving/\n")
    L.migrate(Project(tmp_path))
    gi = (tmp_path / ".gitignore").read_text()
    assert ".env" in gi and ".dwh/" in gi and Layout(tmp_path).version == "v2"
