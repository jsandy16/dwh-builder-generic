"""Keep secrets and protected values out of anything written for humans or the model."""
from __future__ import annotations

import re

SECRET_PATTERNS = [
    (re.compile(r"(?i)[?&](sig|signature|x-amz-signature|x-goog-signature)=[^&\s]{8,}"), "signed-URL token"),
    (re.compile(r"(?i)AccountKey=[A-Za-z0-9+/=]{20,}"), "storage account key"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}"), "bearer token"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"(?i)://[^/\s:@]+:[^/\s@]+@"), "credentials inside a URL"),
]
PROTECTED = {"pii", "sensitive", "regulated"}


class EgressError(RuntimeError):
    pass


def find_secrets(text: str) -> list[str]:
    return [label for rx, label in SECRET_PATTERNS if rx.search(text or "")]


def assert_clean(text: str, where: str = "") -> None:
    hits = find_secrets(text)
    if hits:
        raise EgressError(f"refusing to write {where}: it would contain a {', '.join(hits)}")


def may_show_values(policy: str, classification: str) -> bool:
    """Example values only with samples_allowed AND a non-protected column."""
    return (policy or "").lower() == "samples_allowed" and (classification or "").lower() in ("public", "internal")


def fence(text: str, limit: int = 120) -> str:
    """Source-derived text shown to the model is data, not instructions: fence and truncate it."""
    t = str(text).replace("`", "'").replace("\n", " ")
    return f"`{t[:limit]}{'…' if len(t) > limit else ''}`"
