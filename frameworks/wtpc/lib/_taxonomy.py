"""frameworks/wtpc/lib/_taxonomy - the estate's concept -> live category-name resolver.

The posture sources reference tag CONCEPTS (env / function / sla). Your estate's live category
names may differ - an existing taxonomy, a namespacing convention - so the mapping is data:
``taxonomy.yaml`` at the estate root declares, per concept, the live category name, the object
scope, the cardinality, and the closed value list. Every consumer resolves concept -> category
through this module, so renaming a category for your estate edits one file and no script.

Set ``WTPC_TAXONOMY=/path/to/file.yaml`` to point every script at an alternate taxonomy file
(the same override the reference estate uses to run these exact scripts against its own
namespaced category names).
"""
from __future__ import annotations

import os

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the estate root (this lives in lib/)
DEFAULT_TAXONOMY = os.path.join(HERE, "taxonomy.yaml")

# The SINGLE-cardinality posture-membership axes (postures/*.yaml membership rules).
POSTURE_CONCEPTS = ("env", "function", "sla")


def taxonomy_path() -> str:
    return os.environ.get("WTPC_TAXONOMY", DEFAULT_TAXONOMY)


def load_taxonomy(path: str | None = None) -> dict:
    """The parsed taxonomy document."""
    return yaml.safe_load(open(path or taxonomy_path(), encoding="utf-8")) or {}


def categories(path: str | None = None) -> list[dict]:
    """The category declarations: [{concept, category, object, cardinality, values}, ...]."""
    return list(load_taxonomy(path).get("categories") or [])


def runtime_by_concept(path: str | None = None) -> dict[str, str]:
    """{concept -> live category name} for every declared concept."""
    return {c["concept"]: c.get("category", c["concept"]) for c in categories(path)}


def posture_runtime(path: str | None = None) -> dict[str, str]:
    """{posture concept (env/function/sla) -> live category name} - the posture subset, so every
    posture consumer resolves category names identically. A concept the taxonomy omits resolves to
    its own name (the bare default)."""
    m = runtime_by_concept(path)
    return {c: m.get(c, c) for c in POSTURE_CONCEPTS}


__all__ = ["DEFAULT_TAXONOMY", "POSTURE_CONCEPTS", "categories", "load_taxonomy",
           "posture_runtime", "runtime_by_concept", "taxonomy_path"]
