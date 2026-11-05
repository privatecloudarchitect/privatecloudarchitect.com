"""Parsed files, cached by path, size and modification time (the strategy suites' cost, 2026-11-05).

A render reads the same files many times: the pins file once per capability's drift read, the site's competency map
and page manifest once per render, the layout once per view. Each parse is the same work on the same bytes, and the
two generator tests that re-render the views once per portfolio figure made more than sixteen hundred renders of
twenty parses each. `parsed` parses a file once per process and hands back that object until the file's size or
modification time moves, so a file rewritten on disk (a test writing a fixture, a release re-pinning the copies) is
parsed again on its next read, and nothing is served from a stale parse.

The object returned is shared: a caller reads it and never mutates it. A caller that needs its own copy copies it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

_CACHE: dict[Path, tuple[tuple[int, int], Any]] = {}


def parsed(path: Path, parse: Callable[[str], Any]) -> Any:
    """The file at `path` parsed by `parse`, from the cache when the file's size and modification time are the ones it
    was parsed at; read-only to the caller."""
    st = path.stat()
    key = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    value = parse(path.read_text(encoding="utf-8"))
    _CACHE[path] = (key, value)
    return value


def forget() -> None:
    """Drop every cached parse (a test that wants a cold read)."""
    _CACHE.clear()
