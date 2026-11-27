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
import re
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
    "glossary": "docs/design/enterprise-strategy-layer/00-CHARTER.md",
}
# A source read for one section only is digested on that section, found by its heading, so an edit elsewhere in the
# file never lists the vocabulary stale (the charter changes often; its glossary rarely).
SECTIONS = {"glossary": "Glossary"}
# The terms the strategy hub's "How to read these pages" block defines, in its order (the educator review, S5). Each
# must be an entry of the charter's glossary, its one writer; the committed and aspirational target kinds wait on the
# layer's own decision of what separates them.
GLOSSARY_TERMS = ["Ledger", "Declaration", "Drift read", "Adoption level", "Adoption bar", "Illustrative", "Instrument",
                  "Cost of delay", "Conversion rate", "Common unit (cu)", "CD3", "Enabler", "Chain rule"]
_ENTRY = re.compile(r"^- \*\*(?P<term>[^*]+)\*\*: (?P<text>\S.*)$")
_CONTINUED = re.compile(r"^  \S")
_SECTION_REF = re.compile(r"\s*\((?:sections?|section) [0-9]+(?:\.[0-9]+)*(?:(?:, | and )[0-9]+(?:\.[0-9]+)*)*\)")
OUT = "docs/design/enterprise-strategy-layer/companion/vocabulary.json"
SCHEMA = 1


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(text: str, title: str) -> str:
    """The section of a Markdown file whose heading reads `title` (its number aside), from that heading to the next
    heading of the same level; never a line range, so the section moves with the file."""
    lines = text.splitlines(keepends=True)
    head = re.compile(r"^(#{1,6}) (?:[0-9]+(?:\.[0-9]+)*\.? )?" + re.escape(title) + r"\s*$")
    for i, line in enumerate(lines):
        m = head.match(line)
        if m:
            level = len(m.group(1))
            end = next((j for j in range(i + 1, len(lines)) if re.match(r"^#{1,%d} " % level, lines[j])), len(lines))
            return "".join(lines[i:end])
    raise ValueError(f"no heading reads {title!r}")


def digest(name: str, path: Path) -> str:
    """A source's sha256: of its section for a source read for one section only (SECTIONS), else of the whole file."""
    if name in SECTIONS:
        return hashlib.sha256(section(path.read_text(encoding="utf-8"), SECTIONS[name]).encode("utf-8")).hexdigest()
    return sha256_of(path)


def plain(text: str) -> str:
    """A glossary definition for a reader: its section references dropped, and the three kinds of Markdown it uses
    (bold, code and links) as their text."""
    text = _SECTION_REF.sub("", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def glossary(section_text: str) -> dict[str, str]:
    """Every entry of a glossary section as {term: definition}, strictly: after the heading, each non-blank line is an
    entry, `- **Term**: definition`, or that entry's continuation indented two spaces; any other line fails the parse
    rather than dropping out. A horizontal rule is allowed only as the section's last line."""
    out: dict[str, list[str]] = {}
    term = None
    body = section_text.splitlines()[1:]
    last = max((i for i, ln in enumerate(body) if ln.strip()), default=-1)
    for n, line in enumerate(body, start=2):
        if not line.strip():
            continue
        if re.fullmatch(r"-{3,}", line.strip()) and n - 2 == last:
            continue  # the rule that closes a section, as the charter writes one before its next heading
        m = _ENTRY.match(line)
        if m:
            term = m.group("term").strip()
            if term in out:
                raise ValueError(f"glossary line {n}: {term!r} is defined twice")
            out[term] = [m.group("text")]
        elif _CONTINUED.match(line) and term:
            out[term].append(line.strip())
        else:
            raise ValueError(f"glossary line {n} is neither an entry nor its continuation: {line!r}")
    return {k: plain(" ".join(v)) for k, v in out.items()}


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
    entries = glossary(section((root / SOURCES["glossary"]).read_text(encoding="utf-8"), SECTIONS["glossary"]))
    missing = [t for t in GLOSSARY_TERMS if t not in entries]
    if missing:
        raise ValueError(f"the charter's glossary has no entry for {missing}; the hub block defines only its terms")
    return {
        "schema": SCHEMA,
        "written_from": {
            name: {"path": rel, "sha256": digest(name, root / rel), **({"section": SECTIONS[name]} if name in SECTIONS else {})}
            for name, rel in SOURCES.items()
        },
        "jobs": comp["jobs"],
        "competencies": comp["competencies"],
        "phases": [{"id": p["id"], "name": p.get("name")} for p in phases],
        "pages": [
            {"path": path, "title": page.get("title")} for path, page in sorted(pages.items())
        ],
        "rungs": sorted(rungs, key=lambda r: int(r[1:])),
        "glossary": [{"term": t, "definition": entries[t]} for t in GLOSSARY_TERMS],
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
