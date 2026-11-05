"""The gates of the charter's section 8, as a library (30-GATES.md step 3).

One function per gate. Each judges the files as plain data, not through the typed models, so a file the models would
refuse is still judged clause by clause and every finding names its line. Each returns findings, never a bare yes or
no: a finding names the file, the line, the clause it breaks and the edit that fixes it, so whoever trips a gate fixes
it in place without reading this file (the charter's coupling rule, section 8). A gate whose input is absent says
`not_covered`, never passed (P-027).

GATE-13 is the date gate. It is the one gate that reads a calendar, so it lives in check.py, takes the day it judges as
an argument, and runs only in the strategy check, never in a pre-push. Every bound a gate needs is read through the
policy loader (GATE-14).

Run from the repository root: docs/design/enterprise-strategy-layer/generator/gates.py, which `make strategy-gates`
runs in every pre-push: every structural gate, file-only, its time printed (agreed with f8 and 3c, 2026-10-28).
"""

from __future__ import annotations

import ast
import html
import importlib.util
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import ValidationError

LAYER = Path(__file__).resolve().parent.parent
ROOT = LAYER.parents[2]
SITE = ROOT / "deploy" / "privatecloudarchitect" / "site"
COMPANION = ROOT / "deploy" / "privatecloudarchitect" / "companion"
STAGING = COMPANION / "staging"
LADDER = ROOT / "docs" / "design" / "standup-dependency-ladder" / "00-CHARTER.md"

if str(LAYER) not in sys.path:
    sys.path.insert(0, str(LAYER))

from generator import (  # noqa: E402
    core,
    models,
    scrublist,
)
from generator.migrate import upgrade  # noqa: E402
from generator.policy import DataLoader, Loaded, check_vocabularies, load_data  # noqa: E402
from generator.render import GENERATED, stamp_shaped, stampless  # noqa: E402

# ── the clauses of section 8, each with the gate it belongs to ──────────────────────────────────────────────────────
# Each text is a phrase of the gate's row in the charter's section 8, verbatim; the gates' test reads the row and
# fails when a phrase is not in it or the row says more than its phrases (anything left beyond connecting words), and
# when a clause has no test that injects its failure. So the table and the gates cannot drift apart.
CLAUSES: dict[str, tuple[str, str]] = {
    "1.1": ("GATE-1", "a capability without exactly one accountable role"),
    "1.2": ("GATE-1", "an initiative without exactly one sponsor role"),
    "1.3": ("GATE-1", "a declaration without exactly one writer"),
    "1.4": ("GATE-1", "a role the register does not define"),
    "1.5": ("GATE-1", "in a portfolio, two departments for one role in one scope"),
    "2.1": ("GATE-2", "a capability with no job and no `practice`"),
    "2.2": ("GATE-2", "with `foundation` as a job"),
    "2.3": ("GATE-2", "with a job not in `competency-map.yaml`"),
    "2.4": (
        "GATE-2",
        "a `taught_by` with no non-foundation competency, unless `untaught` names the capability's own territory and "
        "the lane it was sent to",
    ),
    "2.5": ("GATE-2", "a `taught_by` competency that is unpublished"),
    "2.6": (
        "GATE-2",
        "that is not a foundation competency and serves none of the capability's jobs",
    ),
    "2.7": ("GATE-2", "a `links` page not in `deploy/privatecloudarchitect/site/src/pages.json`"),
    "2.8": ("GATE-2", "an `untaught` entry with no lane or no message on record"),
    "2.9": ("GATE-2", "a capability of the outside model the catalog's map does not place"),
    "2.10": ("GATE-2", "a cross-check capability neither mapped nor reasoned"),
    "2.11": (
        "GATE-2",
        "a placement in the register that names no capability or planned capability the register holds",
    ),
    "2.12": ("GATE-2", "an untaught placement that names no lane"),
    "2.13": ("GATE-2", "a placement out of scope with no reason"),
    "2.14": (
        "GATE-2",
        "a practice capability, keyed to the outside model, that names no hand-off to a capability keyed to a job",
    ),
    "2.15": (
        "GATE-2",
        "a placement whose proposed competency serves another job than the one it proposes",
    ),
    "2.16": (
        "GATE-2",
        "a practice capability whose `practice` the catalog's map does not place on it, or a practice placement whose "
        "capability names no `practice`",
    ),
    "2.17": ("GATE-2", "a practice capability that names a job"),
    "3.1": ("GATE-3", "an empty value or sustain ledger"),
    "3.2": (
        "GATE-3",
        "a value without a business objective it serves, a category, a measure, a unit and an instrument",
    ),
    "3.3": ("GATE-3", "a speed value without its paired stability measure"),
    "3.4": ("GATE-3", "an instrument that names a companion not in staging"),
    "3.5": ("GATE-3", "a `not_covered` instrument on a capability `strategy-pages` publishes"),
    "3.6": (
        "GATE-3",
        "or on any capability while `instrument-gaps` reads `wait` (a capability `strategy-pages` does not publish is "
        "listed, not refused, while it reads `carry`)",
    ),
    "4.1": (
        "GATE-4",
        "a guidance or planning assessment without its date, tiers, evidence and confidence",
    ),
    "5.1": ("GATE-5", "an empty establish ledger"),
    "5.2": (
        "GATE-5",
        "a prerequisite that does not resolve to a step, a capability or a planned capability (including a `step:` "
        "that names no earlier step)",
    ),
    "5.3": ("GATE-5", "a cycle among prerequisites"),
    "5.4": ("GATE-5", "a `ladder:` rung on a capability whose scope is not `workload`"),
    "6.1": (
        "GATE-6",
        "an external citation not verified (fetched, version and date recorded, BLOCK-010)",
    ),
    "6.2": ("GATE-6", "a forecast not labelled as one"),
    "7.1": ("GATE-7", "an estate identifier or an estate's state in the register"),
    "7.2": ("GATE-7", "private portfolio data in a public view"),
    "7.3": ("GATE-7", "an `illustrative` value unlabelled in a public view"),
    "7.4": ("GATE-7", "present in an adopter's portfolio"),
    "7.5": ("GATE-7", "an `input` value without who supplied it"),
    "7.6": ("GATE-7", "a required node of the reference portfolio that no approval covers"),
    "7.7": ("GATE-7", "an approval that names a node no longer present (listed, not refused)"),
    "8.1": (
        "GATE-8",
        "in a portfolio, an initiative whose planning tier is nearer than the tier of the initiative that establishes "
        "one of its prerequisites",
    ),
    "8.2": ("GATE-8", "`committed` ahead of its prerequisites (section 5.7)"),
    "9.1": ("GATE-9", "a generated page that is not what the generator emits"),
    "9.2": ("GATE-9", "that fails the voice and figure-pattern rules chapters meet"),
    "10.1": (
        "GATE-10",
        "a typed fact in a view that the register or a portfolio holds (a view renders, it never restates)",
    ),
    "11.1": (
        "GATE-11",
        "a trigger event that re-opened nothing, spawned nothing and is not marked `no_change`",
    ),
    "11.2": ("GATE-11", "is marked `no_change` and did either"),
    "11.3": ("GATE-11", "an initiative whose `from_event` names no event"),
    "11.4": ("GATE-11", "an initiative whose `from_scan` names no recorded scan"),
    "11.5": ("GATE-11", "a scan area whose `found` names no signal"),
    "11.6": ("GATE-11", "a signal whose `watch` names no watch entry"),
    "11.7": (
        "GATE-11",
        "a driver stress that names no written capability, or a planned stress that names neither a planned nor a "
        "written one",
    ),
    "11.8": ("GATE-11", "an initiative whose `from_event` names an event that did not spawn it"),
    "11.9": ("GATE-11", "a trigger event whose `driver` names no driver"),
    "11.10": ("GATE-11", "a trigger event whose `spawned` names no initiative"),
    "12.1": ("GATE-12", "a hand-off to a page for a prerequisite the register marks `untaught`"),
    "12.2": ("GATE-12", "to a page that is not published"),
    "12.3": ("GATE-12", "an untaught hand-off with no lane or no message on record"),
    "13.1": ("GATE-13", "an assessment past its derived review-by date with no newer assessment"),
    "13.2": ("GATE-13", "an expired exception not counted as drift"),
    "13.3": (
        "GATE-13",
        "a watch entry not read within its interval (an entry marked `pending_source` or `optional` is listed, not "
        "refused)",
    ),
    "13.4": ("GATE-13", "the strategy check's own last recorded run older than its interval"),
    "13.5": (
        "GATE-13",
        "a lane `lanes.yaml` names apart from the open registry's lane table (listed, not refused)",
    ),
    "13.6": ("GATE-13", "a job no written capability serves (listed, not refused)"),
    "13.7": (
        "GATE-13",
        "an untaught placement of the map whose message to its lane is not on record (listed, not refused)",
    ),
    "13.8": (
        "GATE-13",
        "a watch read whose new candidates no trigger event or signal rules on within the entry's interval",
    ),
    "13.9": (
        "GATE-13",
        "the companion's vocabulary file absent or written from a site file that has since changed (listed, not refused)",
    ),
    "14.1": (
        "GATE-14",
        "in the strategy layer's code (`docs/design/enterprise-strategy-layer/generator/`, which holds the generator, "
        "the gates, the strategy check and the drift adapters; `docs/design/enterprise-strategy-layer/instrument/`; "
        "`docs/design/enterprise-strategy-layer/schedule/` (planned, 30-GATES.md step 5); and the adopter's "
        "companion, its path named when PH4 creates it), a duration or identifier `policy.yaml` defines written "
        "outside the policy loader (a numeric value cannot be told from an unrelated literal, so the "
        "parameter-change tests hold those)",
    ),
    "14.2": ("GATE-14", "a view that types a value `policy.yaml` holds"),
    "14.3": (
        "GATE-14",
        "a policy entry without its value, decisions, version, effective date, change class and readers",
    ),
    "14.4": ("GATE-14", "a value in a field a vocabulary covers that the vocabulary does not list"),
    "14.5": ("GATE-14", "a generated output without its provenance"),
    "14.6": ("GATE-14", "a method version without its pinned definition and golden fixture"),
    "14.7": (
        "GATE-14",
        "a change to the typed models of a file whose structural fingerprint no longer matches the one pinned for "
        "its schema version, without a new version and a migration (the models and their lock are written in PH2, "
        "as P-025 pins `spineVersion` and D-053 its structure lock)",
    ),
    "14.8": (
        "GATE-14",
        "an estate's override of an entry not marked `overridable`, or marked `one_way`, or without its decision",
    ),
    "14.9": (
        "GATE-14",
        "a node of the portfolio under a path the run's import supplies, or an import that supplies a field the "
        "portfolio does not import",
    ),
    "15.1": ("GATE-15", "a register that names no reader"),
    "15.2": ("GATE-15", "a door's strategy path that `strategy-pages` does not publish"),
    "15.3": (
        "GATE-15",
        "a door's handbook path that `deploy/privatecloudarchitect/site/src/pages.json` does not serve",
    ),
    "15.4": (
        "GATE-15",
        "the feed at `deploy/privatecloudarchitect/site/src/strategy-front-door.json` that is not what the "
        "generator emits, or absent",
    ),
}

STRUCTURAL = tuple(f"GATE-{n}" for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15))

# The strategy layer's code, as GATE-14's first clause names it. A path joins this list in the change that creates it.
CODE = (
    "docs/design/enterprise-strategy-layer/generator",
    "docs/design/enterprise-strategy-layer/instrument",
    "docs/design/enterprise-strategy-layer/schedule",
    "docs/design/enterprise-strategy-layer/companion",  # the adopter's companion (40-BREADTH.md step 9)
)
LOADER_FILES = ("policy.py", "models.py")  # where the policy is read and shaped, not used
LOADER_CALLS = {"get", "selected", "entry", "measure_method", "vocabulary", "method"}
SELF_NAMING = {"implements", "run_method"}


@dataclass(frozen=True)
class Finding:
    """What a gate found, at its file and line, with the clause and the edit. A finding is refused unless `listed`: a
    listed one is shown and recorded and never fails a gate, as a clause's own words say it is listed, not refused
    (40-BREADTH.md step 2)."""

    clause: str
    file: str
    line: int | None
    what: str
    edit: str
    listed: bool = False

    @property
    def gate(self) -> str:
        return CLAUSES[self.clause][0]

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        if self.listed:
            return one_line(f"{where}: listed: {self.gate} ({self.clause}) {self.what}")
        return one_line(f"{where}: {self.gate} ({self.clause}) {self.what}; {self.edit}")


UNJUDGED_EDIT = "fix what the message names; a gate that has not judged has not passed (P-027)"


def one_line(text: str) -> str:
    """A failure as one line: a cause's own line breaks and runs of space (a parser's or a model's message) closed up,
    so each failure is one line in 3c's form, whatever raised it."""
    return " ".join(text.split())


@dataclass
class Result:
    gate: str
    state: str  # passed | refused | not_covered
    findings: list[Finding]  # the refused ones; they alone decide the state
    why: str | None = (
        None  # not covered: the input that was absent; refused: the clauses left unjudged, and why
    )
    at: tuple[str, int] | None = None  # the file and line `why` points at, where the edit is made
    edit: str | None = None
    listed: list[Finding] = field(
        default_factory=list
    )  # shown and recorded beside the state, never refused

    def listed_lines(self) -> list[str]:
        """Each listed item in its one form, `file:line: listed: GATE-n (clause) what`."""
        return [str(x) for x in self.listed]

    def failures(self) -> list[str]:
        """Each failure in its one form, `file:line`, the rule and the edit (3c's condition, 30-GATES.md section 2):
        each finding of a refusal, the clauses a refusal left unjudged, and a gate that is not covered, a line each."""
        out = [str(f) for f in self.findings]
        if self.state == "passed" or not self.why:
            return out
        file, line = self.at or ("docs/design/enterprise-strategy-layer/generator/gates.py", 1)
        what = (
            "not covered" if self.state == "not_covered" else "refused, and clauses left unjudged"
        )
        return [
            *out,
            one_line(
                f"{file}:{line}: {self.gate} {what}: {self.why}; {self.edit or UNJUDGED_EDIT}"
            ),
        ]


# ── the sources a gate reads ────────────────────────────────────────────────────────────────────────────────────────
class Doc:
    """A YAML file as data, with the line of any path in it."""

    def __init__(self, path: str, text: str) -> None:
        self.path, self.text = path, text
        self.data = load_data(text)
        self._node: Any = None

    @classmethod
    def read(cls, rel: str, root: Path = ROOT) -> Doc:
        """A data file read and parsed, or a SourceError at the file and the line the read or the parser stopped at."""
        text = read_text(root / rel, rel)
        try:
            return cls(rel, text)
        except (
            Exception
        ) as e:  # a parse that fails is the file's, named at its line, never at the parser's code
            raise SourceError(f"{rel}: {type(e).__name__}: {e}", at=(rel, _parse_line(e))) from e

    def line(self, *keys: str | int) -> int | None:
        if self._node is None:
            self._node = yaml.compose(self.text, Loader=DataLoader)
        node, line = self._node, None
        if node is not None:
            line = node.start_mark.line + 1
        for k in keys:
            nxt = None
            if isinstance(node, yaml.MappingNode):
                nxt = next((v for kn, v in node.value if kn.value == k), None)
            elif (
                isinstance(node, yaml.SequenceNode)
                and isinstance(k, int)
                and 0 <= k < len(node.value)
            ):
                nxt = node.value[k]
            if nxt is None:
                break
            node, line = nxt, nxt.start_mark.line + 1
        return line


def _model_line(doc, e: BaseException) -> int:
    """The line of the first field a model refused, where the error names its location in the file, else line 1."""
    if isinstance(e, ValidationError) and e.errors():
        loc = [x for x in e.errors()[0]["loc"] if isinstance(x, str | int)]
        try:
            return doc.line(*loc) or 1
        except (
            Exception
        ):  # a location the file does not hold as written (a migrated key) points at the file
            return 1
    return 1


class SourceError(OSError):
    """A source the gates read that is missing or cannot be parsed, named by its path, and by the line the parser
    stopped at where it says one (`at`)."""

    def __init__(self, message: str, at: tuple[str, int] | None = None) -> None:
        super().__init__(message)
        self.at = at

    def failure(
        self,
        what: str = "every structural gate not covered: a source could not be read",
        edit: str = "fix the file so it reads and parses through its model",
    ) -> str:
        """The failure in its one form: the file and line, what it leaves undone (every structural gate not covered,
        unless the caller says another), and the edit."""
        file, line = self.at or (str(self).split(": ", 1)[0], 1)
        return one_line(f"{file}:{line}: {what} ({self}); {edit}")


def read_text(path: Path, rel: str) -> str:
    """A file's text, or a SourceError that names it at the line the read stopped at: a byte that is not UTF-8 at the
    line it sits on, a missing or unreadable file at its first."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        line = path.read_bytes()[: e.start].count(b"\n") + 1
        raise SourceError(f"{rel}: {type(e).__name__}: {e}", at=(rel, line)) from e
    except OSError as e:
        raise SourceError(f"{rel}: {type(e).__name__}: {e}", at=(rel, 1)) from e


def _parse_line(e: BaseException) -> int:
    """The line a parser stopped at, where its error says one (YAML's mark, JSON's lineno), else the file's first."""
    mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
    if mark is not None:
        return mark.line + 1
    return getattr(e, "lineno", None) or 1


def _where(e: BaseException) -> tuple[str, int]:
    """Where a failure points: a SourceError at the file and line it names, any other error at the repository's line it
    was raised at."""
    return e.at if isinstance(e, SourceError) and e.at else _raised_at(e)


def _raised_at(e: BaseException) -> tuple[str, int]:
    """Where an error was raised in the repository's own code, the innermost such frame: the line a gate that raised
    names. A frame outside the repository, or in an environment or a library inside it (a `.venv`, site-packages), is
    never the repository's code, so the frame that called into it is named."""
    import traceback

    for frame in reversed(traceback.extract_tb(e.__traceback__)):
        if frame.filename.startswith("<") or not Path(frame.filename).is_file():
            continue  # a frozen or generated module (`<frozen codecs>`) is no file of the repository's
        try:
            rel = Path(frame.filename).resolve().relative_to(ROOT).as_posix()
        except ValueError:
            continue
        if not any(
            part.startswith(".") or part in ("site-packages", "node_modules")
            for part in rel.split("/")[:-1]
        ):
            return rel, frame.lineno or 1
    return "docs/design/enterprise-strategy-layer/generator/gates.py", 1


def _shaped(kind: str, doc: Doc) -> Doc:
    """A data file with every top-level key its model requires, read after migration, so a file cut down to its schema
    line is refused as a source, by its name, before any gate finds nothing to judge in it and passes."""
    if not isinstance(doc.data, dict):
        raise ValueError("empty, or not a mapping")
    model = models.MODELS[kind]
    data = upgrade(kind, doc.data)[0] if kind in models.SCHEMA_VERSIONS else doc.data
    missing = [
        f.alias or k
        for k, f in model.model_fields.items()
        if f.is_required() and (f.alias or k) not in data
    ]
    if missing:
        raise ValueError(f"lacks the top-level keys its model requires: {', '.join(missing)}")
    return doc


def _comp_map(raw) -> dict:
    """The competency map in the shape the gates read: a mapping whose `competencies` and `jobs` are lists of entries
    with ids, so an empty or misshapen map is refused as a source, by its name, before any gate judges it."""
    if not isinstance(raw, dict):
        raise ValueError("empty, or not a mapping")
    for key in ("competencies", "jobs"):
        items = raw.get(key)
        if not isinstance(items, list) or not all(isinstance(x, dict) and "id" in x for x in items):
            raise ValueError(f"`{key}` is not a list of entries with ids")
    return raw


def _rungs(text: str) -> set[str]:
    """The ladder's rungs; a charter that names none is a source no gate can read, never a ladder with no rungs."""
    found = set(re.findall(r"\bR\d+\b", text))
    if not found:
        raise ValueError("names no rung (R1, R2, ...)")
    return found


def _pages(text: str) -> dict[str, dict]:
    """pages.json's entries by path; a file that holds no `pages` list of entries with a path is a source no gate can
    read, named at its first line (a parse error at the parser's)."""
    data = json.loads(text)
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list) or not all(isinstance(x, dict) and "path" in x for x in pages):
        raise ValueError("holds no `pages` list of entries with a path")
    return {x["path"]: x for x in pages}


def _views(rendered: Path, root: Path) -> dict[str, str]:
    """The committed views; a folder that holds none is a source no gate can read, never a site with no pages."""
    _need_dir(rendered)
    found = {
        str(x.relative_to(root)): read_text(x, str(x.relative_to(root)))
        for x in sorted(rendered.glob("*.html"))
    }
    if not found:
        raise ValueError("holds no rendered view")
    return found


def _need_dir(path: Path) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"{path} is not a folder")


@dataclass
class Sources:
    register: Doc
    portfolio: Doc
    policy: Doc
    comp_map: dict
    pages: dict[str, dict]
    phases: set[str]
    rungs: set[str]
    views: dict[str, str] = field(default_factory=dict)  # repo-relative path: the page as committed
    catalog_map: Doc | None = None  # catalog-map.yaml (40-BREADTH.md step 3)
    outside_model: Doc | None = (
        None  # research/outside-model.yaml, the sources' named capabilities (step 1)
    )
    front_door: str | None = (
        None  # the committed feed's text, deploy/.../src/strategy-front-door.json (GATE-15)
    )
    root: Path = ROOT
    git: Path | None = None  # the checkout that resolves a pinned commit; the files' own when None
    # a run's import (step 9): each field `ownership.imports` names, with the address prefixes it supplies (served.address_of);
    # None where no import is passed, and 14.9 is then not judged
    imports: dict[str, list[str]] | None = None
    # the scrub list a run passed (scrublist.kill_list_from), used by every leak check and every scrubbed result of
    # this run; the publisher's own list, read as data from this repository, when None (a companion run in the mirror
    # has no publisher, and reaches for no file it was not passed)
    lists: tuple[re.Pattern, tuple[str, ...]] | None = None
    # the clauses this run judges: every clause when None (the repository's run); a companion run passes the clauses
    # its split covers, and a gate then skips the reads of a clause it does not judge (a repository file a run does not
    # hold), so one clause's absent input never leaves the gate's other clauses unjudged; the split reports the skipped
    # clause not covered, never passed
    clauses: frozenset[str] | None = None

    def judges(self, clause: str) -> bool:
        return self.clauses is None or clause in self.clauses

    @classmethod
    def read(cls, root: Path = ROOT, portfolio: str | None = None) -> Sources:
        rel = "docs/design/enterprise-strategy-layer"
        site = "deploy/privatecloudarchitect/site"
        rendered = root / rel / "generator" / "rendered"

        def source(path: str, parse):
            """One source read and parsed, or a SourceError that names it: no gate judges a file it could not read."""
            try:
                parsed = parse(path)
            except (
                SourceError
            ):  # a read that names its own file and line (one view of the folder) keeps them
                raise
            except Exception as e:  # any failure to read or parse a source names it; no gate judges what it could not read
                raise SourceError(
                    f"{path}: {type(e).__name__}: {e}", at=(path, _parse_line(e))
                ) from e
            return parsed

        text = lambda p: read_text(root / p, p)  # noqa: E731
        return cls(
            register=source(
                f"{rel}/register.yaml", lambda p: _shaped("register", Doc.read(p, root))
            ),
            portfolio=source(
                portfolio or f"{rel}/portfolio.example.yaml",
                lambda p: _shaped("portfolio", Doc.read(p, root)),
            ),
            policy=source(f"{rel}/policy.yaml", lambda p: _shaped("policy", Doc.read(p, root))),
            comp_map=source(
                f"{site}/competency-map.yaml", lambda p: _comp_map(yaml.safe_load(text(p)))
            ),
            pages=source(f"{site}/src/pages.json", lambda p: _pages(text(p))),
            phases=source(
                f"{site}/mastery.yaml",
                lambda p: {x["id"] for x in yaml.safe_load(text(p))["phases"]},
            ),
            rungs=source(str(LADDER.relative_to(ROOT)), lambda p: _rungs(text(p))),
            views=source(
                str(rendered.relative_to(root)),
                lambda p: _views(rendered, root),
            ),
            catalog_map=source(
                f"{rel}/catalog-map.yaml", lambda p: _shaped("catalog_map", Doc.read(p, root))
            ),
            outside_model=source(
                f"{rel}/research/outside-model.yaml",
                lambda p: _shaped("outside_model", Doc.read(p, root)),
            ),
            # the feed as committed; absent is a finding (15.4), never a source error
            front_door=source(FRONT_DOOR_REL, lambda p: text(p) if (root / p).is_file() else None),
            root=root,
        )

    def loaded(self) -> Loaded | None:
        """The policy as the portfolio's estate runs it (each override of an overridable entry applied, so every gate
        and the check read one view), or None when it does not load (GATE-14's third clause says why). Loaded once
        per run, as the report and the views are: the gates ask for it per finding, and at the catalog's full size
        GATE-3 asked hundreds of times (step 4, batch 2)."""
        return self._once_for("loaded", (self.policy, self.portfolio), self._load)

    def _once_for(self, name: str, docs: tuple, compute):
        """A value computed once per run from the named documents, and again when a different document object stands
        in any of their places: a test derives a changed source set by copying this one and replacing a document, and
        the copy shares this cache."""
        once = self.__dict__.setdefault("_once", {})
        key = tuple(id(d) for d in docs)
        if once.get((name, "for")) != key:
            once[name], once[(name, "for")] = compute(), key
        return once[name]

    def _load(self) -> Loaded | None:
        # any failure is "does not load", never a crash, and the reason names which file holds the cause
        try:
            pol = Loaded(models.Policy.model_validate(upgrade("policy", self.policy.data)[0]))
        except Exception as e:
            self.unloaded = f"{self.policy.path}: {type(e).__name__}: {e}"
            self.unloaded_at = (self.policy.path, _model_line(self.policy, e))
            return None
        try:  # an override not shaped as one is the portfolio's, not the policy's
            return pol.for_estate((self.portfolio.data.get("policy") or {}).get("overrides") or [])
        except Exception as e:
            self.unloaded = f"{self.portfolio.path}, its policy overrides: {type(e).__name__}: {e}"
            self.unloaded_at = (
                self.portfolio.path,
                self.portfolio.line("policy", "overrides") or 1,
            )
            return None

    def typed(self) -> tuple[models.Register, models.Portfolio, Loaded] | None:
        pol = self.loaded()
        typed = []
        for name, model, doc in (
            ("register", models.Register, self.register),
            ("portfolio", models.Portfolio, self.portfolio),
        ):
            try:
                typed.append(model.model_validate(upgrade(name, doc.data)[0]))
            except ValidationError as e:  # the file, the field and the value the model refused
                self.untyped = f"{doc.path}: " + "; ".join(
                    f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                    for err in e.errors()[:3]
                )
                self.untyped_at = (doc.path, _model_line(doc, e))
                return None
            except (
                Exception
            ) as e:  # any other failure in a model or its migration is "does not load" too
                self.untyped = f"{doc.path}: {type(e).__name__}: {e}"
                self.untyped_at = (doc.path, _model_line(doc, e))
                return None
        if pol is None:
            self.untyped = f"the policy as the estate runs it does not load ({getattr(self, 'unloaded', 'its model refuses it')})"
            self.untyped_at = getattr(self, "unloaded_at", None)
            return None
        return typed[0], typed[1], pol

    def report(self) -> dict | None:
        """The generator's report on these files, computed once per run and read by every gate that needs it (GATE-9's
        render, clause 14.5); None when the files do not load through their models."""
        return self._once_for("report", (self.register, self.portfolio, self.policy), self._report)

    def _report(self) -> dict | None:
        typed = self.typed()
        if typed is None:
            return None
        from generator import render

        reg, pf, pol = typed
        return core.report(reg, pf, pol, render.drift_lines(reg, pol, pf))

    def review(self) -> dict[str, str]:
        """The review views as the generator emits them from these files (not from disk), rendered once per run, by
        their repository path."""
        return self._once_for("review", (self.register, self.portfolio, self.policy), self._review)

    def _review(self) -> dict[str, str]:
        from generator import render

        typed = self.typed()
        emitted = render.docs(*typed, report=self.report()) if typed else render.docs()
        return {
            f"docs/design/enterprise-strategy-layer/generator/rendered/{k}.html": v
            for k, v in emitted.items()
        }

    def why_untyped(self) -> str:
        """Why the models refused the register or the portfolio, naming the field and the value."""
        said = getattr(self, "untyped", "")
        return (
            "the register, the portfolio or the policy as the estate runs it does not load through its model"
            + (f": {said}" if said else "")
        )


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _listed(value: Any) -> list:
    """A list as written; one item written bare (a string, a mapping) read as a list of one, so a walk never reads a
    string by its characters or a mapping by its keys; nothing written is no item. An estate's own items have no model
    yet, so this is what keeps their shape from hiding a value from a gate."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _caps(s: Sources):
    """(doc, path, capability) for the register's capabilities and a portfolio's estate-local ones."""
    for i, c in enumerate(s.register.data.get("capabilities") or []):
        yield s.register, ("capabilities", i), c
    for i, c in enumerate(_listed(s.portfolio.data.get("local_capabilities"))):
        yield s.portfolio, ("local_capabilities", i), c


def _inits(s: Sources):
    for i, d in enumerate(s.register.data.get("initiatives") or []):
        yield s.register, ("initiatives", i), d
    for i, d in enumerate(_listed(s.portfolio.data.get("local_initiatives"))):
        yield s.portfolio, ("local_initiatives", i), d


def _f(
    clause: str,
    doc: Doc | str,
    path: tuple,
    what: str,
    edit: str,
    line: int | None = None,
    listed: bool = False,
) -> Finding:
    if isinstance(doc, Doc):
        return Finding(clause, doc.path, line or doc.line(*path), what, edit, listed)
    return Finding(clause, doc, line, what, edit, listed)


def _ref(x: str) -> tuple[str, str]:
    prefix, _, rest = str(x).partition(":")
    return (prefix, rest) if rest else ("", prefix)


def _roles(s: Sources) -> set[str]:
    return {r.get("id") for r in s.register.data.get("roles") or []}


def _foundation(s: Sources) -> str:
    """The handbook's foundation job: the vocabulary's job that holds no phase (check_jobs' own rule)."""
    found = [j["id"] for j in s.comp_map.get("jobs") or [] if not j.get("phase")]
    return found[0] if len(found) == 1 else "foundation"


def _competencies(s: Sources) -> dict[str, dict]:
    return {c["id"]: c for c in s.comp_map.get("competencies") or []}


def _published(s: Sources, comp: dict) -> bool:
    return comp.get("status") != "planned" and comp.get("teaches") in s.pages


def _companion_url() -> str:
    from generator import render

    return render.COMPANION


def _page_published(s: Sources, page: str) -> bool:
    """A handbook page in pages.json, or a companion file published from staging."""
    base = _companion_url().rstrip("/") + "/"
    if page.startswith(base):
        rest = page[len(base) :]
        if not rest.startswith(
            "blob/main/"
        ):  # the companion publishes its files on main, at blob/main/<path>
            return False
        rest = rest[len("blob/main/") :]
        staging = (s.root / STAGING.relative_to(ROOT)).resolve()
        target = (staging / rest).resolve()
        return (
            target.is_relative_to(staging) and target.is_file()
        )  # a file inside staging, never outside it
    return page in s.pages


# ── GATE-1: one accountable role, one sponsor, one writer, roles defined; one department per role and scope ──────────
def gate_1(s: Sources) -> list[Finding]:
    out, roles = [], _roles(s)

    def one(clause, doc, path, value, what, field_):
        if not isinstance(value, str) or not value:
            n = len(value) if isinstance(value, list) else 0
            out.append(
                _f(
                    clause,
                    doc,
                    path,
                    f"{what} names {n} {field_} roles",
                    f"name exactly one role in `{field_}`",
                )
            )
            return None
        return value

    def defined(doc, path, role):
        if role is not None and role not in roles:
            out.append(
                _f(
                    "1.4",
                    doc,
                    path,
                    f"names the role {role!r}, which the register does not define",
                    f"define {role!r} under the register's `roles`, or name one of {', '.join(sorted(roles))}",
                )
            )

    for doc, p, c in _caps(s):
        defined(
            doc,
            (*p, "accountable"),
            one("1.1", doc, (*p, "accountable"), c.get("accountable"), c.get("id"), "accountable"),
        )
        for j, d in enumerate(c.get("declarations") or []):
            w = d.get("writer")
            if not isinstance(w, str) or not w:
                out.append(
                    _f(
                        "1.3",
                        doc,
                        (*p, "declarations", j),
                        f"{c.get('id')}: the declaration of {d.get('object')!r} names no single writer",
                        "name exactly one role in `writer`",
                    )
                )
            else:
                defined(doc, (*p, "declarations", j, "writer"), w)
        for j, loop in enumerate(c.get("sustain") or []):
            defined(doc, (*p, "sustain", j, "runner"), loop.get("runner"))
        for j, v in enumerate(c.get("value") or []):
            defined(doc, (*p, "value", j, "target_owner"), v.get("target_owner"))
    for doc, p, d in _inits(s):
        defined(
            doc,
            (*p, "sponsor"),
            one("1.2", doc, (*p, "sponsor"), d.get("sponsor"), d.get("id"), "sponsor"),
        )
    for i, w in enumerate(s.register.data.get("watch_list") or []):
        defined(s.register, ("watch_list", i, "reader"), w.get("reader"))
    pf = s.portfolio
    seen: dict[tuple[str, str], str] = {}
    for i, a in enumerate(pf.data.get("assignments") or []):
        defined(pf, ("assignments", i, "role"), a.get("role"))
        key = (a.get("role"), a.get("scope"))
        if key in seen and seen[key] != a.get("department"):
            out.append(
                _f(
                    "1.5",
                    pf,
                    ("assignments", i),
                    f"the role {key[0]} in the scope {key[1]} is assigned to {seen[key]} and to {a.get('department')}",
                    "keep one department per role per scope; split the scope if two departments each hold part of it",
                )
            )
        seen.setdefault(key, a.get("department"))
    for i, c in enumerate(pf.data.get("capacity") or []):
        defined(pf, ("capacity", i, "role"), c.get("role"))
    return out


# ── GATE-2: jobs, the competencies that teach, the pages that serve ────────────────────────────────────────────────
def gate_2(s: Sources) -> list[Finding]:
    out, comps, found = [], _competencies(s), _foundation(s)
    vocab = {j["id"] for j in s.comp_map.get("jobs") or []}
    for doc, p, c in _caps(s):
        cid, jobs = c.get("id"), c.get("jobs") or []
        if not jobs and not str(c.get("practice") or "").strip():
            out.append(
                _f(
                    "2.1",
                    doc,
                    (*p, "jobs"),
                    f"{cid} names no job",
                    "name the jobs of competency-map.yaml it serves, or the outside model's capability it implements "
                    "as the layer's own practice (`practice`, DEC-18)",
                )
            )
        if jobs and str(c.get("practice") or "").strip():
            out.append(
                _f(
                    "2.17",
                    doc,
                    (*p, "jobs"),
                    f"{cid} is keyed to the practice {c.get('practice')!r} and names the jobs {jobs}",
                    "the layer's own practice names no job: it is keyed to the outside model, never to the handbook "
                    "(charter section 5.5, DEC-18); drop the jobs, or the key",
                )
            )
        for j, job in enumerate(jobs):
            if job == found:
                out.append(
                    _f(
                        "2.2",
                        doc,
                        (*p, "jobs", j),
                        f"{cid} names {found!r} as a job",
                        f"drop {found!r}: it is every job's ground and no capability's job (check_jobs' rule)",
                    )
                )
            elif job not in vocab:
                out.append(
                    _f(
                        "2.3",
                        doc,
                        (*p, "jobs", j),
                        f"{cid} names the job {job!r}, which competency-map.yaml's `jobs` does not hold",
                        "name a job of deploy/privatecloudarchitect/site/competency-map.yaml, or update this line in "
                        "the change that renamed it",
                    )
                )
        taught = c.get("taught_by") or []
        teaching = [t for t in taught if t in comps and comps[t].get("job") != found]
        untaught = c.get("untaught") or []
        if not teaching and not any(_names_territory_and_lane(u) for u in untaught):
            out.append(
                _f(
                    "2.4",
                    doc,
                    (*p, "taught_by"),
                    f"{cid} is taught by no non-foundation competency and `untaught` names no territory and lane",
                    "name the competency that teaches it, or record its territory in `untaught` with the lane its "
                    'candidate chapter was sent to ("<territory>, sent to lane <lane>")',
                )
            )
        for j, t in enumerate(taught):
            comp = comps.get(t)
            if comp is None or not _published(s, comp):
                out.append(
                    _f(
                        "2.5",
                        doc,
                        (*p, "taught_by", j),
                        f"{cid} is taught by {t!r}, which is not a published competency",
                        "name a published competency of competency-map.yaml, or update this line in the change that "
                        "renamed or unpublished it",
                    )
                )
            elif comp.get("job") != found and comp.get("job") not in jobs:
                out.append(
                    _f(
                        "2.6",
                        doc,
                        (*p, "taught_by", j),
                        f"{cid} is taught by {t!r}, whose job {comp.get('job')!r} is none of its jobs",
                        f"add {comp.get('job')!r} to the capability's jobs, or name a competency that serves one of them",
                    )
                )
        if doc is s.register:  # an adopter has no lane to send a territory to
            for j, u in enumerate(untaught):
                if not _on_record(u):
                    out.append(
                        _f(
                            "2.8",
                            doc,
                            (*p, "untaught", j),
                            f"{cid}'s untaught entry names no lane or has no message on record",
                            "write it as {territory, lane, message: {sent, answer, answered}}, the answer null and "
                            "pending until the lane answers",
                        )
                    )
        for j, page in enumerate(c.get("links") or []):
            if page not in s.pages:
                out.append(
                    _f(
                        "2.7",
                        doc,
                        (*p, "links", j),
                        f"{cid} links {page!r}, which deploy/privatecloudarchitect/site/src/pages.json does not hold",
                        "link a published page, or update this line in the change that moved or unpublished it",
                    )
                )
    out += _catalog_map(s)
    return out


def _practice_ids(s: Sources) -> set[str]:
    """The register ids the catalog's map places as the layer's own practice: a register placement with lane 64 and no
    job (DEC-18)."""
    if s.catalog_map is None:
        return set()
    return {
        p.get("register_id")
        for p in s.catalog_map.data.get("placements") or []
        if p.get("place") == "register" and p.get("lane") and not p.get("proposed_job")
    }


def _practice_written(s: Sources) -> dict[str, str]:
    """The practice capabilities the register writes, by id, each with the outside model's capability its `practice`
    names (schema 4; 40-BREADTH.md step 4). Before the first practice batch the map alone named them."""
    return {
        c.get("id"): str(c.get("practice"))
        for c in s.register.data.get("capabilities") or []
        if str(c.get("practice") or "").strip()
    }


def _catalog_map(s: Sources) -> list[Finding]:
    """The catalog's map against the outside model and the handbook (40-BREADTH.md step 3): every capability of the
    outside model placed once (2.9); every named capability of each cross-check `completeness` names mapped to the
    outside model or reasoned (2.10); a register placement naming a capability or planned capability the register holds
    (2.11); an untaught placement naming its lane (2.12); a placement out of scope saying why (2.13); a practice
    capability, once written, handing off to a capability keyed to a job (2.14); a proposed competency serving the job
    it proposes (2.15)."""
    if s.catalog_map is None or s.outside_model is None:
        return []
    pol = s.loaded()
    if pol is None:
        return []
    out: list[Finding] = []
    m, om = s.catalog_map, s.outside_model
    completeness = pol.get("completeness")
    model, checks = completeness["outside_model"], set(completeness["cross_checks"])
    named = om.data.get("capabilities") or []
    placements = m.data.get("placements") or []
    placed = {p.get("capability") for p in placements}
    if m.data.get("model") != model or om.data.get("model") != model:
        out.append(
            _f(
                "2.9",
                m,
                ("model",),
                f"the map's model {m.data.get('model')!r} is not the outside model `completeness` names ({model!r})",
                "place the capabilities of the outside model `completeness` names",
            )
        )
    for i, c in enumerate(named):
        if c.get("source") == model and c.get("name") not in placed:
            out.append(
                _f(
                    "2.9",
                    om,
                    ("capabilities", i),
                    f"the outside model's {c.get('name')!r} ({c.get('perspective')}) is placed nowhere",
                    "place it in catalog-map.yaml: in the register, untaught with its lane, or out of scope with why",
                )
            )
    mapped = {(x.get("source"), x.get("name")): x for x in m.data.get("mappings") or []}
    model_names = {c.get("name") for c in named if c.get("source") == model}
    for i, c in enumerate(named):
        if c.get("source") not in checks:
            continue
        x = mapped.get((c.get("source"), c.get("name")))
        if x is None or not (x.get("maps_to") or str(x.get("reason") or "").strip()):
            out.append(
                _f(
                    "2.10",
                    om if x is None else m,
                    ("capabilities", i)
                    if x is None
                    else ("mappings", list(mapped).index((c.get("source"), c.get("name")))),
                    f"{c.get('source')}'s {c.get('name')!r} is neither mapped to the outside model nor reasoned",
                    "map it to the outside model's capability that covers it, or say why none does",
                )
            )
    for j, x in enumerate(m.data.get("mappings") or []):
        for k, target in enumerate(x.get("maps_to") or []):
            if target not in model_names:
                out.append(
                    _f(
                        "2.10",
                        m,
                        ("mappings", j, "maps_to", k),
                        f"{x.get('source')}'s {x.get('name')!r} maps to {target!r}, which the outside model does not name",
                        "map it to a capability of the outside model as research/outside-model.yaml names it",
                    )
                )
    held = {c.get("id") for c in s.register.data.get("capabilities") or []} | set(
        s.register.data.get("planned_capabilities") or []
    )
    comps = _competencies(s)
    for i, p in enumerate(placements):
        place = p.get("place")
        if place == "register" and p.get("register_id") not in held:
            out.append(
                _f(
                    "2.11",
                    m,
                    ("placements", i, "register_id"),
                    f"{p.get('capability')!r} is placed in the register as {p.get('register_id')!r}, which the register "
                    "neither holds nor plans",
                    "enter the id in the register's planned_capabilities, or name the capability that covers it",
                )
            )
        if place == "untaught" and not str(p.get("lane") or "").strip():
            out.append(
                _f(
                    "2.12",
                    m,
                    ("placements", i),
                    f"{p.get('capability')!r} is placed untaught and names no lane",
                    "name the lane its territory was sent to (lanes.yaml)",
                )
            )
        if place == "out_of_scope" and not str(p.get("reason") or "").strip():
            out.append(
                _f(
                    "2.13",
                    m,
                    ("placements", i),
                    f"{p.get('capability')!r} is placed out of scope with no reason",
                    "say why, within policy.yaml's product-stack-scope (DEC-08)",
                )
            )
        comp, job = p.get("proposed_competency"), p.get("proposed_job")
        if comp and job and comps.get(comp, {}).get("job") != job:
            out.append(
                _f(
                    "2.15",
                    m,
                    ("placements", i, "proposed_competency"),
                    f"{p.get('capability')!r} proposes the competency {comp!r}, whose job is "
                    f"{comps.get(comp, {}).get('job')!r}, not the proposed {job!r}",
                    "propose a competency of the proposed job, or the job the competency serves",
                )
            )
    # a practice capability, once written, hands off to a capability keyed to a job: a page a job-keyed capability's
    # competencies teach or its links serve. The register's `practice` key names the practice (schema 4); the map's
    # placement must agree with it (2.16), so neither record can drift from the other.
    written = _practice_written(s)
    placed = {
        p.get("register_id"): p.get("capability")
        for p in m.data.get("placements") or []
        if p.get("place") == "register" and p.get("register_id") in _practice_ids(s)
    }
    for i, c in enumerate(s.register.data.get("capabilities") or []):
        cid = c.get("id")
        if cid in written and placed.get(cid) != written[cid]:
            out.append(
                _f(
                    "2.16",
                    s.register,
                    ("capabilities", i, "practice"),
                    f"{cid} is keyed to the practice {written[cid]!r}, which the catalog's map does not place on it"
                    + (f" (the map places {placed[cid]!r})" if cid in placed else ""),
                    "key it to the capability the map places on it, or place that capability in the map (DEC-18)",
                )
            )
    written_ids = {c.get("id") for c in s.register.data.get("capabilities") or []}
    for i, p in enumerate(m.data.get("placements") or []):
        rid = p.get("register_id")
        if rid in placed and rid in written_ids and rid not in written:
            out.append(
                _f(
                    "2.16",
                    m,
                    ("placements", i),
                    f"{p.get('capability')!r} is placed as the layer's own practice on {rid}, which the register "
                    "writes with no `practice`",
                    "key the capability to the placement's capability (`practice`), or move the placement",
                )
            )
    job_pages: set[str] = set()
    for c in s.register.data.get("capabilities") or []:
        if c.get("id") in written:
            continue
        job_pages |= set(c.get("links") or [])
        job_pages |= {
            comps[t]["teaches"]
            for t in c.get("taught_by") or []
            if t in comps and comps[t].get("teaches")
        }
    for i, c in enumerate(s.register.data.get("capabilities") or []):
        if c.get("id") not in written:
            continue
        pages = {
            page
            for part in [*(c.get("establish") or []), *(c.get("sustain") or [])]
            for h in part.get("handoff") or []
            for page in h.get("pages") or []
        } | set(c.get("links") or [])
        if not pages & job_pages:
            out.append(
                _f(
                    "2.14",
                    s.register,
                    ("capabilities", i),
                    f"{c.get('id')} is the layer's own practice and hands off to no capability keyed to a job",
                    "name a hand-off or a link to a page a job-keyed capability's competencies teach or its links "
                    "serve, the capability whose output the practice reads (DEC-18)",
                )
            )
    return out


def _names_territory_and_lane(u: Any) -> bool:
    """An untaught entry that names its territory and the lane it was sent to: typed (schema 3), or as text in the form
    schema 2 wrote ("<territory>, sent to lane <lane>")."""
    if isinstance(u, dict):
        return bool(str(u.get("territory") or "").strip() and str(u.get("lane") or "").strip())
    return isinstance(u, str) and bool(re.search(r"\blane\b", u))


def _on_record(u: Any) -> bool:
    """An untaught entry or hand-off whose lane and message are on record: a lane, and a message with the day it was
    sent; a pending answer is on record (B10 needs only the message)."""
    if not isinstance(u, dict):
        return False
    msg = u.get("message")
    return (
        bool(str(u.get("lane") or "").strip())
        and isinstance(msg, dict)
        and _is_date(msg.get("sent"))
    )


# ── GATE-3: the value and sustain ledgers ──────────────────────────────────────────────────────────────────────────
STAGING_PATH = re.compile(r"deploy/privatecloudarchitect/companion/staging/[\w./-]+")


def gate_3(s: Sources) -> list[Finding]:
    out = []
    pol = s.loaded()
    # the value categories are the policy's: when it does not load, 3.3 is not judged, and the run says why
    speed = (
        set() if pol is None else {m for m in pol.vocabulary("value_categories") if m == "speed"}
    )
    for doc, p, c in _caps(s):
        cid = c.get("id")
        for ledger in ("value", "sustain"):
            if not c.get(ledger):
                out.append(
                    _f(
                        "3.1",
                        doc,
                        (*p, ledger),
                        f"{cid}'s {ledger} ledger is empty",
                        f"write at least one {'value it returns' if ledger == 'value' else 'loop that keeps it'}",
                    )
                )
        values = {v.get("id"): v for v in c.get("value") or []}
        for j, v in enumerate(c.get("value") or []):
            gap = v.get("instrument") if isinstance(v.get("instrument"), dict) else None
            missing = [
                k for k in ("serves", "category", "measure", "unit", "instrument") if not v.get(k)
            ]
            if gap is not None and not (
                str(gap.get("not_covered") or "").strip() and str(gap.get("lane") or "").strip()
            ):
                missing.append("instrument's reason and lane")
            if gap is not None:
                out += _instrument_gap(s, doc, (*p, "value", j, "instrument"), cid, v.get("id"))
            if missing:
                out.append(
                    _f(
                        "3.2",
                        doc,
                        (*p, "value", j),
                        f"{cid}'s value {v.get('id')} has no {', '.join(missing)}",
                        "write each: the business objective it serves, its category, measure, unit and instrument",
                    )
                )
            if v.get("category") in speed:
                pair = values.get(v.get("paired_with"))
                if pair is None or pair is v:
                    out.append(
                        _f(
                            "3.3",
                            doc,
                            (*p, "value", j),
                            f"{cid}'s speed value {v.get('id')} is paired with no stability measure",
                            "pair it (`paired_with`) with a value of the same capability that measures stability",
                        )
                    )
        texts = [
            ((*p, "value", j, "instrument"), v.get("instrument") or "")
            for j, v in enumerate(c.get("value") or [])
            if not isinstance(v.get("instrument"), dict)  # a gap names no companion (3.5, 3.6)
        ]
        texts += [
            ((*p, "sustain", j, "carried_by"), lp.get("carried_by") or "")
            for j, lp in enumerate(c.get("sustain") or [])
        ]
        dr = (c.get("drift_read") or {}).get("companion")
        if dr and not _layer_reader(s, dr):
            texts.append(
                (
                    (*p, "drift_read", "companion"),
                    f"deploy/privatecloudarchitect/companion/staging/{dr}",
                )
            )
        for path, text in texts if s.judges("3.4") else []:  # staging is this repository's
            for m in STAGING_PATH.finditer(text):
                named = m.group(0).rstrip(".,;)")
                if not (s.root / named).exists():
                    out.append(
                        _f(
                            "3.4",
                            doc,
                            path,
                            f"{cid} names the companion path {named}, which is not in staging",
                            "name a companion in deploy/privatecloudarchitect/companion/staging, or update this line "
                            "in the change that moved or removed it",
                        )
                    )
    return out


LAYER_READERS = (
    "docs/design/enterprise-strategy-layer/generator/",
    "docs/design/enterprise-strategy-layer/instrument/",
)


def _layer_reader(s: Sources, companion: str) -> bool:
    """A drift read the strategy layer's own code makes (the strategy check over the register, the portfolio and the
    policy, for the layer's own practice; 40-BREADTH.md step 4), named by its repository path: a companion beside the
    staging ones, accepted when the file exists under the generator or the instrument folder."""
    return companion.startswith(LAYER_READERS) and (s.root / companion).is_file()


def _published_pages(s: Sources) -> set[str] | None:
    """The paths `strategy-pages` publishes, as the estate runs the policy; None when the policy does not load."""
    pol = s.loaded()
    return None if pol is None else set(pol.get("strategy-pages"))


def _instrument_gap(s: Sources, doc: Doc, path: tuple, cid: str, vid: str) -> list[Finding]:
    """A value whose instrument no lane has built (DEC-21): refused on a capability `strategy-pages` publishes (3.5);
    on any other, refused while `instrument-gaps` reads `wait` and listed while it reads `carry` (3.6)."""
    pol = s.loaded()
    if pol is None:
        return []
    if f"/strategy/{cid}" in (_published_pages(s) or set()):
        return [
            _f(
                "3.5",
                doc,
                path,
                f"{cid}'s value {vid} has no instrument yet, and its page is published",
                "restore the instrument, or ask the operator through D4-16 to withdraw the capability's page",
            )
        ]
    carry = pol.get("instrument-gaps") == "carry"
    return [
        _f(
            "3.6",
            doc,
            path,
            f"{cid}'s value {vid} has no instrument yet"
            + (": carried by name, off every served view (DEC-21)" if carry else ""),
            "build the instrument with the lane the value names, then write it here",
            listed=carry,
        )
    ]


# ── GATE-4: every assessment has its date, tiers, evidence and confidence ──────────────────────────────────────────
def _is_date(x: Any) -> bool:
    """A calendar day, by the models' one rule (never a week date, never a day the calendar lacks)."""
    try:
        models.a_day(str(x), "a date", time=True)
        return True
    except ValueError:
        return False


def _evidence_given(e: Any) -> bool:
    """An evidence item that says something: a reference's text, a citation's source, or (schema 2's form) text."""
    if isinstance(e, dict):
        return bool(str(e.get("ref") or e.get("cite") or "").strip())
    return bool(str(e or "").strip())


def gate_4(s: Sources) -> list[Finding]:
    out = []
    checks = [
        (doc, (*p, "guidance", k), d.get("id"), g, ("half_life",))
        for doc, p, d in _inits(s)  # the register's initiatives and an estate's own
        for k, g in enumerate(_listed(d.get("guidance")))
    ] + [
        (
            s.portfolio,
            ("initiatives", i, "planning", k),
            d.get("id"),
            g,
            ("full_value_in", "first_value_in", "tier", "first_value_tier"),
        )
        for i, d in enumerate(s.portfolio.data.get("initiatives") or [])
        for k, g in enumerate(_listed(d.get("planning")))
    ]
    for doc, path, iid, a, tiers in checks:
        missing = [t for t in tiers if not a.get(t)]
        if not _is_date(a.get("assessed")):
            missing.append("assessed (a date)")
        if not any(_evidence_given(e) for e in _listed(a.get("evidence"))):
            missing.append("evidence")
        if not a.get("confidence"):
            missing.append("confidence")
        if missing:
            out.append(
                _f(
                    "4.1",
                    doc,
                    path,
                    f"{iid}: an assessment without {', '.join(missing)}",
                    "write the assessment's date, its tiers, its evidence and its confidence",
                )
            )
    return out


# ── GATE-5: the establish ledger and the prerequisite graph ─────────────────────────────────────────────────────────
def gate_5(s: Sources) -> list[Finding]:
    out = []
    caps = {c.get("id") for _d, _p, c in _caps(s)}
    planned = set(s.register.data.get("planned_capabilities") or [])
    comps = _competencies(s)
    edges: dict[str, set[str]] = {}

    def resolve(doc, path, owner, x, earlier: list[str] | None):
        kind, ident = _ref(x)
        ok = {
            "step": earlier is not None and ident in earlier,
            "capability": ident in caps or ident in planned,
            "competency": ident in comps,
            "phase": ident in s.phases,
            "ladder": ident in s.rungs,
        }.get(kind, False)
        if not ok:
            hint = (
                "an earlier step of the same capability"
                if kind == "step"
                else "a capability, a planned capability, a competency, a phase or a ladder rung"
            )
            out.append(
                _f(
                    "5.2",
                    doc,
                    path,
                    f"{owner}: the prerequisite {x!r} resolves to nothing",
                    f"name {hint}, with its prefix",
                )
            )
        return kind, ident

    for doc, p, c in _caps(s):
        cid = c.get("id")
        steps = c.get("establish") or []
        if not steps:
            out.append(
                _f(
                    "5.1",
                    doc,
                    (*p, "establish"),
                    f"{cid}'s establish ledger is empty",
                    "write the one-time steps that bring it into being",
                )
            )
        seen: list[str] = []
        for j, st in enumerate(steps):
            for k, x in enumerate(st.get("requires") or []):
                kind, ident = resolve(
                    doc, (*p, "establish", j, "requires", k), f"{cid}.{st.get('id')}", x, seen
                )
                if kind == "capability":
                    edges.setdefault(cid, set()).add(ident)
                if kind == "ladder" and c.get("scope") != "workload":
                    out.append(
                        _f(
                            "5.4",
                            doc,
                            (*p, "establish", j, "requires", k),
                            f"{cid} is a {c.get('scope')} capability and names the ladder rung {ident}",
                            "the Standup Dependency Ladder orders a workload; drop the rung or make the capability's "
                            "scope workload",
                        )
                    )
            seen.append(st.get("id"))
    for doc, p, d in _inits(s):
        iid = d.get("id")
        made = [_ref(x)[1] for x in d.get("establishes") or []]
        for key in ("establishes", "improves", "requires"):
            for k, x in enumerate(d.get(key) or []):
                kind, ident = resolve(doc, (*p, key, k), iid, x, None)
                if key == "requires" and kind == "capability":
                    for m in made:
                        edges.setdefault(m, set()).add(ident)

    # a cycle among capabilities, through steps and through the initiatives that establish them
    state: dict[str, int] = {}
    cycles: list[list[str]] = []

    def visit(n: str, trail: list[str]) -> None:
        state[n] = 1
        for m in sorted(edges.get(n, ())):
            if state.get(m) == 1:
                cycles.append([*trail[trail.index(m) :], m] if m in trail else [n, m])
            elif not state.get(m):
                visit(m, [*trail, m])
        state[n] = 2

    for n in sorted(edges):
        if not state.get(n):
            visit(n, [n])
    for cyc in cycles:
        home = next(((doc, p) for doc, p, c in _caps(s) if c.get("id") == cyc[0]), (s.register, ()))
        out.append(
            _f(
                "5.3",
                home[0],
                home[1],
                f"the prerequisites form a cycle: {' -> '.join(cyc)}",
                "break the cycle: one of these capabilities must come first",
            )
        )
    return out


# ── GATE-6: citations verified; forecasts labelled ─────────────────────────────────────────────────────────────────
URL = re.compile(r"https?://\S+", re.IGNORECASE)


def gate_6(s: Sources) -> list[Finding]:
    out = []
    evid = [
        (doc, (*p, "guidance", k, "evidence", e), x)
        for doc, p, d in _inits(s)  # the register's initiatives and an estate's own
        for k, g in enumerate(_listed(d.get("guidance")))
        for e, x in enumerate(_listed(g.get("evidence")))
    ] + [
        (s.portfolio, ("initiatives", i, "planning", k, "evidence", e), x)
        for i, d in enumerate(s.portfolio.data.get("initiatives") or [])
        for k, g in enumerate(_listed(d.get("planning")))
        for e, x in enumerate(_listed(g.get("evidence")))
    ]
    for doc, path, x in evid:
        if (
            isinstance(x, dict) and "ref" in x and "cite" not in x
        ):  # schema 3: a reference, never an external source
            if URL.search(str(x.get("ref") or "")):
                out.append(
                    _f(
                        "6.1",
                        doc,
                        path,
                        "an external source cited as a reference",
                        "write it as a citation, {cite, fetched, version, quote}, read in session (BLOCK-010)",
                    )
                )
            continue
        if isinstance(x, str) and URL.search(x):
            out.append(
                _f(
                    "6.1",
                    doc,
                    path,
                    "an external source cited as text",
                    "write it as a citation, {cite, fetched, version, quote}, read in session (BLOCK-010)",
                )
            )
        elif not isinstance(x, (str, dict)):
            out.append(
                _f(
                    "6.1",
                    doc,
                    path,
                    f"an evidence item of the shape {type(x).__name__}, neither a citation nor text",
                    "write it as a citation, {cite, fetched, version, quote}, read in session (BLOCK-010)",
                )
            )
        elif isinstance(x, dict):
            # each present: a blank is no value, as clause 7.5 and GATE-4 read one
            missing = [
                k
                for k in ("cite", "fetched", "version", "quote")
                if not str(x.get(k) or "").strip()
            ]
            if x.get("fetched") and not _is_date(x["fetched"]):
                missing.append("fetched as a date")
            if missing:
                out.append(
                    _f(
                        "6.1",
                        doc,
                        path,
                        f"the citation of {x.get('cite')} has no {', '.join(missing)}",
                        "fetch it in session and record the day it was fetched and the source's own version or date "
                        "(BLOCK-010)",
                    )
                )
    for doc in (s.register, s.portfolio):  # the register's trigger events and an estate's own
        for i, t in enumerate(_listed(doc.data.get("trigger_events"))):
            if URL.search(str(t.get("source") or "")) and not (
                _is_date(t.get("read_at")) and _is_date(t.get("date"))
            ):
                out.append(
                    _f(
                        "6.1",
                        doc,
                        ("trigger_events", i),
                        f"the trigger event {t.get('id')} cites a source without the date it was read and its own date",
                        "record `read_at` and `date` (BLOCK-010)",
                    )
                )
    for i, sig in enumerate(
        _listed(s.register.data.get("signals"))
    ):  # schema 3: a signal names its source
        if URL.search(str(sig.get("source") or "")) and not _is_date(sig.get("read_at")):
            out.append(
                _f(
                    "6.1",
                    s.register,
                    ("signals", i),
                    f"the signal {sig.get('id')} cites a source without the time it was read",
                    "record `read_at` (BLOCK-010)",
                )
            )
    typed = s.typed()
    if typed:
        reg, pf, pol = typed
        forecast = {m for m in pol.vocabulary("confidence") if m == "forecast"}
        for problem in core.readiness_problems(reg, pf, pol):
            if problem["kind"] != "unconstrained":
                continue
            i = next(
                i
                for i, d in enumerate(s.portfolio.data.get("initiatives") or [])
                if d.get("id") == problem["initiative"]
            )
            planning = s.portfolio.data["initiatives"][i].get("planning") or []
            # the newest assessment is judged, as the board shows it; an older one is superseded, never edited
            newest = core.newest_index(planning, day=lambda a: a.get("assessed"))
            for k, a in enumerate(planning):
                if k == newest and a.get("confidence") not in forecast:
                    out.append(
                        _f(
                            "6.2",
                            s.portfolio,
                            ("initiatives", i, "planning", k, "confidence"),
                            f"{problem['initiative']} requires {problem['requires']}, which no "
                            f"{'committed ' if problem.get('makers') else ''}initiative establishes, so its horizon "
                            "rests on a decision nobody has made and is a forecast; it is not labelled as one",
                            "set its confidence to forecast, or commit the initiative that establishes the prerequisite",
                        )
                    )
    return out


# ── GATE-7: no estate in the register; nothing private and nothing unlabelled in a public view ─────────────────────
def _fields(model, seen=None) -> set[str]:
    """Every field name a model and the models it holds declare, by alias."""
    import typing

    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    out = set()
    for name, f in model.model_fields.items():
        out.add(f.alias or name)
        stack = [f.annotation]
        while stack:
            a = stack.pop()
            if isinstance(a, type) and issubclass(a, models.BaseModel):
                out |= _fields(a, seen)
            stack.extend(typing.get_args(a))
    return out


# An estate's state is what a portfolio's models name and the register's do not (section 7: the register holds
# definitions, a portfolio one estate's state and plan), derived from the models so a new field joins without an edit.
STATE_KEYS = _fields(models.Portfolio) - _fields(models.Register)


ROOT_DIV = re.compile(r'<div class="esl"[^>]*>')


def _line_at(page: str, index: int) -> int:
    return page.count("\n", 0, index) + 1


def _root_line(page: str) -> int:
    """The line of a view's root element, where a finding about the whole view points."""
    m = ROOT_DIV.search(page)
    return _line_at(page, m.start()) if m else 1


def _content(page: str) -> tuple[str, int]:
    """A view's own content, without the site's layout around it, and the offset it starts at: from the marker the
    renderer writes where the layout takes the content, or from the root element."""
    at = page.find("<!-- strategy-content -->")
    if at < 0:
        m = ROOT_DIV.search(page)
        at = m.start() if m else 0
    return page[at:], at


KILL_LIST_PATH = (
    scrublist.KILL_LIST_PATH
)  # the publisher's list, the default; a run may pass another (step 9)
kill_list_from = (
    scrublist.kill_list_from
)  # the reader, in the module the drift loader shares (generator/scrublist.py)


def _kill_list(path: Path | None = None) -> tuple[re.Pattern, tuple[str, ...]]:
    """The scrub list the gates use: the publisher's, read as data (never executed), or the list a run passes."""
    return scrublist.default(path)


def scrub(text: str | None, lists: tuple[re.Pattern, tuple[str, ...]] | None = None) -> str | None:
    """Text with each estate identifier the companions' kill-list catches replaced, its allowed values spared: what a
    gate prints or a run records names a line, never the identifier (GATE-7). `lists` is a scrub list a run passed
    (kill_list_from); the publisher's otherwise."""
    if not text:
        return text
    try:
        kill, allow = lists or _kill_list()
    except Exception:  # a text that cannot be scrubbed is withheld, never shown as it is
        return "[withheld: the companions' kill-list did not load]"
    spared = [(m.start(), m.end()) for a in allow for m in re.finditer(re.escape(a), text)]
    return kill.sub(
        lambda m: (
            m.group(0)
            if any(s <= m.start() and m.end() <= e for s, e in spared)
            else "[an estate identifier]"
        ),
        text,
    )


def scrubbed(r: Result, lists: tuple[re.Pattern, tuple[str, ...]] | None = None) -> Result:
    """A result whose findings, reason and listed items, their file paths among them (a view's name carries a role or
    the estate), carry no estate identifier. `lists` is the run's scrub list (Sources.lists); the publisher's otherwise."""
    out = replace(
        r,
        findings=[
            replace(
                f, file=scrub(f.file, lists), what=scrub(f.what, lists), edit=scrub(f.edit, lists)
            )
            for f in r.findings
        ],
        why=scrub(r.why, lists),
    )
    if getattr(r, "listed", None):
        out.listed = [
            replace(
                x, file=scrub(x.file, lists), what=scrub(x.what, lists), edit=scrub(x.edit, lists)
            )
            for x in r.listed
        ]
    return out


# the attributes whose text a reader or a search engine reads: a meta tag's content (the description, the title a
# link preview shows), an image's alt, an element's title or label
READ_ATTRS = re.compile(r'(?<![\w-])(?:content|alt|title|aria-label)="([^"]*)"')


def _tag_as_read(m: re.Match) -> str:
    """A tag as a reader or a search engine reads it: the text its read attributes hold, set apart by spaces."""
    return " " + " ".join(READ_ATTRS.findall(m.group(0))) + " "


_AS_READ: dict[str, str] = {}  # each distinct line read once: the site's layout is on every page


def as_read(raw: str) -> str:
    """A line as a reader or a search engine reads it: each tag read as the text its attributes show, then entities
    decoded, and every format character (a soft hyphen, a zero-width space) dropped, since it shows nothing and would
    split a phrase only for a machine."""
    if raw in _AS_READ:
        return _AS_READ[raw]
    text = html.unescape(re.sub(r"<[^>]+>", _tag_as_read, raw))
    if (
        not text.isascii()
    ):  # no format character is ASCII, so only the other characters are looked at
        text = NON_ASCII.sub(_no_format_character, text)
    _AS_READ[raw] = text
    return text


NON_ASCII = re.compile(r"[^\x00-\x7f]")


def _no_format_character(m: re.Match) -> str:
    return "" if unicodedata.category(m.group(0)) == "Cf" else m.group(0)


def _literals(seq) -> list[list[str]]:
    """Each literal a parsed rule's sequence requires, as a list of alternatives: a run of literal characters, what a
    group or a repeat of at least once requires, and for an alternation one requirement whose alternatives are each
    branch's best, or nothing when a branch requires nothing. A character class, a wildcard, a backreference or an
    assertion ends a run and requires nothing, which is the safe side: a requirement is only ever a literal every
    match must contain."""
    from re import _parser as sre

    out: list[list[str]] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            out.append(["".join(run)])
            run.clear()

    for op, av in seq:
        if op is sre.LITERAL:
            run.append(chr(av))
            continue
        flush()
        if op is sre.SUBPATTERN:
            out += _literals(av[3])
        elif op is sre.BRANCH:
            alts: list[str] | None = []
            for branch in av[1]:
                reqs = _literals(branch)
                if not reqs:
                    alts = None
                    break
                alts += _best(reqs)
            if alts:
                out.append(alts)
        elif op in (sre.MAX_REPEAT, sre.MIN_REPEAT) and av[0] >= 1:
            out += _literals(av[2])
    flush()
    return out


def _best(reqs: list[list[str]]) -> list[str]:
    return max(reqs, key=lambda alts: min(map(len, alts)))


def required_literal(pattern: str) -> list[str] | None:
    """Words of which every match of the rule contains one, casefolded, read from the rule's own parse; None when
    none can be read, and the rule is then searched everywhere. A text without any of them cannot match the rule, so
    GATE-9 does not search it: each view's content is one line, and every rule searched it as written and as decoded.
    Case: the rules match without regard to case, and casefolding both sides is the wider equivalence, so a text that
    could match always keeps its word."""
    try:
        from re import _parser as sre

        reqs = _literals(sre.parse(pattern))
    except Exception:  # a parse this reader does not follow: the rule is searched everywhere
        return None
    return [a.casefold() for a in _best(reqs)] if reqs else None


def _could_match(need: list[str] | None, folded: tuple[str, ...]) -> bool:
    """Whether a rule with the given requirement could match any of the casefolded texts."""
    return need is None or any(lit in text for text in folded for lit in need)


def _as_read(readable: str) -> tuple[str, list[tuple[int, int]]]:
    """A page's words as a reader or a search engine reads them (`as_read`), whitespace collapsed into one stream across
    line breaks; with each word's offset in the stream and the source line it came from."""
    words, starts, at = [], [], 0
    for n, raw in enumerate(readable.splitlines(), 1):
        for w in as_read(raw).split():
            words.append(w)
            starts.append((at, n))
            at += len(w) + 1
    return " ".join(words), starts or [(0, 1)]


def _leaks(
    text: str,
    memo: dict[str, int] | None = None,
    lists: tuple[re.Pattern, tuple[str, ...]] | None = None,
) -> list[tuple[int, int]]:
    """(line, count) for each line where the companions' kill-list finds an estate identifier; never the identifier.
    A `memo` shared across pages judges each line once however many pages repeat it (the site's layout). `lists` is a
    scrub list a run passed; the publisher's otherwise."""
    kill, allow = lists or _kill_list()
    memo = {} if memo is None else memo
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        if raw not in memo:
            line = raw
            for a in allow:
                line = line.replace(a, "")
            memo[raw] = len(kill.findall(line))
        if memo[raw]:
            out.append((n, memo[raw]))
    return out


def _keys(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield (*path, k), k
            yield from _keys(v, (*path, k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _keys(v, (*path, i))


def _public_portfolio(s: Sources) -> bool | None:
    """Whether `policy.yaml`'s `publication` makes this portfolio public (DEC-04): an item of its public list that names
    a portfolio and this estate. Any other portfolio is an adopter's, private, and refuses illustrative values. None when
    the policy does not load: publication cannot be read, so no clause that turns on it is judged."""
    pol = s.loaded()
    if pol is None:
        return None
    estate = str(s.portfolio.data.get("estate"))
    return any(f"the {estate} portfolio" in str(x) for x in pol.get("publication")["public"])


def gate_7(s: Sources) -> list[Finding]:
    out = []
    for line, n in _leaks(s.register.text, lists=s.lists):
        out.append(
            _f(
                "7.1",
                s.register.path,
                (),
                f"the register holds {n} estate identifier(s) the companions' kill-list catches on this line",
                "remove them: the register is universal",
                line=line,
            )
        )
    for path, k in _keys(s.register.data):
        if k in STATE_KEYS:
            out.append(
                _f(
                    "7.1",
                    s.register,
                    path,
                    f"the register holds an estate's state ({k})",
                    "move it to the estate's portfolio; the register holds definitions only",
                )
            )
    estate = s.portfolio.data.get("estate")
    public = _public_portfolio(s)
    # the public views' other inputs, read as written: the renderer reshapes what it shows (an id read as words), so an
    # identifier is caught at its source as well as on the page; an adopter's portfolio is private and holds its own
    for doc in [s.policy] + ([s.portfolio] if public else []):
        for line, n in _leaks(doc.text, lists=s.lists):
            out.append(
                _f(
                    "7.2",
                    doc.path,
                    (),
                    f"a public view's input holds {n} estate identifier(s) the companions' kill-list catches on this "
                    "line",
                    "remove them: the policy and the reference portfolio are published",
                    line=line,
                )
            )
    typed = s.typed()
    judged = core.provenance(typed[2], [], typed[0], typed[1])["input_digest"] if typed else None
    seen_lines: dict[str, int] = {}  # each line judged once however many views repeat it
    for rel, page in s.views.items():
        m = PROV.search(page)
        shown = (
            json.loads(html.unescape(m.group("data"))).get("input_digest")
            if m and m.group("data")
            else None
        )
        if (
            judged and shown and shown != judged
        ):  # a view rendered from other files than the ones judged here
            out.append(
                _f(
                    "7.2",
                    rel,
                    (),
                    f"the view was rendered from inputs {shown}, not the files judged here ({judged})",
                    "render the public views from the register, the reference portfolio and the policy judged here",
                    line=_line_at(page, m.start()),
                )
            )
        if public is False:
            out.append(
                _f(
                    "7.2",
                    rel,
                    (),
                    f"a public view rendered from the portfolio of the estate {estate!r}",
                    "render public views from the reference portfolio only; an adopter's portfolio is private (DEC-04)",
                    line=_root_line(page),
                )
            )
        for line, n in _leaks(page, seen_lines, lists=s.lists):
            out.append(
                _f(
                    "7.2",
                    rel,
                    (),
                    f"a public view holds {n} estate identifier(s) the companions' kill-list catches on this line",
                    "render from the reference portfolio's derived values only, never a raw read (DEC-04)",
                    line=line,
                )
            )
    typed = s.typed()
    boards = {  # the view says what it is, on its root
        r: p
        for r, p in s.views.items()
        if re.search(r'<div class="esl"[^>]*\bdata-view="board"', p)
    }
    if typed and not boards and core.illustrative_inputs(typed[1], typed[0]) and s.views:
        out.append(
            _f(
                "7.3",
                "docs/design/enterprise-strategy-layer/generator/render.py",
                (),
                "the portfolio has illustrative inputs and no view is the board that names them",
                "render the board, with its data-view",
                line=_def_line(LAYER / "generator" / "render.py", "board_page"),
            )
        )
    if typed and boards:
        reg, pf, _pol = typed
        for rel, page in boards.items():
            # the board's own list, item by item, as a reader reads it: a name elsewhere on the page labels nothing
            m = re.search(r'<p class="illus-list">(.*?)</p>', page, re.DOTALL)
            text = html.unescape(m.group(1)).strip() if m else ""
            listed = {x.strip() for x in (text[:-1] if text.endswith(".") else text).split("; ")}
            for item in core.illustrative_inputs(pf, reg):
                if item not in listed:
                    out.append(
                        _f(
                            "7.3",
                            rel,
                            (),
                            f"the illustrative input {item!r} is not labelled on the board",
                            "re-render the board: every illustrative input is listed and labelled",
                            line=_root_line(page),
                        )
                    )
    for rel, page in s.views.items():
        if not re.search(r'<div class="esl" data-source="[^"]+" data-view="[a-z]+"', page):
            out.append(
                _f(
                    "7.3",
                    rel,
                    (),
                    "the view does not declare what it renders and what it is, so its labels cannot be judged",
                    "render the root with its data-source (register, portfolio) and its data-view",
                    line=_root_line(page),
                )
            )
            continue
    for path, k in _keys(
        s.portfolio.data
    ):  # an input is shown with who supplied it, so it must name them
        if k == "kind":
            node = s.portfolio.data
            for key in path[:-1]:
                node = node[key]
            # who supplied it: its source, or, for an override alone, the decision it names (policy.yaml's shape)
            override = tuple(path[:2]) == ("policy", "overrides")
            supplier = node.get("source") or (node.get("decided_by") if override else None)
            if node.get("kind") == "input" and not str(supplier or "").strip():
                out.append(
                    _f(
                        "7.5",
                        s.portfolio,
                        path,
                        "an input value that names no one who supplied it",
                        "write its `source`: who supplied it, and when",
                    )
                )
    if public is False:
        for path, k in _keys(s.portfolio.data):
            if k == "kind":
                node = s.portfolio.data
                for key in path[:-1]:
                    node = node[key]
                if node.get("kind") == "illustrative":
                    out.append(
                        _f(
                            "7.4",
                            s.portfolio,
                            path,
                            "an illustrative value in an adopter's portfolio",
                            "replace it with a measured value or an input with who supplied it and when",
                        )
                    )
    if public:
        out += _approvals(s)
    return out


def _resolve(data: Any, address: tuple) -> bool:
    """Whether a portfolio holds a node at an address (served.KEYS reads a keyed list's items by their key)."""
    from generator import served

    node, at = data, ()
    for seg in address:
        if isinstance(node, dict):
            if seg not in node:
                return False
            node = node[seg]
        elif isinstance(node, list):
            key = served.KEYS.get(served._pattern(at))
            hit = [x for x in node if key is not None and str(key(x)) == seg]
            if len(hit) != 1:
                return False
            node = hit[0]
        else:
            return False
        at = (*at, seg)
    return True


def _approvals(s: Sources) -> list[Finding]:
    """7.6: a required node of the reference portfolio that no approval covers, where the served projection cannot
    withhold it: a top-level field `Portfolio` holds no default for, the capacity line of the role the board plans, and
    each published capability's `target_grade`. 7.7: an approval that names a node the working file no longer holds,
    listed. Judged on the working file, never the projection (40-BREADTH.md step 2)."""
    from generator import served

    typed = s.typed()
    if typed is None:
        return []
    _reg, pf, _pol = typed
    out: list[Finding] = []
    covered = {tuple(n.path) for a in pf.approvals for n in a.nodes}
    data = served.dumped(pf)
    required_top = {
        (f.alias or k,)
        for k, f in models.Portfolio.model_fields.items()
        if f.is_required() and (f.alias or k) not in ("schema", "estate", "policy", "approval")
    }
    board_role = (("capacity", pf.capacity[0].role),) if pf.capacity else ()
    published = _published_pages(s) or set()
    pages = {
        ("capabilities", c.id, "target_grade")
        for c in pf.capabilities
        if f"/strategy/{c.id}" in published
    }
    for address, _form in served.approvable(pf):
        if address in covered:
            continue
        if address in required_top or address in board_role or address in pages:
            out.append(
                _f(
                    "7.6",
                    s.portfolio,
                    address[:1],
                    f"the node {'/'.join(address)} is required on the served pages, and no approval covers it",
                    "ask the operator to approve it (served.py ask), and record the approval from the ask",
                )
            )
    for i, a in enumerate(pf.approvals):
        for k, n in enumerate(a.nodes):
            if not _resolve(data, tuple(n.path)):
                out.append(
                    _f(
                        "7.7",
                        s.portfolio,
                        ("approvals", i, "nodes", k),
                        f"{a.decision}'s approval names {'/'.join(n.path)}, which the portfolio no longer holds",
                        "leave it as the record of what was approved; a later approval need not name it",
                        listed=True,
                    )
                )
    return out


# ── GATE-8: no plan ahead of its prerequisites ──────────────────────────────────────────────────────────────────────
def gate_8(s: Sources) -> list[Finding]:
    typed = s.typed()
    if not typed:
        return []
    reg, pf, pol = typed
    out = []
    pos = {d.get("id"): i for i, d in enumerate(s.portfolio.data.get("initiatives") or [])}
    for problem in core.readiness_problems(reg, pf, pol):
        if problem["kind"] != "nearer":
            continue
        out.append(
            _f(
                "8.1",
                s.portfolio,
                ("initiatives", pos.get(problem["initiative"], 0), "planning"),
                f"{problem['initiative']}: its tier {problem['tier']} is nearer than {problem['nearest']}'s "
                f"{problem['nearest_tier']}, which establishes {problem['requires']}",
                "move its horizon out, or bring the establishing initiative's in",
            )
        )
    established = core.established(reg, pf)
    committed = {
        d.get("id")
        for d in s.portfolio.data.get("initiatives") or []
        if (d.get("status") or {}).get("value") == "committed"
    }
    makers: dict[str, set[str]] = {}
    for d in reg.initiatives:
        for c in d.establishes:
            makers.setdefault(_ref(c)[1], set()).add(d.id)
    for d in reg.initiatives:
        if d.id not in committed:
            continue
        for c in (_ref(x)[1] for x in d.requires):
            if c not in established and not (makers.get(c, set()) - {d.id}) & committed:
                out.append(
                    _f(
                        "8.2",
                        s.portfolio,
                        ("initiatives", pos.get(d.id, 0), "status"),
                        f"{d.id} is committed, but its prerequisite {c} is neither established nor established by a "
                        "committed initiative",
                        "commit the initiative that establishes it first, or step this one back from committed",
                    )
                )
    return out


# ── GATE-9: a view is what the generator emits, and meets the chapters' voice and figure rules ──────────────────────
STAMP = GENERATED  # the renderer's own pattern for its generation stamp, read from the renderer


# every em- and en-dash form by its Unicode name (the dash itself, its small, two- and three-em and vertical forms),
# written or as an entity
_DASHES = "".join(
    chr(c)
    for c in range(0x2000, 0x10000)
    if re.search(r"\b(EM|EN|TWO-EM|THREE-EM) DASH\b", unicodedata.name(chr(c), ""))
)
DASH = re.compile(
    f"[{_DASHES}]|&[mn]dash;|&#0*(?:{'|'.join(str(ord(c)) for c in _DASHES)});"
    f"|&#x0*(?:{'|'.join(f'{ord(c):x}' for c in _DASHES)});",
    re.IGNORECASE,
)
CHROME = re.compile(r"<(style|script)\b.*?</\1>", re.DOTALL)
# the attributes a page carries for the gates alone (a figure's node and kind, the provenance, the view's source and
# kind): no reader reads them, so the voice rules do not; `data-label`, which the page shows on a phone, is read
MACHINE_ATTRS = re.compile(r'\sdata-(?:node|kind|prov|source|view)="[^"]*"')
FIGURE = re.compile(r"<(figure|svg|img|canvas)\b", re.IGNORECASE)


def _first_difference(a: str, b: str) -> int:
    for n, (x, y) in enumerate(zip(a.splitlines(), b.splitlines(), strict=False), 1):
        if x != y:
            return n
    return min(a.count("\n"), b.count("\n")) + 1


def _site_module(name: str):
    """A module of the site's own (figure_patterns, voice_lint, validate_routes), imported from the site's directory."""
    if str(SITE) not in sys.path:
        sys.path.insert(0, str(SITE))
    return importlib.import_module(name)


def _yaml_item_line(text: str, item: str, key: str) -> int:
    """The line a YAML list holds `item` on, else the line of the list's key, where a finding about it points."""
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.strip().removeprefix("-").strip().strip("'\"") == item and raw.lstrip().startswith(
            "-"
        ):
            return n
    return next((n for n, raw in enumerate(text.splitlines(), 1) if raw.startswith(f"{key}:")), 1)


def _floored(s: Sources, floors: set[str]) -> list[Finding]:
    """A strategy page is never let off declaring its figures, however a pattern-floors.yaml entry spells it: a review
    view by its path (the name the figure-pattern check reads it by) or by a name no other page of the site's carries,
    and a served copy by any spelling of its name (validate_routes.strategy_copy), published or not."""
    rel = "deploy/privatecloudarchitect/site/pattern-floors.yaml"
    path = s.root / rel
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    routes = _site_module("validate_routes")
    copy, fold = routes.strategy_copy, routes.fold_name
    served = {fold(str(e.get("file", ""))) for e in s.pages.values()}
    review = set(s.views) | {fold(Path(v).name) for v in s.views} - served
    return [
        _f(
            "9.2",
            rel,
            (),
            f"{entry!r} names a strategy page in pattern-floors.yaml, which would let its plates go undeclared",
            "remove the entry and declare each plate's pattern in the renderer",
            line=_yaml_item_line(text, entry, "pages"),
        )
        for entry in sorted(floors)
        if entry in review or fold(PurePosixPath(entry).name) in review or copy(entry)
    ]


def gate_9(s: Sources, emitted: dict[str, str] | None = None) -> list[Finding]:
    out = []
    if emitted is None:
        try:
            emitted = s.review()
        except (
            Exception
        ) as e:  # the renderer refuses what it cannot render; say so, and let the other gates speak
            return [
                _f(
                    "9.1",
                    "docs/design/enterprise-strategy-layer/generator/render.py",
                    (),
                    f"the generator could not emit the views: {e}",
                    "fix what the message names; the gate that judges that input names its line",
                    line=_def_line(LAYER / "generator" / "render.py", "docs"),
                )
            ]
    for rel in sorted(set(s.views) | set(emitted)):
        page, fresh = s.views.get(rel), emitted.get(rel)
        if page is None or fresh is None:
            out.append(
                _f(
                    "9.1",
                    rel,
                    (),
                    "the generator emits a view that is not committed"
                    if page is None
                    else "no generator emits this view",
                    "re-render: docs/design/enterprise-strategy-layer/generator/render.py; never write a view by hand",
                    line=1,
                )
            )
            continue
        a, b = stampless(page), stampless(fresh)
        if a != b:
            out.append(
                _f(
                    "9.1",
                    rel,
                    (),
                    "the view is not what the generator emits",
                    "re-render it: docs/design/enterprise-strategy-layer/generator/render.py; never edit a view by hand",
                    line=_first_difference(a, b),
                )
            )
    figure_patterns, voice_lint = _site_module("figure_patterns"), _site_module("voice_lint")
    # the catalog and the floors read once for every page; each line judged once however many pages repeat it (the
    # site's layout is on every page), so the gate's time grows with the words written, not with the pages
    patterns, floors = figure_patterns.catalog(), figure_patterns.floors()
    out += _floored(s, floors)
    rules = [*voice_lint.TELLS, (DASH, "dash", "the house voice uses no em or en dash")]
    # a word every match of each rule contains, so a text without it is not searched for that rule (exact: see
    # required_literal); None searches the rule everywhere
    needs = [required_literal(pat.pattern) for pat, _, _ in rules]
    judged: dict[str, list[tuple[str, str, str]]] = {}

    def tells(raw: str) -> list[tuple[str, str, str]]:
        raw = MACHINE_ATTRS.sub(
            "", raw
        )  # attributes only the gates and the browser read, never a reader
        """The rules a line breaks as written and as decoded (the decoded form searched only where an entity changes
        it); the words as a reader reads them are judged by the stream scan below, across line breaks."""
        if raw not in judged:
            decoded = html.unescape(raw)
            texts = (raw,) if decoded == raw else (raw, decoded)
            folded = tuple(t.casefold() for t in texts)
            found = []
            for (pat, rule, why), need in zip(rules, needs, strict=True):
                if not _could_match(need, folded):
                    continue
                m = next((m for text in texts if (m := pat.search(text))), None)
                if m:
                    found.append((rule, m.group(0), why))
            judged[raw] = found
        return judged[raw]

    for rel, page in s.views.items():
        content, start = _content(page)
        # every line a reader or a search engine reads (title and description included); style and script blanked
        readable = CHROME.sub(lambda m: "\n" * m.group(0).count("\n"), page)
        said: set[tuple[str, int]] = set()
        for n, raw in enumerate(readable.splitlines(), 1):
            # the site's own voice rules on the words a reader reads (entities decoded), and the house ban on em and en
            # dashes, written or escaped
            for rule, hit, why in tells(raw):
                said.add((rule, n))
                out.append(
                    _f(
                        "9.2",
                        rel,
                        (),
                        f"[{rule}] {hit!r}: {why}",
                        "reword it in the renderer",
                        line=n,
                    )
                )
        # the same tells on the words as a reader reads them, one stream across line breaks (a tell split over two
        # source lines reads as one phrase in the browser), each reported at the line where it starts
        stream, starts = _as_read(readable)
        folded_stream = (stream.casefold(),)
        for (pat, rule, why), need in zip(voice_lint.TELLS, needs, strict=False):
            if not _could_match(need, folded_stream):
                continue
            for m in pat.finditer(stream):
                n = next(line for at, line in reversed(starts) if at <= m.start())
                if (rule, n) not in said:
                    said.add((rule, n))
                    out.append(
                        _f(
                            "9.2",
                            rel,
                            (),
                            f"[{rule}] {m.group(0)!r}: {why}",
                            "reword it in the renderer",
                            line=n,
                        )
                    )
        # a figure is a numbered plate that declares its pattern; one outside a plate escapes that rule
        # blank only the plates the figure-pattern check numbers and judges; a figure anywhere else is refused
        outside = figure_patterns.PLATE.sub(
            lambda m: (
                " " * len(m.group(0)) if figure_patterns.NUMBERED.search(m.group(1)) else m.group(0)
            ),
            content,
        )
        for m in FIGURE.finditer(outside):
            out.append(
                _f(
                    "9.2",
                    rel,
                    (),
                    f"a <{m.group(1)}> outside a numbered plate",
                    "render the figure as a plate that declares its pattern (figure-patterns.yaml)",
                    line=_line_at(page, start + m.start()),
                )
            )
        for problem in figure_patterns.check_page(rel, page, patterns, floors):
            out.append(
                _f(
                    "9.2",
                    rel,
                    (),
                    str(problem),
                    "declare the plate's figure pattern in the renderer",
                    line=_root_line(page),
                )
            )
    return out


# ── GATE-10: a view renders, it never restates ─────────────────────────────────────────────────────────────────────
def _texts(node) -> set[str]:
    if isinstance(node, dict):
        return set().union(*(_texts(v) for v in node.values())) if node else set()
    if isinstance(node, list):
        return set().union(*(_texts(v) for v in node)) if node else set()
    return {node} if isinstance(node, str) else set()


def renderer_modules() -> list[Path]:
    """Every generator module the renderer loads, followed through its imports, so a renderer split across modules is
    still read (GATE-10)."""
    gen = LAYER / "generator"
    seen, todo = set(), ["render"]
    while todo:
        name = todo.pop()
        if name in seen or not (gen / f"{name}.py").exists():
            continue
        seen.add(name)
        for n in ast.walk(ast.parse((gen / f"{name}.py").read_text())):
            if isinstance(n, ast.Import):
                todo += [
                    a.name.split(".", 1)[1] for a in n.names if a.name.startswith("generator.")
                ]
            if isinstance(n, ast.ImportFrom):
                if n.module and n.module.startswith("generator."):
                    todo.append(n.module.split(".", 1)[1])
                elif n.module == "generator" or (n.level and not n.module):
                    todo += [a.name for a in n.names]
                elif n.level and n.module:
                    todo.append(n.module)
    return sorted(gen / f"{m}.py" for m in seen)


def _shape_keys(tree: ast.AST) -> set[int]:
    """The keys of `ENTRY_VALUES`, where the models declare the shape each entry's readers read: a policy id there types
    the entry it names, as a loader call reads it."""
    keys: set[int] = set()
    for n in ast.walk(tree):
        target = (
            n.target
            if isinstance(n, ast.AnnAssign)
            else n.targets[0]
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            else None
        )
        if (
            isinstance(target, ast.Name)
            and target.id == "ENTRY_VALUES"
            and isinstance(n.value, ast.Dict)
        ):
            keys |= {id(k) for k in n.value.keys if isinstance(k, ast.Constant)}
    return keys


def _table_constants(tree: ast.AST, name: str) -> set[int]:
    """Every literal inside a module-level table assigned to `name` (migrate.RENAMED: the value ids a schema change
    moved, which the register then holds as a live id and a tombstone): the table that carries a file from one schema
    to the next names those ids by design, and restates no fact a view shows."""
    out: set[int] = set()
    for n in ast.walk(tree):
        target = (
            n.target
            if isinstance(n, ast.AnnAssign)
            else n.targets[0]
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            else None
        )
        if isinstance(target, ast.Name) and target.id == name and n.value is not None:
            out |= {id(c) for c in ast.walk(n.value) if isinstance(c, ast.Constant)}
    return out


def gate_10(s: Sources, code: list[Path] | None = None) -> list[Finding]:
    """A fact the register or the portfolio holds, typed into the code that renders a view. A view's file is held by
    GATE-9 (it is what the renderer emits), so a restated fact can only enter through the renderer's or the core's
    literals. Scoped to text: an id, or a phrase of three words or more; a number cannot be told from an unrelated one."""
    facts = {
        t
        for t in _texts(s.register.data) | _texts(s.portfolio.data)
        if (len(t.split()) >= 3 or re.fullmatch(r"[A-Za-z0-9]+(-[A-Za-z0-9]+)+", t)) and len(t) >= 8
    }
    # the policy's own ids (an entry, a method): one passed to a loader call reads the policy and restates nothing
    policy_ids = {e.get("id") for e in s.policy.data.get("entries") or []} | {
        m.get("id") for m in s.policy.data.get("methods") or []
    }
    # every module the renderer loads, so a renderer split across modules is still read
    code = code or renderer_modules()
    out = []
    for path in code:
        tree, nodes = _parsed(path)
        # the loader's own `self` only in the loader; anywhere else a receiver named self is no policy
        reading = _read_args(
            tree, receivers=POLICY_RECEIVERS if path.name == "policy.py" else {"pol"}, nodes=nodes
        )
        # the models' own declaration of each entry's shape names the entry it types, and restates nothing
        if path.name == "models.py":
            reading |= _shape_keys(tree)
        # the schema change's own table of moved value ids names them by design (40-BREADTH.md step 2)
        moved = _table_constants(tree, "RENAMED") if path.name == "migrate.py" else set()
        for n in nodes:
            if (
                isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and n.value in facts
                and not (id(n) in reading and n.value in policy_ids)
                and id(n) not in moved
            ):
                out.append(
                    _f(
                        "10.1",
                        str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                        (),
                        f"the renderer types {n.value!r}, which the register or the portfolio holds",
                        "read it from the register or the portfolio",
                        line=n.lineno,
                    )
                )
    return out


# ── GATE-11: trigger events and their effects ──────────────────────────────────────────────────────────────────────
def gate_11(s: Sources) -> list[Finding]:
    out = []
    events = {t.get("id") for t in s.register.data.get("trigger_events") or []} | {
        t.get("id") for t in s.portfolio.data.get("trigger_events") or []
    }
    for doc, key in ((s.register, "trigger_events"), (s.portfolio, "trigger_events")):
        for i, t in enumerate(doc.data.get(key) or []):
            did = bool(t.get("reopened")) or bool(t.get("spawned"))
            if not did and not t.get("no_change"):
                out.append(
                    _f(
                        "11.1",
                        doc,
                        (key, i),
                        f"the trigger event {t.get('id')} re-opened nothing and spawned nothing",
                        "record what it re-opened or spawned, or mark it `no_change: true`",
                    )
                )
            if did and t.get("no_change"):
                out.append(
                    _f(
                        "11.2",
                        doc,
                        (key, i, "no_change"),
                        f"the trigger event {t.get('id')} is marked no_change and re-opened or spawned",
                        "drop `no_change`, or the re-opened and spawned lists",
                    )
                )
    scans = {x.get("id") for x in _listed(s.register.data.get("scans"))} | {
        x.get("id") for x in _listed(s.portfolio.data.get("scans"))
    }
    spawned_by = {
        t.get("id"): set(_listed(t.get("spawned")))
        for doc, key in ((s.register, "trigger_events"), (s.portfolio, "trigger_events"))
        for t in _listed(doc.data.get(key))
    }
    for doc, p, d in _inits(s):
        if d.get("from_scan") and d.get("from_scan") not in scans:
            out.append(
                _f(
                    "11.4",
                    doc,
                    (*p, "from_scan"),
                    f"{d.get('id')} comes from the scan {d.get('from_scan')!r}, which no scan records",
                    "record the scan under `scans`, or correct the id",
                )
            )
        if d.get("from_event") and d.get("from_event") not in events:
            out.append(
                _f(
                    "11.3",
                    doc,
                    (*p, "from_event"),
                    f"{d.get('id')} comes from the event {d.get('from_event')!r}, which no trigger event records",
                    "record the event under `trigger_events`, or correct the id",
                )
            )
        elif d.get("from_event") and d.get("id") not in spawned_by.get(d.get("from_event"), ()):
            out.append(
                _f(
                    "11.8",
                    doc,
                    (*p, "from_event"),
                    f"{d.get('id')} comes from the event {d.get('from_event')!r}, whose `spawned` does not name it",
                    "name the initiative in the event's `spawned`, or correct the initiative's `from_event`",
                )
            )
    # step 5: the scan's, the signals', the drivers' and the events' references, each resolving to what it names
    signals = {x.get("id") for x in _listed(s.register.data.get("signals"))}
    watches = {w.get("id") for w in _listed(s.register.data.get("watch_list"))}
    for doc, key in ((s.register, "scans"), (s.portfolio, "scans")):
        for i, sc in enumerate(_listed(doc.data.get(key))):
            for j, area in enumerate(_listed(sc.get("areas"))):
                for k, f in enumerate(_listed(area.get("found"))):
                    if f not in signals:
                        out.append(
                            _f(
                                "11.5",
                                doc,
                                (key, i, "areas", j, "found", k),
                                f"the scan {sc.get('id')} found {f!r} in its {area.get('area')} area, which no signal records",
                                "record the signal under `signals`, or correct the id",
                            )
                        )
    for i, sig in enumerate(_listed(s.register.data.get("signals"))):
        if sig.get("watch") and sig.get("watch") not in watches:
            out.append(
                _f(
                    "11.6",
                    s.register,
                    ("signals", i, "watch"),
                    f"the signal {sig.get('id')} was found by the watch entry {sig.get('watch')!r}, which the watch list does not hold",
                    "name the watch entry that found it, or drop `watch`",
                )
            )
    written = {c.get("id") for c in _listed(s.register.data.get("capabilities"))} | {
        c.get("id") for c in _listed(s.portfolio.data.get("local_capabilities"))
    }
    planned = set(_listed(s.register.data.get("planned_capabilities")))
    for doc, key in ((s.register, "drivers"), (s.portfolio, "drivers")):
        for i, d in enumerate(_listed(doc.data.get(key))):
            for k, st in enumerate(_listed(d.get("stresses"))):
                if st.get("capability") not in written:
                    out.append(
                        _f(
                            "11.7",
                            doc,
                            (key, i, "stresses", k, "capability"),
                            f"the driver {d.get('id')} stresses {st.get('capability')!r}, which no written capability is",
                            "name a written capability, or list a planned one under `stresses_planned`",
                        )
                    )
            for k, c in enumerate(_listed(d.get("stresses_planned"))):
                if (
                    c not in planned and c not in written
                ):  # a written capability stays here until DEC-19 is ruled
                    out.append(
                        _f(
                            "11.7",
                            doc,
                            (key, i, "stresses_planned", k),
                            f"the driver {d.get('id')} names {c!r} as a planned stress, which neither the planned list nor the register holds",
                            "name a planned or written capability",
                        )
                    )
    drivers = {d.get("id") for d in _listed(s.register.data.get("drivers"))} | {
        d.get("id") for d in _listed(s.portfolio.data.get("drivers"))
    }
    initiatives = {d.get("id") for _doc, _p, d in _inits(s)}
    for doc, key in ((s.register, "trigger_events"), (s.portfolio, "trigger_events")):
        for i, t in enumerate(_listed(doc.data.get(key))):
            if t.get("driver") and t.get("driver") not in drivers:
                out.append(
                    _f(
                        "11.9",
                        doc,
                        (key, i, "driver"),
                        f"the trigger event {t.get('id')} names the driver {t.get('driver')!r}, which no driver is",
                        "name a register driver, or drop `driver`",
                    )
                )
            for k, x in enumerate(_listed(t.get("spawned"))):
                if x not in initiatives:
                    out.append(
                        _f(
                            "11.10",
                            doc,
                            (key, i, "spawned", k),
                            f"the trigger event {t.get('id')} spawned {x!r}, which no initiative is",
                            "record the initiative, or correct the id",
                        )
                    )
    return out


# ── GATE-12: a hand-off lands only on a published page that teaches the part ───────────────────────────────────────
def gate_12(s: Sources) -> list[Finding]:
    out = []
    for doc, p, c in _caps(s):
        cid = c.get("id")
        for ledger in ("establish", "sustain"):
            for j, part in enumerate(c.get(ledger) or []):
                # a part the register marks untaught is one with an untaught hand-off: it goes to no page at all
                untaught = any(h.get("kind") == "untaught" for h in part.get("handoff") or [])
                for k, h in enumerate(part.get("handoff") or []):
                    path = (*p, ledger, j, "handoff", k)
                    pages = h.get("pages") or []
                    if h.get("kind") == "untaught" and doc is s.register and not _on_record(h):
                        out.append(
                            _f(
                                "12.3",
                                doc,
                                path,
                                f"{cid}.{part.get('id')} is untaught and names no lane or has no message on record",
                                "write its lane and its message, {sent, answer, answered}, the answer null and "
                                "pending until the lane answers",
                            )
                        )
                    if pages and untaught:
                        out.append(
                            _f(
                                "12.1",
                                doc,
                                path,
                                f"{cid}.{part.get('id')} is untaught and is handed to {', '.join(pages)}",
                                "hand an untaught part to no page; list it with its category and lane",
                            )
                        )
                    for page in pages:
                        if not _page_published(s, page):
                            out.append(
                                _f(
                                    "12.2",
                                    doc,
                                    path,
                                    f"{cid}.{part.get('id')} is handed to {page}, which is not published",
                                    "hand it to a published page, or update this line in the change that moved or "
                                    "unpublished the page",
                                )
                            )
    return out


# ── GATE-14: built to change ───────────────────────────────────────────────────────────────────────────────────────
def _forbidden(pol: Loaded) -> set[str]:
    out = {t["id"] for t in pol.get("planning-tiers")} | {
        lv.id for m in pol.model.methods for lv in m.levels or []
    }
    out |= {m.id for m in pol.model.methods}

    def durations(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from durations(v)
        elif isinstance(o, list):
            for v in o:
                yield from durations(v)
        elif isinstance(o, str) and o.startswith("P") and o[1:2].isdigit():
            yield o

    for e in pol.model.entries:
        out |= set(durations(e.value))
    return out


def scan(paths: list[Path], pol: Loaded) -> list[tuple[Path, int, str]]:
    """GATE-14's first clause: a duration or identifier the policy defines, written as a literal outside the loader.
    Two forms are reading, not writing: an id passed to a loader call, and a method's implementation naming itself
    (`METHOD = "..."`)."""
    forbidden, found = _forbidden(pol), []
    for path in paths:
        if path.name in LOADER_FILES:
            continue
        tree, nodes = _parsed(path)
        allowed = set()
        for n in nodes:
            if isinstance(n, ast.Assign):
                names = {t.id for t in n.targets if isinstance(t, ast.Name)} | {
                    e.id
                    for t in n.targets
                    if isinstance(t, ast.Tuple)
                    for e in t.elts
                    if isinstance(e, ast.Name)
                }
                if "METHOD" in names:
                    allowed |= {id(c) for c in ast.walk(n.value) if isinstance(c, ast.Constant)}
        allowed |= _read_args(tree, nodes=nodes)
        for n in nodes:
            if (
                isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and n.value in forbidden
                and id(n) not in allowed
            ):
                found.append((path, n.lineno, n.value))
    return found


_TREES: dict[str, tuple[ast.AST, list[ast.AST]]] = {}


def _parsed(path: Path) -> tuple[ast.AST, list[ast.AST]]:
    """A module's tree and every node of it, parsed and walked once per text: GATE-10 and GATE-14 each read the
    renderer's modules, and each read them more than once."""
    text = path.read_text()
    if text not in _TREES:
        tree = ast.parse(text)
        _TREES[text] = (tree, list(ast.walk(tree)))
    return _TREES[text]


POLICY_RECEIVERS = {
    "pol",
    "self",
}  # the loaded policy, its estate view (pol.for_estate(...)), and the loader's own


def _root(node: ast.AST) -> str | None:
    """The name an expression is rooted in: pol for pol.for_estate(...).get, caps for caps.get."""
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _read_args(
    tree: ast.AST, receivers: set[str] | None = None, nodes: list[ast.AST] | None = None
) -> set[int]:
    """The literals a module passes as the first argument of a loader call, or of a method naming itself where it
    registers (@implements("id", version)) or where the policy resolves the method an entry selects
    (run_method("entry", ...)): reading the policy, never writing or restating a value."""
    out = set()
    for n in nodes if nodes is not None else ast.walk(tree):
        loader = (
            isinstance(n.func, ast.Attribute)
            and n.func.attr in LOADER_CALLS
            and (
                receivers is None or _root(n.func.value) in receivers
            )  # a dict's own get is no loader
            if isinstance(n, ast.Call)
            else False
        )
        if isinstance(n, ast.Call) and (
            loader or getattr(n.func, "id", getattr(n.func, "attr", None)) in SELF_NAMING
        ):
            out |= {id(a) for a in n.args[:1] if isinstance(a, ast.Constant)}
    return out


def code_paths(root: Path = ROOT) -> list[Path]:
    return sorted(p for rel in CODE for p in (root / rel).glob("*.py"))


ISO = re.compile(r"\bP(?:\d+[YMWD])+\b")
META = re.compile(r'<meta\b[^>]*\bcontent="([^"]*)"[^>]*>')
PROV = re.compile(r'<p class="prov"(?: data-prov="(?P<data>[^"]*)")?>.*?</p>', re.DOTALL)


def _figures(data: dict):
    """Every figure of a portfolio (a mapping carrying a `kind`) with the path of keys and indices that locates it in
    the file and its node address (served.KEYS' form, a keyed item by its key); the approvals and the policy aside."""
    from . import served as _served

    def walk(node, path: tuple, address: tuple):
        if isinstance(node, dict):
            if "kind" in node and len(address) > 1:
                yield path, address, node
            for k, v in node.items():
                yield from walk(v, (*path, k), (*address, str(k)))
        elif isinstance(node, list):
            key = _served.KEYS.get(_served._pattern(address))
            for i, item in enumerate(node):
                if (
                    key is None
                ):  # a list no key addresses (evidence, loops, stages) holds no addressable node
                    continue
                try:
                    label = str(key(item))
                except (KeyError, TypeError):
                    label = str(i)
                yield from walk(item, (*path, i), (*address, label))

    for top, value in data.items():
        if top in ("approval", "approvals", "policy"):
            continue
        yield from walk(value, (top,), (top,))


def gate_14(s: Sources, code: list[Path] | None = None) -> list[Finding]:
    out = []
    raw = s.policy.data
    required = ("value", "decided_by", "since", "effective_from", "change", "read_by")
    for i, e in enumerate(raw.get("entries") or []):
        missing = [k for k in required if k not in e or (k == "decided_by" and not e.get(k))]
        if missing:
            out.append(
                _f(
                    "14.3",
                    s.policy,
                    ("entries", i),
                    f"the entry {e.get('id')} has no {', '.join(missing)}",
                    "write its value, the decisions that set it, the version and date it arrived, its change class "
                    "and what reads it",
                )
            )
    # judged on the files as written, so an override is judged whether or not the estate's view loads; an item that
    # is no mapping is the portfolio model's to refuse
    entries = {e.get("id"): e for e in raw.get("entries") or [] if isinstance(e, dict)}
    for i, o in enumerate(((s.portfolio.data.get("policy") or {}).get("overrides")) or []):
        if not isinstance(o, dict):
            continue
        e = entries.get(o.get("entry"))
        why = (
            "an entry policy.yaml does not hold"
            if e is None
            else "an entry marked one-way"
            if e.get("one_way")
            else "an entry not marked overridable"
            if not e.get("overridable")
            else "no decision"
            if not str(o.get("decided_by") or "").strip()  # a blank is no decision
            else None
        )
        if why:
            out.append(
                _f(
                    "14.8",
                    s.portfolio,
                    ("policy", "overrides", i),
                    f"the override of {o.get('entry')!r} is of {why}",
                    "override only an entry marked overridable, never one-way, with the decision-log entry that made it",
                )
            )
    # 14.9 (step 9): a run's import supplies fields of the portfolio; a node the portfolio types under one of its paths
    # is refused, whatever its kind (an imported field has one writer, the system of record), and so is an import
    # supplying a field the portfolio does not say it imports; one address grammar, served.address_of. Judged only when
    # a run passes an import; the adopter's companion reports the clause not covered otherwise, never passed.
    if s.imports is not None:
        from . import served as _served

        named = set(((s.portfolio.data.get("ownership") or {}).get("imports") or {}).keys())
        prefixes: list[tuple[str, ...]] = []
        for field, paths in s.imports.items():
            if field not in named:
                out.append(
                    _f(
                        "14.9",
                        s.portfolio,
                        ("ownership", "imports"),
                        f"the run's import supplies {field!r}, a field the portfolio does not import",
                        "import only a field ownership.imports names, or type the field and drop it from the import",
                    )
                )
                continue
            prefixes += [_served.address_of(x) for x in paths or []]
        for path, address, _node in _figures(s.portfolio.data):
            if any(_served.under(address, x) for x in prefixes):
                out.append(
                    _f(
                        "14.9",
                        s.portfolio,
                        path,
                        f"the portfolio types {'/'.join(address)}, which the run's import supplies",
                        "drop the typed value: an imported field has one writer, the system of record",
                    )
                )
    pol = s.loaded()
    # the clauses that read the loaded policy cannot judge; the run says why (not covered)
    if pol is None:
        return out
    for path, line, value in scan(code or code_paths(s.root), pol) if s.judges("14.1") else []:
        out.append(
            _f(
                "14.1",
                str(path.relative_to(s.root)) if path.is_relative_to(s.root) else str(path),
                (),
                f"writes {value!r}, which policy.yaml defines",
                "read it through the policy loader",
                line=line,
            )
        )
    # A view is what the generator emits (GATE-9) from code that types no policy value (above), so what is left to
    # judge is a value that reaches the reader raw: a duration in its ISO form, or a tier by its id where the policy
    # gives it a label. A level has no label, so its id is its name.
    # a tier by its id, or by its id as words (the renderer's `words`), where the policy gives it a label
    tiers = {t["id"] for t in pol.get("planning-tiers")}
    tiers |= {t.replace("-", " ") for t in tiers}
    raw_values: dict[str, set[str]] = {}  # each line judged once however many pages repeat it

    def raw_shown(text: str) -> set[str]:
        if text not in raw_values:
            body = re.sub(
                r"<[^>]+>", " ", META.sub(r" \1 ", text)
            )  # a description's words are read too
            raw_values[text] = set(ISO.findall(body)) | {
                w
                for w in tiers
                if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", body, re.IGNORECASE)
            }
        return raw_values[text]

    for rel, page in s.views.items():
        # every line a reader or a search engine reads, the head included; the provenance names ids by design
        readable = CHROME.sub(
            lambda m: "\n" * m.group(0).count("\n"), PROV.sub(lambda m: " " * len(m.group(0)), page)
        )
        for n, text in enumerate(readable.splitlines(), 1):
            for w in sorted(raw_shown(text)):
                out.append(
                    _f(
                        "14.2",
                        rel,
                        (),
                        f"the view shows {w!r}, a value policy.yaml holds, in its raw form",
                        "render it through the loader: a duration in words, a tier or level by its label",
                        line=n,
                    )
                )
    for problem in check_vocabularies(
        pol, {"register": s.register.data, "portfolio": s.portfolio.data}
    ):
        where = problem.split(":", 1)[0]
        doc = s.register if where.startswith("register") else s.portfolio
        out.append(
            _f(
                "14.4",
                doc,
                _path_of(where),
                problem.split(": ", 1)[1],
                "use a member of the vocabulary, or add the member to policy.yaml by its ruling",
            )
        )
    typed = s.typed()
    if typed:
        reg, pf, _ = typed
        prov = (s.report() or core.report(reg, pf, pol))["provenance"]
        for f_ in pol.model.provenance.fields:
            if f_ not in prov:
                out.append(
                    _f(
                        "14.5",
                        "docs/design/enterprise-strategy-layer/generator/core.py",
                        (),
                        f"the generated report carries no {f_!r} in its provenance",
                        "stamp every provenance field policy.yaml names on every output",
                        line=_def_line(LAYER / "generator" / "core.py", "provenance"),
                    )
                )
    for rel, page in s.views.items():
        m = PROV.search(page)
        data = json.loads(html.unescape(m.group("data"))) if m and m.group("data") else {}
        missing = [
            f_ for f_ in pol.model.provenance.fields if f_ != "generated_at" and f_ not in data
        ]
        statuses = set(pol.vocabulary("method_status"))
        methods = data.get("methods") if isinstance(data.get("methods"), dict) else {}
        if "methods" in data and not (
            isinstance(
                data.get("methods"), dict
            )  # empty for a page that used no method of the policy's
            and all(
                isinstance(v, dict)
                and isinstance(v.get("version"), int)
                and v.get("status") in statuses
                for v in methods.values()
            )
        ):
            missing.append("each method's version and status")
        if not m or not stamp_shaped(
            page
        ):  # every provenance line's stamp present and in shape, whatever the fields list
            missing.append("generated_at")
        if missing or data.get("policy_version") != pol.model.policy_version:
            out.append(
                _f(
                    "14.5",
                    rel,
                    (),
                    f"the view's provenance lacks {', '.join(missing) or 'the current policy version'}",
                    "re-render it: every view ends with every provenance field policy.yaml names",
                    line=_line_at(page, m.start()) if m else _root_line(page),
                )
            )
    for i, m in enumerate(
        raw.get("methods") or [] if s.judges("14.6") else []
    ):  # a git and test lookup
        d = m.get("definition") or {}
        golden = m.get("golden")
        problems = []
        if not d.get("text"):
            problems.append("no definition")
        if not d.get("at_commit"):
            problems.append("a definition pinned to no commit")
        elif subprocess.run(
            ["git", "-C", str(s.git or s.root), "cat-file", "-e", f"{d['at_commit']}^{{commit}}"],
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},  # never fetch from a promisor remote
            capture_output=True,
        ).returncode:
            problems.append(f"a definition pinned to {d['at_commit']}, which is not a commit here")
        test = (golden or {}).get("test") if isinstance(golden, dict) else None
        if not test:
            problems.append("no golden test named")
        else:
            file_, _, name = test.partition("::")
            held = s.root / file_
            if not (
                held.exists()
                and re.search(rf"^def {re.escape(name)}\(", held.read_text(), re.MULTILINE)
            ):
                problems.append(f"a golden test, {test}, that is not on disk")
        if problems:
            out.append(
                _f(
                    "14.6",
                    s.policy,
                    ("methods", i),
                    f"the method {m.get('id')} version {m.get('version')} has {', '.join(problems)}",
                    "pin its definition to the commit that ratified it and name its golden fixture",
                )
            )
    if s.judges("14.7"):  # the lock is this repository's file
        lock = Doc.read("docs/design/enterprise-strategy-layer/generator/schema.lock.yaml", s.root)
        for name, model in models.MODELS.items():
            version = models.SCHEMA_VERSIONS[name]
            if (lock.data.get(name) or {}).get(version) != models.fingerprint(model):
                out.append(
                    _f(
                        "14.7",
                        lock,
                        (name,),
                        f"{name}'s model no longer matches the fingerprint pinned for schema version {version}",
                        "give the file a new schema version with a migration, and pin the new fingerprint",
                    )
                )
    return out


def _def_line(path: Path, name: str) -> int | None:
    """The line a module defines a function on."""
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n.lineno
    return None


def _path_of(where: str) -> tuple:
    parts: list[str | int] = []
    for tok in re.findall(r"[^.\[\]]+|\[\d+\]", where.split(".", 1)[1] if "." in where else ""):
        parts.append(int(tok[1:-1]) if tok.startswith("[") else tok)
    return tuple(parts)


# ── running them ────────────────────────────────────────────────────────────────────────────────────────────────────
# ── GATE-15: the front door (schema 6; DEC-06, 50-FRONT-DOOR.md section 9) ───────────────────────────────────────────
FRONT_DOOR_REL = "deploy/privatecloudarchitect/site/src/strategy-front-door.json"


def _link_paths(entries: list) -> list:
    """A door's entries as paths: a plain path, or the path of `{path, words}` (schema 7)."""
    return [e.get("path") if isinstance(e, dict) else e for e in entries]


def gate_15(s: Sources) -> list[Finding]:
    """The readers' doors and the feed the home renderer reads: a register that names no reader; a door that opens a
    view the policy does not publish, or pairs with a page the site does not serve; and the committed feed that is not
    what the generator emits from these files, or is absent, so the landing page never draws a door from a stale feed."""
    out = []
    readers = _listed(s.register.data.get("readers"))
    if not readers and s.judges("15.1"):
        out.append(
            _f(
                "15.1",
                s.register,
                ("readers",),
                "the register names no reader; the front door has no door to draw",
                "write the readers the charter's section 6 names, each with its door in both layers",
                line=s.register.line("readers") or 1,
            )
        )
    published = _published_pages(s)
    for i, r in enumerate(readers):
        door = r.get("door") if isinstance(r, dict) else None
        if not isinstance(door, dict):
            continue
        if published is not None and s.judges("15.2") and isinstance(door.get("strategy"), list):
            for j, p in enumerate(_link_paths(door["strategy"])):
                if p not in published:
                    out.append(
                        _f(
                            "15.2",
                            s.register,
                            ("readers", i, "door", "strategy", j),
                            f"the {r.get('id')}'s door opens {p}, which `strategy-pages` does not publish",
                            "publish the view in policy.yaml's `strategy-pages`, or open a published one",
                        )
                    )
        if s.judges("15.3") and isinstance(door.get("handbook"), list):
            for j, p in enumerate(_link_paths(door["handbook"])):
                if str(p).partition("#")[0] not in s.pages:
                    out.append(
                        _f(
                            "15.3",
                            s.register,
                            ("readers", i, "door", "handbook", j),
                            f"the {r.get('id')}'s door pairs with {p}, which the site does not serve",
                            "pair the door with a page deploy/privatecloudarchitect/site/src/pages.json holds",
                        )
                    )
    if s.judges("15.4") and not out:  # judged on the typed files once the doors themselves pass
        try:
            typed = s.typed()
        except Exception:  # the models' refusal is GATE-14's to name
            typed = None
        if typed is not None:
            from generator import render

            reg, pf, pol = typed
            try:
                emitted = render.emit_front_door(pol=pol, reg=reg, pf=pf)
            except Exception as e:  # the renderer refuses what the doors cannot open; say so once
                emitted = None
                out.append(
                    _f(
                        "15.4",
                        FRONT_DOOR_REL,
                        (),
                        f"the generator could not emit the feed: {e}",
                        "fix what the message names, then render and commit the feed",
                        line=1,
                    )
                )
            if emitted is not None and s.front_door != emitted:
                out.append(
                    _f(
                        "15.4",
                        FRONT_DOOR_REL,
                        (),
                        "the committed feed is absent"
                        if s.front_door is None
                        else "the committed feed is not what the generator emits from these files",
                        "run `python -m generator.render` from docs/design/enterprise-strategy-layer and commit the "
                        "feed with the register that moved it",
                        line=1,
                    )
                )
    return out


GATES = {
    "GATE-1": gate_1,
    "GATE-2": gate_2,
    "GATE-3": gate_3,
    "GATE-4": gate_4,
    "GATE-5": gate_5,
    "GATE-6": gate_6,
    "GATE-7": gate_7,
    "GATE-8": gate_8,
    "GATE-9": gate_9,
    "GATE-10": gate_10,
    "GATE-11": gate_11,
    "GATE-12": gate_12,
    "GATE-14": gate_14,
    "GATE-15": gate_15,
}
NEEDS_TYPED = {
    "GATE-8"
}  # judged on the derived tiers, so only once the files load through their models
NEEDS_VIEWS = {"GATE-9"}
# Gates with a clause judged only on the typed models (6.2, the board's labels in 7.3, the report's provenance in
# 14.5): when the models do not load and nothing else was refused, the gate has not judged, so it is not covered.
PARTLY_TYPED = {"GATE-6", "GATE-7", "GATE-14", "GATE-15"}
# Gates with a clause judged only on the loaded policy (3.3, on its value categories): when the policy does not load
# and nothing else was refused, the gate has not judged, so it is not covered.
PARTLY_LOADED = {"GATE-3"}


RENDER_REL = "docs/design/enterprise-strategy-layer/generator/render.py"


def _untyped_at(s: Sources) -> tuple[str, int] | None:
    """Where the models refused a file: the file and the line of the field, as `typed()` found it."""
    return getattr(s, "untyped_at", None)


def run(s: Sources, gates: tuple[str, ...] = STRUCTURAL) -> list[Result]:
    results = []
    for g in gates:
        try:  # a precondition that raises leaves its gate not covered, and the others still run
            untyped = (g in NEEDS_TYPED or g in PARTLY_TYPED) and s.typed() is None
            unloaded = g in PARTLY_LOADED and s.loaded() is None
        except Exception as e:
            results.append(Result(g, "not_covered", [], f"{type(e).__name__}: {e}", _where(e)))
            continue
        if g in NEEDS_TYPED and untyped:
            results.append(Result(g, "not_covered", [], s.why_untyped(), _untyped_at(s)))
            continue
        if g in NEEDS_VIEWS and not s.views:
            results.append(
                Result(
                    g,
                    "not_covered",
                    [],
                    "no view is rendered",
                    (RENDER_REL, _def_line(LAYER / "generator" / "render.py", "docs") or 1),
                    f"render the views: {RENDER_REL}",
                )
            )
            continue
        try:
            judged = GATES[g](s)
        except (
            Exception
        ) as e:  # a gate that could not judge has not passed (P-027), and the others still run
            results.append(Result(g, "not_covered", [], f"{type(e).__name__}: {e}", _where(e)))
            continue
        # a listed finding rides beside the state and never refuses (40-BREADTH.md step 2)
        found = [f for f in judged if not f.listed]
        listed = [f for f in judged if f.listed]
        if not found and g in PARTLY_TYPED and untyped:
            results.append(
                Result(g, "not_covered", [], s.why_untyped(), _untyped_at(s), listed=listed)
            )
            continue
        if not found and g in PARTLY_LOADED and unloaded:
            results.append(
                Result(
                    g,
                    "not_covered",
                    [],
                    "the policy as the estate runs it does not load "
                    f"({getattr(s, 'unloaded', 'its model refuses it')})",
                    getattr(s, "unloaded_at", None),
                    listed=listed,
                )
            )
            continue
        # refused on what it could judge, while a clause that needs the models or the loaded policy was not judged:
        # the refusal stands, and it says which clauses went unjudged and why, so a second cause is never silent
        unjudged = (
            s.why_untyped()
            if g in PARTLY_TYPED and untyped
            else "the policy as the estate runs it does not load "
            f"({getattr(s, 'unloaded', 'its model refuses it')})"
            if g in PARTLY_LOADED and unloaded
            else None
        )
        why = (
            f"refused on the clauses it could judge; those that need the models or the loaded policy were not judged: "
            f"{unjudged}"
            if found and unjudged
            else None
        )
        results.append(
            Result(
                g,
                "refused" if found else "passed",
                found,
                why,
                (
                    _untyped_at(s)
                    if g in PARTLY_TYPED and untyped
                    else getattr(s, "unloaded_at", None)
                )
                if why
                else None,
                listed=listed,
            )
        )
    return [scrubbed(r, s.lists) for r in results]


def _strategy_entry(entry: dict) -> bool:
    """An entry the strategy generator owns, as the site defines it (validate_routes.strategy_entry)."""
    return _site_module("validate_routes").strategy_entry(entry)


def _json_entry_line(text: str, path: str | None, key: str, nth: int = 0) -> int:
    """The line the `nth` pages.json entry with this path names it on (a second entry for one path at its own line),
    else the line of the list's key."""
    if path is not None:
        found = list(re.finditer(r'"path":\s*' + re.escape(json.dumps(path)), text))
        if len(found) > nth:
            return _line_at(text, found[nth].start())
    m = re.search(rf'"{key}":', text)
    return _line_at(text, m.start()) if m else 1


# ── S4: the served rendering judged (40-BREADTH.md step 2) ──────────────────────────────────────────────────────────
SPAN_TOKEN = re.compile(r"<span\b[^>]*>|</span>")
WRAPPER = re.compile(r'<span(?: data-node="(?P<node>[^"]*)")? data-kind="(?P<kind>[^"]*)">')
LABEL = {"illustrative": '<span class="illus">illustrative</span>', "input": "(supplied by "}


def wrappers(page: str) -> list[tuple[str | None, str, int, int]]:
    """Each figure's wrapper on a page, `render.fig`'s `<span data-node data-kind>`, as (node, kind, start, end), its
    end past its closing tag, nested spans counted."""
    out, stack = [], []
    for m in SPAN_TOKEN.finditer(page):
        if m.group(0) == "</span>":
            if stack:
                opened = stack.pop()
                if opened is not None:
                    node, kind, start = opened
                    out.append((node, kind, start, m.end()))
            continue
        w = WRAPPER.fullmatch(m.group(0))
        stack.append(
            (html.unescape(w["node"]) if w and w["node"] else None, w["kind"], m.start())
            if w
            else None
        )
    return out


def unlabelled(page: str) -> list[tuple[str | None, str, int]]:
    """Each illustrative or input figure whose wrapper holds no label (clause 7.3 on a served page)."""
    return [
        (node, kind, start)
        for node, kind, start, end in wrappers(page)
        if kind in LABEL and LABEL[kind] not in page[start:end]
    ]


# the fields of each approvable shape a page prints, by the shape's address pattern (served.WITHHOLD's): the canary
# replaces these, and never a duration, a day, a vocabulary member or a key
PRINTED = {
    ("capabilities", "*", "investment", "*"): ("value",),
    ("capabilities", "*", "effort", "*"): ("value",),
    ("capabilities", "*", "targets", "*"): ("value",),
    ("capabilities", "*", "readings", "*"): ("reading",),
    ("assignments", "*"): ("department",),
    ("capacity", "*"): ("value",),
    ("initiatives", "*", "cost_of_delay"): ("delta",),
}
SENTINEL_FROM, SENTINEL_STEP = (
    900000,
    1000,
)  # whole numbers far from any figure, apart by more than any sum of figures


def canary(s, pol) -> list[tuple[tuple, str]]:
    """(address, why) for each illustrative or input node a served page prints outside a wrapper that names it and
    carries its label: the page rendered from its slice with each such node's printed fields replaced by a sentinel.
    A node the page never prints leaves no sentinel and is not judged."""
    from dataclasses import replace as _replace

    from generator import render, served

    data = s.portfolio.model_dump(mode="json", by_alias=True)
    planted: dict[str, tuple[tuple, str]] = {}
    for k, (address, node_form) in enumerate(served.approvable(s.portfolio)):
        if not isinstance(node_form, dict) or node_form.get("kind") not in LABEL:
            continue
        try:
            fields = PRINTED.get(served.shape_of(address), ())
        except ValueError:
            continue
        _parent, _slot, node = served._get(data, address)
        for field_ in fields:
            if node is None or node.get(field_) is None:
                continue
            token = (
                str(SENTINEL_FROM + SENTINEL_STEP * k)
                if isinstance(node[field_], int | float)
                else f"sentinel{k}x"
            )
            node[field_] = int(token) if token.isdigit() else token
            planted[token] = (address, node["kind"])
    marked = _replace(s, portfolio=models.Portfolio.model_validate(data))
    page = render.render_served(marked, pol)[3]
    spans = wrappers(page)
    out = []
    for token, (address, kind) in planted.items():
        for m in re.finditer(rf"(?<![\w.]){re.escape(token)}(?![\w])", page):
            inside = [w for w in spans if w[2] < m.start() < w[3] and w[1] == kind]
            if not any(
                (w[0] is None or tuple(w[0].split("/")) == address)
                and LABEL[kind] in page[w[2] : w[3]]
                for w in inside
            ):
                out.append(
                    (
                        address,
                        f"the {kind} figure at {'/'.join(address)} is printed without its label",
                    )
                )
    return out


def served_losses(committed: dict[str, str], fresh: dict[str, str]) -> list[str]:
    """For a release report: each approved node or row a served copy loses, or whose kind it moves, from the copy the
    site serves to the copy the generator emits now (40-BREADTH.md step 2)."""
    out = []
    for file, before in sorted(committed.items()):
        after = fresh.get(file, "")
        was = {n: k for n, k, _s, _e in wrappers(before) if n}
        now = {n: k for n, k, _s, _e in wrappers(after) if n}
        for node, kind in sorted(was.items()):
            if node not in now:
                out.append(f"{file}: loses {node} ({kind})")
            elif now[node] != kind:
                out.append(f"{file}: {node} moves from {kind} to {now[node]}")
    return out


def _served_labels(frags: dict[str, str]) -> list[str]:
    """S4 on the served copies: every illustrative or input figure's wrapper carries its label, and the canary render of
    each served page finds no such figure printed without it (clause 7.3)."""
    from generator import render, served
    from generator.policy import load_policy, load_portfolio, load_register

    rel = "deploy/privatecloudarchitect/site/src/pages"
    out = []
    for file, page in sorted(frags.items()):
        for node, kind, start in unlabelled(page):
            out.append(
                str(
                    _f(
                        "7.3",
                        f"{rel}/{file}",
                        (),
                        f"the {kind} figure {node or '(derived)'} is printed without its label",
                        "print it through render.fig(), which labels it",
                        line=_line_at(page, start),
                    )
                )
            )
    reg, pf, pol = load_register(), load_portfolio(), load_policy()
    projection = served.project(reg, pf, pol)
    estate = pol.for_estate(pf.policy.overrides)
    comp_map, pages = render._site_vocabulary(estate)
    for path in estate.get("strategy-pages"):
        view = render._view_of(path, reg)
        s = served.slice_of(
            view,
            projection,
            render._site_slice(view, projection.register, comp_map, pages),
            render._records_slice(view, projection.register, estate, projection.portfolio),
        )
        for _address, why in canary(s, pol):
            out.append(
                str(
                    _f(
                        "7.3",
                        f"{rel}/{render.site_file(path)}",
                        (),
                        why + " (the canary render)",
                        "print it through render.fig(), which wraps and labels it",
                        line=1,
                    )
                )
            )
    return out


def site_check(root: Path = ROOT) -> list[str]:
    """What the site build refuses for the strategy pages, in one call (DEC-07; 30-GATES.md step 10): a structural
    gate that does not pass; a strategy page's copy in the site's src/pages/, or its pages.json entry, that is not what
    the generator emits (its generation stamp aside, as GATE-9 sets it aside); and a strategy copy there, however its
    name is spelled, that no `strategy-pages` path publishes. Each line names its file and line, its clause and the
    edit, scrubbed as every finding is; the build prints the call's time."""
    from generator import render

    try:
        results = run(Sources.read(root=root))
    except SourceError as e:
        return [scrub(e.failure())]
    errors = [line for r in results for line in r.failures()]
    try:
        frags, entries = render.site()
        errors += [scrub(x) for x in _served_labels(frags)]
    except Exception as e:  # the generator refuses what it cannot emit; say so, never a traceback
        found = [
            _f(
                "9.1",
                "docs/design/enterprise-strategy-layer/generator/render.py",
                (),
                f"the strategy generator could not emit the site's copies: {e}",
                "fix what the message names; the gate that judges that input names its line",
                line=_def_line(LAYER / "generator" / "render.py", "site"),
            )
        ]
        return [scrub(e) for e in [*errors, *map(str, found)]]
    pages_dir = SITE / "src" / "pages"
    rel = "deploy/privatecloudarchitect/site/src/pages"
    redo = "re-render: docs/design/enterprise-strategy-layer/generator/render.py; never edit a copy by hand"
    found = []
    for file, frag in frags.items():
        path = pages_dir / file
        if not path.exists():
            found.append(
                _f(
                    "9.1",
                    f"{rel}/{file}",
                    (),
                    "a published strategy page with no copy here",
                    redo,
                    line=1,
                )
            )
            continue
        try:
            served = read_text(path, f"{rel}/{file}")
        except (
            SourceError
        ) as e:  # a copy that cannot be read is named at its line, as a stale one is
            found.append(
                _f("9.1", e.at[0], (), f"a copy that cannot be read ({e})", redo, line=e.at[1])
            )
            continue
        have, want = stampless(served), stampless(frag)
        if not stamp_shaped(
            served
        ):  # set aside, but held present and in shape, as GATE-14 holds a view's
            prov = PROV.search(served)
            found.append(
                _f(
                    "14.5",
                    f"{rel}/{file}",
                    (),
                    "its generation stamp is missing or not a UTC time",
                    redo,
                    line=_line_at(served, prov.start()) if prov else 1,
                )
            )
        if have != want:  # the first line that differs, as GATE-9 names a stale view's
            found.append(
                _f(
                    "9.1",
                    f"{rel}/{file}",
                    (),
                    "not what the strategy generator emits",
                    redo,
                    line=_first_difference(have, want),
                )
            )
    copy = _site_module("validate_routes").strategy_copy
    for path in sorted(p for p in pages_dir.rglob("*") if p.is_file() and copy(p.name)):
        name = path.relative_to(pages_dir).as_posix()
        if name not in frags:
            found.append(
                _f(
                    "9.1",
                    f"{rel}/{name}",
                    (),
                    "a strategy page's copy that no `strategy-pages` path in policy.yaml publishes under this name",
                    "remove it, or publish its view there",
                    line=1,
                )
            )
    manifest_rel = "deploy/privatecloudarchitect/site/src/pages.json"
    manifest_text = ""
    try:
        manifest_text = read_text(SITE / "src" / "pages.json", manifest_rel)
        parsed = json.loads(manifest_text)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("pages"), list):
            raise ValueError("it holds no `pages` list")
        bad = next((k for k, x in enumerate(parsed["pages"]) if not isinstance(x, dict)), None)
        if bad is not None:
            raise ValueError(f"its entry {bad} is not a mapping")
    except (
        SourceError,
        ValueError,
    ) as e:  # pages.json that cannot be read, parsed or walked, named at its line
        at = (
            e.at
            if isinstance(e, SourceError)
            else (
                manifest_rel,
                getattr(e, "lineno", None) or _json_entry_line(manifest_text, None, "pages"),
            )
        )
        found.append(
            _f(
                "9.1",
                at[0],
                (),
                f"pages.json cannot be read ({e})",
                "fix the file so it parses",
                line=at[1],
            )
        )
        return [scrub(x) for x in [*errors, *map(str, found)]]
    # a strategy page by its flag, its path or the copy it serves: such an entry is the generator's, whatever it says
    listed = parsed["pages"]
    where = [i for i, p in enumerate(listed) if _strategy_entry(p)]
    have = [listed[i] for i in where]
    if have != entries:
        n = next(
            (k for k, (a, b) in enumerate(zip(have, entries, strict=False)) if a != b),
            min(len(have), len(entries)),
        )
        if n < len(have):
            what = f"its strategy entries are not what the strategy generator emits, from the entry for {have[n].get('path')!r}"
            nth = sum(p.get("path") == have[n].get("path") for p in listed[: where[n]])
            line = _json_entry_line(manifest_text, have[n].get("path"), "pages", nth)
        else:
            what = f"its strategy entries lack the one the strategy generator emits for {entries[n]['path']!r}"
            line = _json_entry_line(manifest_text, None, "pages")
        found.append(_f("9.1", manifest_rel, (), what, redo, line=line))
    return [scrub(e) for e in [*errors, *map(str, found)]]


def main(argv: list[str]) -> int:
    import time

    started = time.perf_counter()
    try:
        results = run(Sources.read(), STRUCTURAL)
    except (
        SourceError
    ) as e:  # nothing can be judged; every gate says so, and the target fails (P-027)
        results = [
            Result(g, "not_covered", [], f"a source could not be read: {scrub(str(e))}", e.at)
            for g in STRUCTURAL
        ]
    for r in (
        results
    ):  # each gate's state, then each of its failures and its listed items in their one form
        print(f"{r.gate}: {r.state}")
        for line in [*r.failures(), *r.listed_lines()]:
            print(f"  {scrub(line)}")
    print(f"strategy gates: {len(results)} judged in {time.perf_counter() - started:.1f} s")
    # a gate that could not judge has not passed (P-027)
    return 1 if any(r.state in ("refused", "not_covered") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
