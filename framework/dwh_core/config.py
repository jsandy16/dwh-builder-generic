"""Strict spec I/O.

Specs are loaded with yaml.BaseLoader, so every scalar arrives as a STRING. YAML 1.1
coercion (NO -> False, ON -> True, 010 -> 8, 1.10 -> 1.1, ~ -> None) never happens; a
region called "NA", a country code "NO" and a zero-padded "007" survive intact.
Types are applied later, per field, from the intake catalogue.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

NA_TOKEN = "NA"        # whole-answer marker meaning "not applicable"
NONE_TOKEN = "none"    # a real answer meaning "there are none"
DEFAULT_TOKEN = "default"
INFER_TOKEN = "infer"
_MISSING = object()


# ---------------------------------------------------------------- files
def load_yaml(path: Path) -> Any:
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        data = yaml.load(fh, Loader=yaml.BaseLoader)  # strings only
    return {} if data is None else data


class _StrDumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, value):
    # Quote anything a YAML 1.1 reader could misread, so files stay safe for other tools too.
    style = None
    if value == "" or re.fullmatch(
        r"(?i)(y|n|yes|no|on|off|true|false|null|~|na|none|[-+]?[0-9_.:eE]+|0x[0-9a-f]+|0o[0-7]+)",
        value,
    ) or value.strip() != value or any(ch in value for ch in ":#{}[],&*!|>'\"%@`\n"):
        style = '"' if "\n" not in value else "|"
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_StrDumper.add_representer(str, _str_presenter)


def to_strings(obj: Any) -> Any:
    """Normalise python values to the strings-only shape BaseLoader produces."""
    if isinstance(obj, dict):
        return {str(k): to_strings(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_strings(v) for v in obj]
    if obj is None:
        return ""
    if isinstance(obj, bool):
        return "true" if obj else "false"
    return str(obj)


def dump_yaml(data: Any, path: Path) -> None:
    text = yaml.dump(to_strings(data), Dumper=_StrDumper, sort_keys=False,
                     allow_unicode=True, default_flow_style=False, width=100)
    atomic_write_text(Path(path), text)


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(Path(path), json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- hashing
def canonical_hash(obj: Any) -> str:
    """Hash of parsed content (not bytes): CRLF / quoting / key order cannot change it."""
    blob = json.dumps(to_strings(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- dotted paths
def split_path(path: str) -> list[str]:
    return [p for p in path.split(".") if p != ""]


def get_path(data: Any, path: str, default: Any = _MISSING) -> Any:
    cur = data
    for part in split_path(path):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None if default is _MISSING else default
    return cur


def set_path(data: dict, path: str, value: Any) -> None:
    parts = split_path(path)
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part) if isinstance(cur, dict) else None
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def del_path(data: dict, path: str) -> None:
    parts = split_path(path)
    cur = data
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return
        cur = cur[part]
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)


# ---------------------------------------------------------------- typed views
TRUE_WORDS = {"true", "yes", "y", "1"}
FALSE_WORDS = {"false", "no", "n", "0"}


def as_bool(value: Any) -> bool:
    v = str(value).strip().lower()
    if v in TRUE_WORDS:
        return True
    if v in FALSE_WORDS:
        return False
    raise ValueError(f"expected yes/no, got {value!r}")


def as_int(value: Any) -> int:
    v = str(value).strip()
    if not re.fullmatch(r"[-+]?\d+", v):
        raise ValueError(f"expected an integer, got {value!r}")
    return int(v)


def as_number(value: Any) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"expected a number, got {value!r}") from None


def as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "") or value == {} or value == []


def is_token(value: Any, token: str) -> bool:
    """True only when the WHOLE answer is the token. A list containing 'NA' is data."""
    return isinstance(value, str) and value.strip().lower() == token.lower()
