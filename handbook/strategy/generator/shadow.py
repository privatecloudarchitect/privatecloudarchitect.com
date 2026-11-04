"""The shadow run of a method version (30-GATES.md step 7; charter section 5.12, the method change class).

A new version of a method is registered beside the current one with the status `shadow`, implemented beside it
(`core.implements`), and run on the reference portfolio before any ruling selects it. This module runs every version
in shadow beside the version of the same method that is current, and reports each difference between their outputs.
It writes nothing: not to `policy.yaml`, whose selection only a ruling changes, and not to any output, whose provenance
names only the versions that made it. A measure method's shadow run is its own (instrument/lead_time.py writes its
output stamped `shadow`); this one covers the generator's methods.

Run from the repository root: docs/design/enterprise-strategy-layer/generator/shadow.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

LAYER = Path(__file__).resolve().parent.parent
if str(LAYER) not in sys.path:
    sys.path.insert(0, str(LAYER))

from generator import core  # noqa: E402
from generator.models import Portfolio, Register  # noqa: E402
from generator.policy import Loaded, PolicyError  # noqa: E402

IGNORED = {"provenance", "method"}  # what names the version, not what the version computes


def differences(current: Any, shadow: Any, at: str = "") -> list[dict]:
    """Every path at which two outputs differ, with both values."""
    if isinstance(current, dict) and isinstance(shadow, dict):
        out = []
        for k in sorted(set(current) | set(shadow), key=str):
            if k in IGNORED:
                continue
            out += differences(current.get(k), shadow.get(k), f"{at}.{k}" if at else str(k))
        return out
    if isinstance(current, list) and isinstance(shadow, list) and len(current) == len(shadow):
        out = []
        for i, (a, b) in enumerate(zip(current, shadow, strict=True)):
            out += differences(a, b, f"{at}[{i}]")
        return out
    return [] if current == shadow else [{"at": at, "current": current, "shadow": shadow}]


def shadow_runs(register: Register, portfolio: Portfolio, pol: Loaded, *args) -> list[dict]:
    """For each method version in shadow: the current version beside it, and every difference between their outputs."""
    out = []
    for m in pol.model.methods:
        if m.status != "shadow" or (m.id, m.version) not in core.METHODS:
            continue
        current = [c for c in pol.model.methods if c.id == m.id and c.status == "current"]
        if len(current) != 1:
            raise PolicyError(
                f"{m.id} has {len(current)} current versions to run version {m.version} beside"
            )
        cur = current[0]
        a = core.METHODS[(cur.id, cur.version)](register, portfolio, pol, *args)
        b = core.METHODS[(m.id, m.version)](register, portfolio, pol, *args)
        out.append(
            {
                "method": m.id,
                "current": cur.version,
                "shadow": m.version,
                "differences": differences(a, b),
            }
        )
    return out


def main() -> int:
    from generator.policy import load_policy, load_portfolio, load_register

    runs = shadow_runs(load_register(), load_portfolio(), load_policy())
    print(json.dumps(runs, indent=1) if runs else "no method version is in shadow")
    return 0


if __name__ == "__main__":
    sys.exit(main())
