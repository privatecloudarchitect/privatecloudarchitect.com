"""frameworks/cartography/lib/_taxonomy - the estate's concept -> live category-name resolver.

The slice writes four DISCOVERY-OWNED axes, declared in ``taxonomy.yaml`` at the estate root:
``function`` (the axis the tuning framework governs on), ``app`` and ``app-layer`` (pure identity
facts), and ``env-observed`` (the observed companion of the operator-declared environment; the
intent twin is never written by discovery). Each maps one concept to a live category name, an
object scope, a cardinality, and a value list, where ``values: open`` marks an open registry
(``app``) that pre-seeds nothing.

Set ``CARTOGRAPHY_TAXONOMY=/path/to/file.yaml`` to point every script at an alternate taxonomy
file, the same override seam the reference estate uses to run these exact scripts against its own
namespaced category names.
"""
from __future__ import annotations

import os

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TAXONOMY = os.path.join(HERE, "taxonomy.yaml")

CONCEPTS = ("app", "app-layer", "function", "env-observed")


def taxonomy_path() -> str:
    return os.environ.get("CARTOGRAPHY_TAXONOMY", DEFAULT_TAXONOMY)


def load_taxonomy(path: str | None = None) -> dict:
    return yaml.safe_load(open(path or taxonomy_path(), encoding="utf-8")) or {}


def categories(path: str | None = None) -> dict[str, dict]:
    """{concept: declaration} for every declared concept."""
    return {c["concept"]: c for c in load_taxonomy(path).get("categories") or []}


def category_name(concept: str, path: str | None = None) -> str:
    """The live category name a concept resolves to (defaults to the concept itself)."""
    c = categories(path).get(concept) or {}
    return c.get("category", concept)
