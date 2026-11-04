"""The gates' Sources for a companion run, built from passed paths and the vocabulary file; no site file is read."""

from __future__ import annotations

import json
from pathlib import Path

from generator import gates, scrublist


class NotReadError(Exception):
    """An input the run could not read or could not shape: named, never guessed (exit 3)."""


def _rel(path: Path, root: Path) -> str:
    """How a finding names the file: relative to the root where it lies under it, else by its name alone, so no local
    path reaches an output (3c's F4)."""
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name


def doc(kind: str, path: Path, root: Path) -> gates.Doc:
    try:
        return gates._shaped(kind, gates.Doc(_rel(path, root), path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        raise NotReadError(f"{_rel(path, root)}: {type(e).__name__}: {e}") from e


def vocabulary(path: Path, root: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise NotReadError(f"{_rel(path, root)}: {type(e).__name__}: {e}") from e
    for key in ("jobs", "competencies", "phases", "pages", "rungs", "written_from"):
        if key not in data:
            raise NotReadError(f"{_rel(path, root)}: the vocabulary file holds no {key}")
    return data


def read(
    root: Path,
    register: Path,
    portfolio: Path,
    policy: Path,
    vocabulary_path: Path,
    imports: dict | None = None,
    lists: scrublist.Lists | None = None,
    clauses: frozenset[str] | None = None,
) -> tuple[gates.Sources, dict]:
    """Sources as gates.Sources.read builds them, from the passed files alone: the vocabulary in place of the
    competency map, the phases, the pages and the ladder; no rendered views, no catalog map, no outside model."""
    v = vocabulary(vocabulary_path, root)
    s = gates.Sources(
        register=doc("register", register, root),
        portfolio=doc("portfolio", portfolio, root),
        policy=doc("policy", policy, root),
        comp_map={"jobs": v["jobs"], "competencies": v["competencies"]},
        pages={p["path"]: p for p in v["pages"]},
        phases={p["id"] for p in v["phases"]},
        rungs=set(v["rungs"]),
        views={},
        catalog_map=None,
        outside_model=None,
        root=root,
        imports=imports,
        clauses=clauses,  # the clauses this run judges (split.partition): a gate skips the reads of the others
        lists=lists,  # the run's scrub list: no gate reaches for the publisher's
    )
    return s, v
