"""The companion's pinned copies (40-BREADTH.md step 9): the register, the policy and the served projection of the
reference portfolio, written under `companion/pinned/` by a strategy release and refreshed only there.

The adopter's companion mirrors these copies to the companion repository in step 12 (never the live files, a rendered
view or a fixture), and recognizes the reference portfolio by digest alone: `pins.json` records the sha256 of each
source as it stood at the pin and of each copy written, so a run passing either file is the reference run and every
other portfolio is an adopter's, whatever its estate says (3c's judgment, S2). The portfolio's copy is the served
projection (the approved nodes, every withheld node removed; 40-BREADTH.md step 2), filtered as the served views are.

Run from the repository root: python3 docs/design/enterprise-strategy-layer/generator/pin_companion.py --write
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

LAYER = Path(__file__).resolve().parent.parent
ROOT = LAYER.parents[2]
if str(LAYER) not in sys.path:
    sys.path.insert(0, str(LAYER))

REL = "docs/design/enterprise-strategy-layer"
PINNED = f"{REL}/companion/pinned"
SOURCES = {
    "register": f"{REL}/register.yaml",
    "policy": f"{REL}/policy.yaml",
    "portfolio": f"{REL}/portfolio.example.yaml",
}


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def projected_portfolio(root: Path = ROOT) -> str:
    """The reference portfolio as the served views may show it, dumped as YAML: the approved nodes, every withheld node
    removed, the approvals themselves left out (an adopter's portfolio needs none), and the initiatives the projection
    holds off the board left out, since the served board ranks none of them (40-BREADTH.md step 2, S3)."""
    from generator import served
    from generator.policy import load_policy, load_portfolio, load_register

    reg = load_register(root / SOURCES["register"])
    pf = load_portfolio(root / SOURCES["portfolio"])
    pol = load_policy(root / SOURCES["policy"])
    p = served.project(reg, pf, pol)
    data = served.dumped(p.portfolio)
    data[
        "approvals"
    ] = []  # the file-level approval stays (its model requires it); the node approvals are the live file's
    # an initiative the projection holds off the board (costed through a carried capability's value, or its added
    # effort on a carried capability's loops) is served with its reason and never ranked; the companion ranks what the
    # copy plans, so its plan and the decision-log entries that name it are left out, as the served board leaves them
    off = set(p.off_board)
    data["initiatives"] = [i for i in data["initiatives"] if i["id"] not in off]
    data["decision_log"] = [e for e in data["decision_log"] if e.get("initiative") not in off]
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def _commit(root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build(root: Path = ROOT) -> dict[str, bytes]:
    """Each pinned copy's bytes by its file name under companion/pinned/, and pins.json last."""
    copies = {
        "register.yaml": (root / SOURCES["register"]).read_bytes(),
        "policy.yaml": (root / SOURCES["policy"]).read_bytes(),
        "portfolio.example.yaml": projected_portfolio(root).encode("utf-8"),
    }
    pins = {
        "schema": 1,
        "commit": _commit(root),
        "written_by": "docs/design/enterprise-strategy-layer/generator/pin_companion.py",
    }
    for name, rel in SOURCES.items():
        copy = {
            "register": "register.yaml",
            "policy": "policy.yaml",
            "portfolio": "portfolio.example.yaml",
        }[name]
        pins[name] = {
            "source": rel,
            "source_sha256": sha256_of((root / rel).read_bytes()),
            "copy": f"{PINNED}/{copy}",
            "copy_sha256": sha256_of(copies[copy]),
        }
    pins["portfolio"]["projection"] = (
        "the served projection: the approved nodes, every withheld node removed, the approvals left out, and the "
        "initiatives the projection holds off the board left out with the decision-log entries that name them"
    )
    copies["pins.json"] = (json.dumps(pins, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    return copies


def write(root: Path = ROOT) -> Path:
    out = root / PINNED
    out.mkdir(parents=True, exist_ok=True)
    for name, data in build(root).items():
        (out / name).write_bytes(data)
    return out


def current(root: Path = ROOT) -> list[str]:
    """The pinned files whose bytes differ from a fresh build (the digest of the clock-free parts): what a release
    must rewrite. pins.json is compared without its commit."""
    out = []
    fresh = build(root)
    for name, data in fresh.items():
        path = root / PINNED / name
        if not path.exists():
            out.append(f"{name} is absent")
            continue
        held = path.read_bytes()
        if name == "pins.json":
            a, b = json.loads(held), json.loads(data)
            a.pop("commit", None)
            b.pop("commit", None)
            if a != b:
                out.append("pins.json records other digests")
        elif held != data:
            out.append(f"{name} differs from its source")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="pin_companion.py")
    ap.add_argument("--write", action="store_true", help=f"write the copies under {PINNED}")
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    if a.write:
        print(f"wrote {write(a.root).relative_to(a.root)}")
        return 0
    stale = current(a.root)
    print("\n".join(stale) if stale else "the pinned copies are current")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
