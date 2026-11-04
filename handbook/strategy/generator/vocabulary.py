"""The site vocabulary the adopter's companion reads in place of the site files (40-BREADTH.md step 9).

The gates read four files outside the layer for the vocabulary a register is held to: the competency map (jobs and
competencies), mastery.yaml (the phases), pages.json (the pages a hand-off may name) and the ladder charter (its rungs).
The companion never reads a site file, so each strategy release writes those four into one file here,
`companion/vocabulary.json`, with the sha256 of each source it was written from; the strategy check lists the file
stale when a source has since changed (GATE-13, 13.9), never refusing, so a peer's new job or page fails no push.

Run from the repository root: python3 docs/design/enterprise-strategy-layer/generator/vocabulary.py --write
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

LAYER = Path(__file__).resolve().parent.parent
ROOT = LAYER.parents[2]
if str(LAYER) not in sys.path:
    sys.path.insert(0, str(LAYER))

SOURCES = {
    "competency_map": "deploy/privatecloudarchitect/site/competency-map.yaml",
    "mastery": "deploy/privatecloudarchitect/site/mastery.yaml",
    "pages": "deploy/privatecloudarchitect/site/src/pages.json",
    "ladder": "docs/design/standup-dependency-ladder/00-CHARTER.md",
}
OUT = "docs/design/enterprise-strategy-layer/companion/vocabulary.json"
SCHEMA = 1


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root: Path = ROOT) -> dict:
    """The vocabulary as the gates' Sources hold it: the jobs and competencies as the map lists them, each phase's id
    and name, each page's path and title (every page the site builds is public), the ladder's rungs; and the digest
    of each source."""
    from generator import gates

    comp = gates._comp_map(
        yaml.safe_load((root / SOURCES["competency_map"]).read_text(encoding="utf-8"))
    )
    phases = yaml.safe_load((root / SOURCES["mastery"]).read_text(encoding="utf-8"))["phases"]
    pages = gates._pages((root / SOURCES["pages"]).read_text(encoding="utf-8"))
    rungs = gates._rungs((root / SOURCES["ladder"]).read_text(encoding="utf-8"))
    return {
        "schema": SCHEMA,
        "written_from": {
            name: {"path": rel, "sha256": sha256_of(root / rel)} for name, rel in SOURCES.items()
        },
        "jobs": comp["jobs"],
        "competencies": comp["competencies"],
        "phases": [{"id": p["id"], "name": p.get("name")} for p in phases],
        "pages": [
            {"path": path, "title": page.get("title")} for path, page in sorted(pages.items())
        ],
        "rungs": sorted(rungs, key=lambda r: int(r[1:])),
    }


def write(root: Path = ROOT) -> Path:
    out = root / OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(root), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="vocabulary.py")
    ap.add_argument("--write", action="store_true", help=f"write {OUT}")
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    if a.write:
        print(f"wrote {write(a.root).relative_to(a.root)}")
        return 0
    sys.stdout.write(json.dumps(build(a.root), indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
