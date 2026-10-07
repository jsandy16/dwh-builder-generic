"""Unit tests for strict spec I/O: every scalar is a string, nothing is coerced."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dwh_core import config as C  # noqa: E402


def test_yaml_scalars_stay_strings(tmp_path):
    f = tmp_path / "x.yaml"
    f.write_text("a: NO\nb: 007\nc: 1.10\nd: ~\ne: NA\n", encoding="utf-8")
    assert C.load_yaml(f) == {"a": "NO", "b": "007", "c": "1.10", "d": "~", "e": "NA"}


def test_dump_then_load_round_trips(tmp_path):
    f = tmp_path / "y.yaml"
    data = {"region": "NA", "country": "NO", "code": "007", "flag": "yes", "text": "a: b # c"}
    C.dump_yaml(data, f)
    assert C.load_yaml(f) == data


def test_canonical_hash_ignores_key_order():
    assert C.canonical_hash({"a": "1", "b": ["x", "y"]}) == C.canonical_hash({"b": ["x", "y"], "a": "1"})


def test_tokens_are_whole_answers_only():
    assert C.is_token(" na ", "NA")
    assert not C.is_token(["NA"], "NA")
