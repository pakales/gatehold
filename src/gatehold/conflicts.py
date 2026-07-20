"""Deterministic workstream and lexical scope conflict rules."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable

_MULTI_SLASH = re.compile(r"/+")


def canonical_workstream(value: str) -> str:
    return " ".join(value.split()).casefold()


def canonical_scope(value: str) -> str:
    """Return a stable lexical scope key without touching the filesystem."""

    normalized = value.strip().replace("\\", "/")
    normalized = _MULTI_SLASH.sub("/", normalized)
    if normalized == "*":
        return normalized
    prefix = "/" if normalized.startswith("/") else ""
    normalized = posixpath.normpath(normalized)
    if normalized == ".":
        normalized = ""
    if prefix and not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized.rstrip("/").casefold() or "/"


def scopes_overlap(left: str, right: str) -> bool:
    left_key = canonical_scope(left)
    right_key = canonical_scope(right)
    if "*" in {left_key, right_key}:
        return True
    if left_key == right_key:
        return True

    # Named scopes such as ``database:billing`` conflict only by exact key.
    if ":" in left_key or ":" in right_key:
        return False

    left_parts = tuple(part for part in left_key.split("/") if part)
    right_parts = tuple(part for part in right_key.split("/") if part)
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]


def scope_sets_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    return any(scopes_overlap(a, b) for a in left for b in right)
