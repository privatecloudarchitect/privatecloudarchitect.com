#!/usr/bin/env python3
"""Every commit a committed file of the strategy layer names is a landed one (the operator's rule of 2026-11-25,
charter section 1.1; the doctrine line in section 0; G-947).

The rule, as the operator approved it: a committed file names only landed commits. A writer that runs before the land
writes no commit and names its inputs by sha256. Every sha that remains must be an ancestor of HEAD.

The question is reachability, never existence. A commit a rebase rewrote still exists as an object (the reflog and
any other worktree keep it), so `git cat-file -e` passes on exactly the dead reference a rebase leaves behind: on
2026-11-25 five such references passed the gate that way (FM4 of the review of that day). `git merge-base
--is-ancestor <sha> <tip>` is the question a reader's checkout answers, and it is asked here once, for the gate
(GATE-14's 14.6), the charter's test and the lint.

The lint (`dead_references`) reads, at the tip given (HEAD by default):

  * every practice record's `commit` (`instrument/practice/*.json`);
  * every run record's `commit` in the check's tracked log (`runs/log.jsonl`), but the dated history the operator kept
    as written ("Keep as dated history", 2026-11-25): a record run from a checkout up to `RUN_LOG_HISTORY_THROUGH`
    names the worktree commit at run time, which may not be on main, and is not read as a citation;
  * every `at_commit` in `policy.yaml`, each method's definition and the drift-read contract's (a null method pin is
    GATE-14's to judge, by the pending-pin rule);
  * the companion's `pins.json`, which carries no commit from schema 2;
  * the charter's prose, by context, not by every hex token: a backticked token, a token after one of the
    `ANCHORS`, and every token in a status cell of the traceability matrix (section 12) is a commit; a token in a
    sentence that says it "never landed" is dated history; a token after the word companion is that repository's; a
    token after "sha256", "inputs" or "digest" is a content digest, and one after "fingerprint" a schema lock's.
    Any other token with a hex letter and a digit is refused as unclassified, so a new way of writing a commit in the
    charter fails here until it is given its anchor or its rule (the residual risk the review named, closed).

Three outcomes, never two (REQUIRE-009, P-027): every named commit an ancestor (exit 0); a dead reference, each named
by its file and line (exit 1); no git to ask (exit 3, nothing judged; 2 stays argparse's usage error).

Run from the repository root: python3 docs/design/enterprise-strategy-layer/generator/citations.py [--tip REF]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

LAYER = Path(__file__).resolve().parent.parent
ROOT = LAYER.parents[2]
REL = "docs/design/enterprise-strategy-layer"
PRACTICE = f"{REL}/instrument/practice"
RUN_LOG = f"{REL}/runs/log.jsonl"
POLICY = f"{REL}/policy.yaml"
PINS = f"{REL}/companion/pinned/pins.json"
CHARTER = f"{REL}/00-CHARTER.md"
SCOPE = (PRACTICE, RUN_LOG, POLICY, PINS, CHARTER)  # what the lint reads; the repository holds each

# The newest run record the operator kept as dated history (2026-11-25, "Keep as dated history"): a record run from a
# checkout up to this time names the worktree commit at run time, which may not be on main (18 of them name one that is
# not: the 15 the proposal counted and three the release of 2026-11-25 folded after its count). A run record after it
# names a landed commit or none: the fold writes none for a run from a checkout.
RUN_LOG_HISTORY_THROUGH = "2026-11-25T06:05:21Z"

SHA = re.compile(r"[0-9a-f]{7,40}")
TOKEN = re.compile(r"(?<![0-9A-Za-z_/.-])([0-9a-f]{7,40})(?![0-9A-Za-z_-])")
# the words before a token, unbackticked, that make it a commit (each form the charter writes)
ANCHORS = re.compile(
    r"(?:`main` as |`main` |pinned to |landed |site from |origin/main |main as |main at )$", re.I
)
NEVER_LANDED = "never landed"
COMPANION = re.compile(r"\bcompanion\b[^`.;|]{0,24}$", re.I)
DIGEST = re.compile(r"\b(?:sha256|inputs|digest)\s+$", re.I)
FINGERPRINT = re.compile(r"\bfingerprints?\s+$", re.I)


class Reach(Enum):
    """What a checkout says of a named commit, from the tip: three outcomes, the second split by its cause."""

    ANCESTOR = "an ancestor of the tip"
    NOT_ANCESTOR = (
        "a commit here that is not an ancestor of the tip (rewritten by a rebase, or never landed)"
    )
    NOT_A_COMMIT = "not a commit here"
    UNKNOWN = "not resolved: no git checkout to ask"


class UnresolvedError(RuntimeError):
    """No git checkout answers: a reference cannot be judged, which is neither a pass nor a refusal (P-027)."""


def _git(git: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", "-C", str(git), *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},  # never fetch from a promisor remote
        )
    except (OSError, subprocess.SubprocessError):
        return None


class Reacher:
    """Every question of reachability against one tip, answered from two git calls however many are asked: the tip's
    ancestry once (`rev-list`), and each name resolved in one batch (`cat-file --batch-check`)."""

    def __init__(self, git: Path = ROOT, tip: str = "HEAD") -> None:
        self.git, self.tip = git, tip
        self._ancestry: set[str] | None = None
        self._resolved: dict[str, str | None] = {}
        self.known = False  # whether a git checkout answered at all
        r = _git(git, "rev-parse", "--verify", "--quiet", f"{tip}^{{commit}}")
        if r is not None and r.returncode == 0:
            head = r.stdout.strip()
            listed = _git(git, "rev-list", head)
            if listed is not None and listed.returncode == 0:
                self._ancestry = set(listed.stdout.split())
                self.known = True

    def resolve(self, names: list[str]) -> None:
        """Resolve names to full commit ids in one call; a name that is no commit here resolves to None."""
        todo = [n for n in dict.fromkeys(names) if n not in self._resolved]
        if not todo or not self.known:
            return
        r = _git(
            self.git,
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
            stdin="\n".join(todo) + "\n",
        )
        if r is None or r.returncode != 0:
            raise UnresolvedError(f"git cat-file did not answer in {self.git}")
        for name, line in zip(todo, r.stdout.splitlines(), strict=True):
            parts = line.split()
            self._resolved[name] = parts[0] if len(parts) == 2 and parts[1] == "commit" else None

    def reach(self, sha: str) -> Reach:
        if not self.known:
            return Reach.UNKNOWN
        if not SHA.fullmatch(sha):
            return Reach.NOT_A_COMMIT
        self.resolve([sha])
        full = self._resolved.get(sha)
        if full is None:
            return Reach.NOT_A_COMMIT
        return Reach.ANCESTOR if full in self._ancestry else Reach.NOT_ANCESTOR


def reach(sha: str, git: Path = ROOT, tip: str = "HEAD") -> Reach:
    """One question: whether `sha` is an ancestor of `tip` in the checkout `git`."""
    return Reacher(git, tip).reach(sha)


@dataclass(frozen=True)
class Citation:
    """A commit a committed file names, where it names it."""

    file: str
    line: int
    sha: str
    what: str  # the field or the sentence's form, for the message


@dataclass(frozen=True)
class DeadReference:
    file: str
    line: int
    sha: str
    why: str
    edit: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.sha} {self.why}; {self.edit}"


EDIT_COMMIT = "a committed file names only landed commits: name the inputs by sha256, or the landed commit once it is on main"
EDIT_TOKEN = (
    "write a commit as `sha` (backticked) or after one of the anchors citations.ANCHORS names; mark a digest "
    "'sha256 <hex>', the companion repository's commit 'companion <sha>', a commit that never landed with the words "
    "never landed in its sentence"
)


def _line_of(text: str, needle: str, start: int = 1) -> int:
    for n, line in enumerate(text.splitlines(), 1):
        if n >= start and needle in line:
            return n
    return 1


# ── the scope ───────────────────────────────────────────────────────────────────────────────────────────────────────
def practice_citations(root: Path) -> list[Citation]:
    out = []
    for p in sorted((root / PRACTICE).glob("*.json")):
        text = p.read_text(encoding="utf-8")
        sha = json.loads(text).get("commit")
        if sha:
            rel = p.relative_to(root).as_posix()
            out.append(Citation(rel, _line_of(text, '"commit"'), sha, "the record's commit"))
    return out


def run_log_citations(root: Path) -> tuple[list[Citation], list[Citation]]:
    """The run log's commits that are citations, and those kept as dated history: a run from a checkout up to
    `RUN_LOG_HISTORY_THROUGH` names the worktree commit at run time, which may not be on main (the operator's ruling of
    2026-11-25), so it is counted and never refused."""
    path = root / RUN_LOG
    out: list[Citation] = []
    history: list[Citation] = []
    if not path.is_file():
        return out, history
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        sha = r.get("commit")
        if not sha:
            continue
        kept = r.get("source") == "checkout" and str(r.get("run_at")) <= RUN_LOG_HISTORY_THROUGH
        (history if kept else out).append(
            Citation(RUN_LOG, n, sha, f"the run of {r.get('run_at')}'s commit")
        )
    return out, history


def policy_citations(root: Path) -> list[Citation]:
    """Every non-null `at_commit` in the policy, wherever it stands: each method's definition, and an entry's value that
    pins a contract's definition the same way (the drift-read contract's)."""
    if not (root / POLICY).is_file():
        return []
    text = (root / POLICY).read_text(encoding="utf-8")
    out: list[Citation] = []
    after: dict[
        str, int
    ] = {}  # the line each sha was last found on, so a second pin to it names its own line

    def walk(node, where: str) -> None:
        if isinstance(node, dict):
            if node.get("at_commit"):
                sha = str(node["at_commit"])
                lines = text.splitlines()
                after[sha] = next(
                    (
                        n
                        for n in range(after.get(sha, 0) + 1, len(lines) + 1)
                        if re.search(rf"at_commit:\s*[\"']?{re.escape(sha)}\b", lines[n - 1])
                    ),
                    1,
                )
                out.append(Citation(POLICY, after[sha], sha, f"{where}'s pin"))
            for k, v in node.items():
                walk(v, f"{where}.{k}" if where else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                name = v.get("id") if isinstance(v, dict) else None
                walk(v, f"{where}[{name or i}]")

    walk(yaml.safe_load(text), "")
    return out


def pins_findings(root: Path) -> list[DeadReference]:
    """The companion's pins name their sources by sha256 and carry no commit from schema 2."""
    path = root / PINS
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    pins = json.loads(text)
    if "commit" not in pins:
        return []
    return [
        DeadReference(
            PINS,
            _line_of(text, '"commit"'),
            str(pins["commit"]),
            "is a commit in pins.json, which names its sources by sha256 from schema 2",
            "rewrite the pins: python3 docs/design/enterprise-strategy-layer/generator/pin_companion.py --write",
        )
    ]


def _sentence(line: str, at: int) -> str:
    """The sentence of a line holding position `at`: bounded by a full stop or a semicolon followed by a space, and by
    a table cell's pipe."""
    starts = [m.end() for m in re.finditer(r"[.;|]\s", line[:at])]
    start = starts[-1] if starts else 0
    m = re.search(r"[.;|]\s|[.;|]$", line[at:])
    end = at + m.start() if m else len(line)
    return line[start:end]


def charter_tokens(text: str) -> tuple[list[Citation], list[tuple[int, str]]]:
    """The charter's commit citations by context, and every hex token no rule classifies (each with its line)."""
    found: list[Citation] = []
    unclassified: list[tuple[int, str]] = []
    fenced, section = False, ""
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:  # a schema draft is an example, not a citation
            continue
        if line.startswith("## "):
            section = line.split(".", 1)[0][3:]
        status_from = (
            line.rfind("|", 0, len(line.rstrip()) - 1)
            if section == "12" and line.startswith("| REQ-")
            else -1
        )
        for m in TOKEN.finditer(line):
            tok, before = m.group(1), line[: m.start()]
            if NEVER_LANDED in _sentence(line, m.start()):
                continue  # dated history: the sentence says the commit never landed
            backticked = before.endswith("`") and line[m.end() : m.end() + 1] == "`"
            if (
                backticked
                or ANCHORS.search(before)
                or (status_from >= 0 and m.start() > status_from)
            ):
                found.append(Citation(CHARTER, n, tok, "a commit the charter names"))
            elif COMPANION.search(before) or DIGEST.search(before) or FINGERPRINT.search(before):
                continue  # the companion repository's commit, a content digest, a schema lock's fingerprint
            elif re.search(r"[a-f]", tok) and re.search(r"[0-9]", tok):
                unclassified.append((n, tok))
    return found, unclassified


def charter_citations(root: Path) -> tuple[list[Citation], list[DeadReference]]:
    if not (root / CHARTER).is_file():
        return [], []
    found, unclassified = charter_tokens((root / CHARTER).read_text(encoding="utf-8"))
    return found, [
        DeadReference(
            CHARTER,
            n,
            tok,
            "is a hex token no rule classifies as a commit or as anything else",
            EDIT_TOKEN,
        )
        for n, tok in unclassified
    ]


def dead_references(
    root: Path = ROOT, tip: str = "HEAD", git: Path | None = None
) -> tuple[list[DeadReference], dict]:
    """Every dead reference in the scope, and what was read. A file of the scope that is absent under `root` is read as
    holding nothing (a throwaway repository holds part of it; the repository's own test holds every file present).
    Raises UnresolvedError when no git checkout answers."""
    reacher = Reacher(git or root, tip)
    if not reacher.known:
        raise UnresolvedError(f"{git or root} is no git checkout with {tip}; nothing judged")
    runs, history = run_log_citations(root)
    charter, unclassified = charter_citations(root)
    cited = [*practice_citations(root), *runs, *policy_citations(root), *charter]
    reacher.resolve([c.sha for c in [*cited, *history]])
    dead = [*pins_findings(root), *unclassified]
    for c in cited:
        state = reacher.reach(c.sha)
        if state is not Reach.ANCESTOR:
            dead.append(
                DeadReference(c.file, c.line, c.sha, f"({c.what}) is {state.value}", EDIT_COMMIT)
            )
    off_main = sum(1 for c in history if reacher.reach(c.sha) is not Reach.ANCESTOR)
    return dead, {"cited": len(cited), "history": len(history), "history_off_main": off_main}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="citations.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT, help="the checkout whose files are read")
    ap.add_argument(
        "--tip", default="HEAD", help="the commit every citation must be an ancestor of"
    )
    a = ap.parse_args(argv)
    started = time.monotonic()
    try:
        dead, read = dead_references(a.root, a.tip)
    except UnresolvedError as e:
        print(f"citations: not judged: {e}")
        return 3
    for d in dead:
        print(d)
    took = time.monotonic() - started
    if dead:
        print(
            f"citations: {len(dead)} dead or unclassified of {read['cited']} commits named ({took:.1f} s)"
        )
        return 1
    print(
        f"citations: {read['cited']} commits named, each an ancestor of {a.tip}; {read['history']} run records read "
        f"as dated history, {read['history_off_main']} of them naming a worktree commit not on main ({took:.1f} s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
