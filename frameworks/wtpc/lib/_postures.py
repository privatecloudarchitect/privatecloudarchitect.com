"""wtpc/_postures.py - the posture-discovery + content-identity seam (the elevator, not the ramp).

A WTPC posture is DATA: postures/<name>.yaml declares its envelope, floor, policy, and groups, AND its
stable content identity - a `content_ids:` block carrying the view / dashboard / widget / tab id prefixes
plus a catalog ordinal. Every generator reads identity and the posture set FROM HERE, so adding a posture
is dropping one YAML (with a unique content_ids block), never editing a per-posture dict inside a
generator. This module is the single source for both.

Consumers: build_views, build_dashboard (single-posture identity via content_ids); build_governance,
build_governance_views, build_view_bundles (the estate set via discover()).
"""
from __future__ import annotations

import glob
import os

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the bundle root (this loader lives in lib/)
POSTURES_DIR = os.path.join(HERE, "postures")

# content_ids keys every posture must declare (the stable, collision-free id seam). view/dashboard/
# widget/tab are UUID PREFIXES (4 hex chars) expanded by the generators into full ids; ordinal is the
# catalog P-number and fixes the estate ordering (so a governance SM index maps to a stable posture).
_REQUIRED_IDS = ("ordinal", "view_prefix", "view", "dashboard", "widget", "tab")


def load_posture(name: str) -> dict:
    """The full posture YAML doc for a posture name."""
    return yaml.safe_load(open(os.path.join(POSTURES_DIR, f"{name}.yaml"), encoding="utf-8"))


def content_ids(name_or_doc) -> dict:
    """The validated content_ids block for a posture (name or already-loaded doc). Fails loud if a
    posture is missing the seam - a new posture MUST ship its own ids, so the failure names exactly
    what to add rather than silently colliding with another posture's content."""
    doc = name_or_doc if isinstance(name_or_doc, dict) else load_posture(name_or_doc)
    cids = doc.get("content_ids") or {}
    missing = [k for k in _REQUIRED_IDS if not cids.get(k)]
    if missing:
        raise SystemExit(f"posture {doc.get('posture')!r}: content_ids missing {missing} "
                         f"(the stable id seam - copy the block shape from any postures/*.yaml, "
                         f"allocate a unique prefix)")
    return cids


def discover(require_sm: bool = True) -> list[str]:
    """Every instantiated posture, ordered by its declared catalog ordinal (stable id assignment; a
    governance SM at index i maps to a fixed posture across runs). require_sm=True (default) keeps only
    postures with a built `supermetrics.<name>.yaml` record - governance reads those records, so an
    authored-but-not-yet-built posture is skipped until its content is generated."""
    items: list[tuple[int, str]] = []
    for path in sorted(glob.glob(os.path.join(POSTURES_DIR, "*.yaml"))):
        doc = yaml.safe_load(open(path, encoding="utf-8"))
        name = doc["posture"]
        if require_sm and not os.path.exists(os.path.join(HERE, f"supermetrics.{name}.yaml")):
            continue
        ordinal = (doc.get("content_ids") or {}).get("ordinal", 999)
        items.append((ordinal, name))
    return [name for _, name in sorted(items)]
