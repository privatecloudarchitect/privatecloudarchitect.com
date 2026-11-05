"""The strategy check (30-GATES.md step 4; charter section 8; DEC-11).

Every structural gate, then the date gate (GATE-13), then the check's own freshness, judged on one day. The date gate
is the one gate that reads a calendar, so it runs here and nowhere else: a calendar date never fails anyone's
pre-push, and no page computes "overdue" from the day it builds.

  * **The day judged** is an argument, the run's UTC date by default, so a test pins it.
  * **Files only.** The check reads the register, the policy, the reference portfolio, the files the gates reference
    and its own run records. It reads no estate, holds no credential and makes no network call (3c's condition).
  * **Where a run is recorded.** The spool and the commit are arguments. By default the spool is
    `docs/design/enterprise-strategy-layer/runs/spool/` in the main checkout (`git rev-parse --git-common-dir`), so a run
    from a worktree lands where a run from the checkout does, and the commit is `HEAD`. The scheduled run passes both,
    because it runs in an export of `main` that has no `.git`.
  * **Its own freshness first.** It judges the newest earlier record before writing this run's.
  * **The watch reads.** A machine-readable watch source is read by the watch reader (`instrument/watch.py`, on its
    own scheduled agent, never by the check), which writes one dated record per read to a second spool beside the
    check's (`runs/watch-spool/`); a release folds them into the tracked `runs/watch.jsonl`. The check reads both,
    types each record at the boundary (a record that does not read leaves the date gate unjudged at its file and
    line), and the date gate takes the newer of a record and the entry's `last_read` (13.3) and refuses a read whose
    new candidates no trigger event or signal rules on within the entry's interval (13.8).

A strategy release folds the spool's new records into the tracked `runs/log.jsonl`, so every run is on record in git.

Run from the repository root: docs/design/enterprise-strategy-layer/generator/check.py [--day YYYY-MM-DD]
[--spool DIR] [--watch-spool DIR] [--commit SHA] [--git DIR] [--if-due] [--no-record] [--staleness] [--fold].
`--fold` appends the spool's new runs to the tracked log, and the watch spool's new reads to the tracked watch log,
which each strategy release commits. `--git` names the checkout that
resolves a method's pinned commit (GATE-14), the main checkout by default; an export passes it. `--staleness` prints the one warning line
`make verify-prepush` shows and always exits 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

LAYER = Path(__file__).resolve().parent.parent
ROOT = LAYER.parents[2]
if str(LAYER) not in sys.path:
    sys.path.insert(0, str(LAYER))

from generator import core, gates, models  # noqa: E402
from generator.gates import Finding, Result, Sources, _f  # noqa: E402
from generator.models import SCHEMA_VERSIONS, parse_day, parse_stamp  # noqa: E402
from generator.policy import Loaded, add  # noqa: E402

SPOOL = "docs/design/enterprise-strategy-layer/runs/spool"
LOG = "docs/design/enterprise-strategy-layer/runs/log.jsonl"
WATCH_SPOOL = (
    "docs/design/enterprise-strategy-layer/runs/watch-spool"  # the watch reader's records, unfolded
)
WATCH_LOG = "docs/design/enterprise-strategy-layer/runs/watch.jsonl"  # the folded reads, tracked

# What the check reads, and so what an export of `main` must hold for it: the scheduled run exports these and nothing
# else, and a test runs the check from such an export, so a read this list lacks fails there first.
READS = (
    "docs/design/enterprise-strategy-layer",
    "WORLD_CLASS_READINESS_AUDIT_4.md",  # the open registry, whose lane table lanes.yaml is held to (13.5)
    "docs/design/standup-dependency-ladder/00-CHARTER.md",
    "deploy/privatecloudarchitect/site/competency-map.yaml",
    "deploy/privatecloudarchitect/site/mastery.yaml",
    "deploy/privatecloudarchitect/site/src/pages.json",
    "deploy/privatecloudarchitect/site/src/strategy-front-door.json",  # the front door's feed, held to the render (15.4)
    "deploy/privatecloudarchitect/site/src/pages",  # a chapter's plates, which a strategy page's citation names
    "deploy/privatecloudarchitect/site/src/layout.html",
    "deploy/privatecloudarchitect/site/structure_refs.py",
    "deploy/privatecloudarchitect/site/validate_routes.py",  # what is a strategy page's copy (strategy_copy)
    "deploy/privatecloudarchitect/site/voice_lint.py",
    "deploy/privatecloudarchitect/site/figure_patterns.py",
    "deploy/privatecloudarchitect/site/figure-patterns.yaml",
    "deploy/privatecloudarchitect/site/pattern-floors.yaml",
    "deploy/privatecloudarchitect/companion/publish.py",
    "deploy/privatecloudarchitect/companion/staging/handbook/host-lifecycle",
    "deploy/privatecloudarchitect/companion/staging/handbook/platform-backup",
    "deploy/privatecloudarchitect/companion/staging/frameworks/cartography",  # inventory-of-record's drift read and instrument (step 4, batch 1)
    "deploy/privatecloudarchitect/companion/staging/handbook/service-accounts",  # non-human-identity's drift read and instruments (step 4, batch 2)
    "deploy/privatecloudarchitect/companion/staging/handbook/integrations-identity",
    "deploy/privatecloudarchitect/companion/staging/handbook/metrics-collection/harness",  # telemetry-collection's instruments (step 4, batch 3)
    "deploy/privatecloudarchitect/companion/staging/handbook/log-collection",
    "deploy/privatecloudarchitect/companion/staging/handbook/flow-collection",
    "deploy/privatecloudarchitect/companion/staging/handbook/ops-estate",  # content-from-code's drift read and instruments (step 4, batch 3)
    "deploy/privatecloudarchitect/companion/staging/handbook/alerting-doctrine",  # actionable-alerting's (step 4, batch 3)
    "deploy/privatecloudarchitect/companion/staging/handbook/log-alerts",  # threat-alerting's (step 4, batch 3)
    "deploy/privatecloudarchitect/companion/staging/handbook/incident-response",  # incident-handling's (step 4, batch 3)
    "deploy/privatecloudarchitect/companion/staging/handbook/cost-showback",  # workload-showback's (step 4, batch 3)
    "deploy/privatecloudarchitect/companion/staging/handbook/capacity-forecasting",  # capacity-headroom's (step 4, batch 3)
    "deploy/privatecloudarchitect/companion/staging/handbook/construct-model",  # tenancy-model's (step 4, batch 4)
    "deploy/privatecloudarchitect/companion/staging/handbook/isolation-design",  # tenant-isolation's (step 4, batch 4)
    "deploy/privatecloudarchitect/companion/staging/handbook/day1-provisioning",  # self-service-provisioning's (step 4, batch 4)
    "deploy/privatecloudarchitect/companion/staging/handbook/content-libraries",  # self-service-provisioning's image pins (step 4, batch 4, 1b's read)
    "deploy/privatecloudarchitect/companion/staging/handbook/hardening-audit",  # hardening-posture's (step 4, batch 4)
    "deploy/privatecloudarchitect/companion/staging/handbook/microsegmentation",  # east-west-segmentation's (step 4, batch 4)
    "deploy/privatecloudarchitect/companion/staging/handbook/platform-lifecycle",  # controlled-platform-change's (step 4, batch 4)
    "deploy/privatecloudarchitect/companion/staging/handbook/day2-pathways",  # workload-day2's (step 4, batch 4)
    "deploy/privatecloudarchitect/companion/staging/handbook/identity-lifecycle",  # access-lifecycle's (step 4, batch 5)
    "docs/design/content-libraries/evidence",  # the catalog sweep's dry run, self-service-provisioning's released-versions read (1b)
    "lab/state/images",  # the catalog sweep's dated records, the pinned copy self-service-provisioning's drift read reads (1b, step 7)
    "platform/tests/test_enterprise_strategy_generator.py",
    "platform/tests/test_enterprise_strategy_lead_time.py",
)


# An item a gate names without refusing (a watch entry with no source yet) is a finding marked listed, as every gate's
# is (gates.Finding); the name is kept for the date gate's callers.
Listed = Finding


# ── where runs are recorded ──────────────────────────────────────────────────────────────────────────────────────────
def main_checkout(cwd: Path = ROOT) -> Path | None:
    """The main checkout of the repository this code sits in, or None outside a git checkout (an export)."""
    r = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        capture_output=True,
        text=True,
    )
    return Path(r.stdout.strip()).parent if r.returncode == 0 else None


def default_spool() -> Path | None:
    top = main_checkout()
    return top / SPOOL if top else None


def default_watch_spool() -> Path | None:
    top = main_checkout()
    return top / WATCH_SPOOL if top else None


def default_commit() -> str | None:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
    )
    return r.stdout.strip() if r.returncode == 0 else None


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(gates.ROOT).as_posix()
    except ValueError:  # a spool outside the checkout is named by its own path
        return str(path)


def _record(text: str, rel: str, line: int) -> dict:
    """One run record, or a SourceError at its file and line: a record that does not parse, or names no run time."""
    try:
        r = json.loads(text)
    except ValueError as e:
        raise gates.SourceError(
            f"{rel}: {type(e).__name__}: {e}", at=(rel, line + getattr(e, "lineno", 1) - 1)
        ) from e
    try:  # a run's time, read by the one parser here, so a record that holds another is named at its line
        when = parse_stamp(r["run_at"])
    except (TypeError, KeyError, ValueError) as e:
        raise gates.SourceError(
            f"{rel}: a run record whose run_at is no UTC time ({type(e).__name__}: {e})",
            at=(rel, line),
        ) from e
    if when > datetime.now(
        UTC
    ):  # a run after this one's own clock would read as fresh until that time passed
        raise gates.SourceError(
            f"{rel}: a run record dated after now ({r['run_at']})", at=(rel, line)
        )
    return r


def records(spool: Path | None, log: Path | None = None) -> list[dict]:
    """Every run on record, the spool's and the tracked log's, oldest first; a record that cannot be read is a
    SourceError at its file and line."""
    out = []
    if spool and spool.is_dir():
        for p in sorted(spool.glob("*.json")):
            out.append(_record(gates.read_text(p, _rel(p)), _rel(p), 1))
    if log and log.exists():
        rel = _rel(log)
        for n, x in enumerate(gates.read_text(log, rel).splitlines(), 1):
            if x.strip():
                out.append(_record(x, rel, n))
    seen, unique = set(), []
    for r in sorted(out, key=lambda r: r["run_at"]):
        if r["run_at"] not in seen:
            seen.add(r["run_at"])
            unique.append(r)
    return unique


# ── the watch reader's records ──────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Read:
    """One watch read record as typed at the boundary, with the file and line it was read from, so a finding on it
    names where the record is."""

    record: dict
    at: tuple[str, int]

    @property
    def entry(self) -> str:
        return self.record["entry"]

    @property
    def day(self) -> date:
        return parse_day(self.record["day"])

    @property
    def key(self) -> tuple[str, str]:
        return self.record["entry"], self.record["read_at"]


def _watch_record(text: str, rel: str, line: int) -> Read:
    """One watch read record through its model, or a SourceError at its file and line: a record that does not parse,
    that the model refuses, or that is dated after now."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise gates.SourceError(
            f"{rel}: {type(e).__name__}: {e}", at=(rel, line + getattr(e, "lineno", 1) - 1)
        ) from e
    try:
        typed = models.WatchRead.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first["loc"]) or "the record"
        raise gates.SourceError(
            f"{rel}: a watch read record its model refuses ({where}: {first['msg']})",
            at=(rel, line),
        ) from e
    if parse_stamp(typed.read_at) > datetime.now(UTC):
        raise gates.SourceError(
            f"{rel}: a watch read record dated after now ({typed.read_at})", at=(rel, line)
        )
    return Read(typed.model_dump(by_alias=True), (rel, line))


def watch_reads(spool: Path | None, log: Path | None = None) -> list[Read]:
    """Every watch read on record, the watch spool's and the tracked watch log's, oldest first, each typed through its
    model; a record that cannot be read is a SourceError at its file and line."""
    out: list[Read] = []
    if spool and spool.is_dir():
        for p in sorted(spool.glob("*.json")):
            out.append(_watch_record(gates.read_text(p, _rel(p)), _rel(p), 1))
    if log and log.exists():
        rel = _rel(log)
        for n, x in enumerate(gates.read_text(log, rel).splitlines(), 1):
            if x.strip():
                out.append(_watch_record(x, rel, n))
    seen, unique = set(), []
    for r in sorted(out, key=lambda r: (r.record["read_at"], r.record["entry"])):
        if r.key not in seen:
            seen.add(r.key)
            unique.append(r)
    return unique


def newest_read(entry: str, reads: list[Read]) -> Read | None:
    """The newest record of a fetched read of the entry, or None: a record whose fetch failed is on record and counts
    as no read."""
    mine = [r for r in reads if r.entry == entry and r.record["fetched"]]
    return max(mine, key=lambda r: r.record["read_at"]) if mine else None


def _ruled(candidate: str, entry: str, register: dict) -> bool:
    """Whether a trigger event or a signal rules on a new candidate: an event names it in its id or its source as
    fetched, a signal of the entry names it in its id or what it found. Case is not compared: an event's id is written
    lower-case, a catalog's identifier upper."""
    c = candidate.casefold()
    for e in register.get("trigger_events") or []:
        if c in str(e.get("id", "")).casefold() or c in str(e.get("source", "")).casefold():
            return True
    for sig in register.get("signals") or []:
        if sig.get("watch") == entry and (
            c in str(sig.get("id", "")).casefold() or c in str(sig.get("what", "")).casefold()
        ):
            return True
    return False


# ── the date gate (GATE-13) ─────────────────────────────────────────────────────────────────────────────────────────
def _effective(pol: Loaded, portfolio: dict, entry_id: str):
    """An entry's value as this portfolio runs it: its override where the entry allows one, the policy's otherwise."""
    return pol.for_estate((portfolio.get("policy") or {}).get("overrides") or []).get(entry_id)


def _cycle_starts(pol: Loaded, portfolio: dict, until: date) -> list[date]:
    cycle = _effective(pol, portfolio, "cycle")
    anchor = str(cycle.get("first_start"))
    if not re.match(r"\d", anchor):
        return []  # an event, in words: the cycle is not anchored yet (it starts when PH4 exits)
    # anything that opens with a digit is read as a day, a UTC time on one included, through the one parser: a week
    # date, a slashed or bare date, a day the calendar lacks, or text after a day that is no time is refused, never read
    # as not anchored
    start = parse_day(anchor)
    out = []
    while start <= until:
        out.append(start)
        start = add(start, cycle["length"])
    return out


def gate_13(
    s: Sources, day: date, runs: list[dict], reads: list[Read] | None = None
) -> tuple[list[Finding], list[Listed]]:
    reads = reads or []
    pol = s.loaded()
    _cycle_starts(
        pol, s.portfolio.data, day
    )  # an anchor shaped as a day the calendar lacks is refused here too
    typed = s.typed()
    if pol is None or typed is None:
        return [], []
    reg, pf, _ = typed
    found, listed = [], []
    intervals = pol.get("review-intervals")

    # 13.1: an assessment past its derived review-by date with no newer assessment, on the register's initiatives and
    # an estate's own (schema 3)
    for doc, (_key, i), d in gates._inits(s):
        guidance = d.get("guidance") or []
        if not guidance:
            continue
        k = core.newest_index(guidance, day=lambda a: a.get("assessed"))
        g = guidance[k]
        review = add(parse_day(g["assessed"]), intervals[g["half_life"]])
        if day > review:
            found.append(
                _f(
                    "13.1",
                    doc,
                    (_key, i, "guidance", k),
                    f"{d.get('id')}'s guidance, assessed {g['assessed']}, was due for review by {review}",
                    "re-assess it: append a new guidance assessment with its date, evidence and confidence",
                )
            )
    latest = {
        p["initiative"]: p
        for p in core.newest_assessments(core.run_method("planning-horizon", reg, pf, pol))
    }
    for i, d in enumerate(s.portfolio.data.get("initiatives") or []):
        p = latest.get(d.get("id"))
        if p and day > parse_day(p["review_by"]):
            k = core.newest_index(d["planning"], day=lambda a: a.get("assessed"))
            found.append(
                _f(
                    "13.1",
                    s.portfolio,
                    ("initiatives", i, "planning", k),
                    f"{d.get('id')}'s planning, assessed {p['assessed']}, was due for review by {p['review_by']}",
                    "re-assess it: append a new planning assessment",
                )
            )

    # 13.2: an expired exception, or one renewed past its cap, counted as drift
    expiry = pol.get("exception-expiry")
    cycle = _effective(pol, s.portfolio.data, "cycle")
    for i, c in enumerate(s.portfolio.data.get("capabilities") or []):
        for k, x in enumerate(c.get("exceptions") or []):
            path = ("capabilities", i, "exceptions", k)
            ends = parse_day(x["granted"])
            for _ in range(expiry["expires_after_cycles"]):
                ends = add(ends, cycle["length"])
            if x.get("renewals", 0) > expiry["max_consecutive_renewals"]:
                found.append(
                    _f(
                        "13.2",
                        s.portfolio,
                        path,
                        f"{c.get('id')}'s exception {x.get('id')} is renewed {x['renewals']} times in a row, past the "
                        f"cap of {expiry['max_consecutive_renewals']}: its gap counts as drift",
                        "close the gap, or record its next step in the decision log",
                    )
                )
            elif day > ends:
                found.append(
                    _f(
                        "13.2",
                        s.portfolio,
                        path,
                        f"{c.get('id')}'s exception {x.get('id')} expired on {ends}: its gap counts as drift",
                        "renew it by a decision, or close the gap",
                    )
                )

    # 13.3: a watch entry not read within its interval, a read being the newer of its `last_read` (a read by hand)
    # and the watch reader's newest fetched record of it; one with no source yet, or optional, is listed
    entries = s.register.data.get("watch_list") or []
    for i, w in enumerate(entries):
        path = ("watch_list", i)
        hand = parse_day(str(w.get("last_read"))) if w.get("last_read") else None
        record = newest_read(w.get("id"), reads)
        last = max(
            x for x in (hand, record.day if record else None, parse_day(str(w["since"]))) if x
        )
        due = add(last, w["every"])
        if day <= due:
            continue
        what = f"the watch entry {w.get('id')} was due to be read by {due}" + (
            "" if hand or record else ", and has never been read"
        )
        if w.get("status") == "pending_source" or w.get("optional"):
            reason = (
                "it has no source yet" if w.get("status") == "pending_source" else "it is optional"
            )
            listed.append(
                _f(
                    "13.3",
                    s.register,
                    path,
                    f"{what} ({reason})",
                    "read it once it has a source, or when it is read",
                    listed=True,
                )
            )
        else:
            edit = (
                "run the watch reader (instrument/watch.py read --entry "
                f"{w.get('id')}; its scheduled agent runs it daily), or read it in session (fetched and recorded, "
                "BLOCK-010) and write its `last_read`"
                if w.get("machine_readable") is True
                else "read it in session (fetched and recorded, BLOCK-010) and write its `last_read`"
            )
            found.append(_f("13.3", s.register, path, what, edit))

    # 13.8: a watch read whose new candidates no trigger event or signal rules on within the entry's interval: what
    # the reader found new is ruled on (a trigger event, or a signal of the entry, naming it) by the day the entry is
    # next due, or the read is refused at its record
    by_id = {w.get("id"): w for w in entries}
    for r in reads:
        w = by_id.get(r.entry)
        if not r.record["fetched"] or not r.record["new"] or w is None:
            continue
        deadline = add(r.day, w["every"])
        if day <= deadline:
            continue
        unruled = [c for c in r.record["new"] if not _ruled(c, r.entry, s.register.data)]
        if unruled:
            shown = ", ".join(unruled[:5]) + (
                f" and {len(unruled) - 5} more" if len(unruled) > 5 else ""
            )
            found.append(
                _f(
                    "13.8",
                    r.at[0],
                    (),
                    f"the watch read of {r.entry} on {r.record['day']} found {len(unruled)} new "
                    f"candidate{'s' if len(unruled) != 1 else ''} ({shown}) no trigger event or signal rules on, "
                    f"and the ruling was due by {deadline}",
                    "record a trigger event (re-opened, spawned or no_change) or a signal of the entry naming each, "
                    "in the register (charter section 5.8)",
                    line=r.at[1],
                )
            )

    # 13.5: a lane lanes.yaml names apart from the open registry's lane table, listed
    listed += _lanes(s)

    # 13.9: the companion's vocabulary file held to the site files it was written from, listed (step 9)
    listed += _vocabulary(s)

    # 13.6: a job no written capability serves, listed (the handbook's jobs grow by the peers' hand; never a refusal)
    found_job = gates._foundation(s)
    served = {j for c in s.register.data.get("capabilities") or [] for j in c.get("jobs") or []}
    for j in s.comp_map.get("jobs") or []:
        if j["id"] != found_job and j["id"] not in served:
            listed.append(
                _f(
                    "13.6",
                    "deploy/privatecloudarchitect/site/competency-map.yaml",
                    (),
                    f"the job {j['id']!r} is served by no written capability",
                    "write a capability for it (40-BREADTH.md step 4), by the lane that owns its chapters",
                    line=1,
                    listed=True,
                )
            )

    # 13.7: an untaught placement of the map whose message to its lane is not on record, listed
    if s.catalog_map is not None:
        for i, p in enumerate(s.catalog_map.data.get("placements") or []):
            if p.get("place") == "untaught" and not gates._on_record(p):
                listed.append(
                    _f(
                        "13.7",
                        s.catalog_map,
                        ("placements", i),
                        f"{p.get('capability')!r} is placed untaught and its message to lane {p.get('lane')} is not on "
                        "record",
                        "send the message in step 4's batch and record it on the placement (B10)",
                        listed=True,
                    )
                )

    # 13.4: the check's own newest earlier record older than its interval
    every = _effective(pol, s.portfolio.data, "strategy-check")["every"]
    if runs:
        newest = parse_day(runs[-1]["run_at"][:10])
        if day > add(newest, every):
            log = s.root / LOG
            found.append(
                _f(
                    "13.4",
                    LOG,
                    (),
                    f"the strategy check last ran on {newest}, past its interval",
                    "find why the scheduled run stopped (the agent, the Mac asleep or off), and run the check",
                    line=max(1, len(log.read_text().splitlines())) if log.exists() else 1,
                )
            )
    return found, listed


def _vocabulary(s: Sources) -> list[Finding]:
    """13.9: the companion's vocabulary file (generator/vocabulary.py; 40-BREADTH.md step 9) held to the site files it
    was written from, each difference listed, never refused: a peer's new job or page fails no push, and the next
    strategy release rewrites the file."""
    from generator import vocabulary

    rel = vocabulary.OUT
    path = s.root / rel
    fix = "write it: python3 docs/design/enterprise-strategy-layer/generator/vocabulary.py --write"
    if not path.exists():
        return [
            _f(
                "13.9",
                rel,
                (),
                "the companion's vocabulary file is absent",
                fix,
                line=1,
                listed=True,
            )
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [
            _f(
                "13.9",
                rel,
                (),
                f"the vocabulary file does not parse ({e})",
                fix,
                line=1,
                listed=True,
            )
        ]
    out = []
    for name, source in vocabulary.SOURCES.items():
        recorded = ((data.get("written_from") or {}).get(name) or {}).get("sha256")
        current = vocabulary.sha256_of(s.root / source) if (s.root / source).exists() else None
        if recorded != current:
            out.append(
                _f(
                    "13.9",
                    rel,
                    (),
                    f"written from {source} as it stood, which has since changed",
                    fix,
                    line=1,
                    listed=True,
                )
            )
    return out


LANES = "docs/design/enterprise-strategy-layer/lanes.yaml"
LANE_ROW = re.compile(r"^\| (?P<lane>[^|]+?) \| (?P<session>[^|]+?) \|")


def registry_lanes(text: str) -> dict[str, list[str]]:
    """The open registry's lane table, read as each session's lanes: the one table headed `| lane | session |`, a row's
    session the first word of its session cell (64, 3c, f8, 1b), its lane the row's first cell as written. Any other
    table (the tool-blocked chapters, keyed by chapter) is not read."""
    out: dict[str, list[str]] = {}
    lines = text.splitlines()
    head = next((i for i, x in enumerate(lines) if re.match(r"^\| lane \| session \|", x)), None)
    if head is None:
        return out
    for line in lines[head + 2 :]:  # past the header and its rule
        m = LANE_ROW.match(line)
        if not m:
            break  # the table ends at its first line that is not a row
        who = re.match(r"\s*([0-9a-z]+)", m["session"])
        if who:
            out.setdefault(who.group(1), []).append(m["lane"].strip())
    return out


def _lanes(s: Sources) -> list[Finding]:
    """13.5: each lane of lanes.yaml held to the open registry's lane table, its id a session the table names and its
    parts the lanes the table gives that session, each difference listed, never refused."""
    path = s.root / LANES
    if not path.exists():
        return []
    doc = gates.Doc.read(LANES, s.root)
    lanes = models.Lanes.model_validate(doc.data)
    registry = s.root / lanes.registry
    if not registry.exists():
        return [
            _f(
                "13.5",
                doc,
                ("registry",),
                f"the registry {lanes.registry} is not in this checkout",
                "name the open registry",
                listed=True,
            )
        ]
    table = registry_lanes(registry.read_text(encoding="utf-8"))
    out = []
    for i, lane in enumerate(lanes.lanes):
        held = table.get(lane.id)
        if held is None or sorted(held) != sorted(lane.parts):
            out.append(
                _f(
                    "13.5",
                    doc,
                    ("lanes", i, "parts"),
                    f"the lane {lane.id} names the parts {lane.parts}, and the registry's lane table gives it "
                    f"{held or 'no row'}",
                    "make the two agree, in the change that moves a lane",
                    listed=True,
                )
            )
    return out


def due(pol: Loaded, portfolio: dict, day: date, runs: list[dict]) -> bool:
    """Whether a scheduled run is due on this day: none recorded, the newest older than the interval, or a cycle started
    since the newest."""
    if not runs:
        return True
    entry = _effective(pol, portfolio, "strategy-check")
    newest = parse_day(runs[-1]["run_at"][:10])
    if day >= add(newest, entry["every"]):
        return True
    return bool(entry.get("at_cycle_start")) and any(
        newest < c <= day for c in _cycle_starts(pol, portfolio, day)
    )


# ── one run ─────────────────────────────────────────────────────────────────────────────────────────────────────────
DateResult = Result  # the date gate's result carries its listed items as every gate's does


def _date_gate(
    s: Sources, day: date, earlier: list[dict], reads: list[Read] | None = None
) -> DateResult:
    """GATE-13's result: not covered when the models do not load or a date cannot be read, never passed (P-027)."""
    if s.typed() is None:  # the date gate judges derived dates, which need the models
        return DateResult(
            "GATE-13",
            "not_covered",
            [],
            s.why_untyped(),
            gates._untyped_at(s),
            listed=[],
        )
    try:
        found, listed = gate_13(s, day, earlier, reads)
    except Exception as e:  # a date the gate cannot read is said, and the run is still recorded
        return DateResult(
            "GATE-13", "not_covered", [], f"{type(e).__name__}: {e}", gates._where(e), listed=[]
        )
    return DateResult("GATE-13", "refused" if found else "passed", found, None, listed=listed)


def run(
    s: Sources,
    day: date,
    spool: Path | None,
    commit: str | None,
    record: bool = True,
    log: Path | None = None,
    watch_spool: Path | None = None,
    watch_log: Path | None = None,
) -> tuple[list[Result], list[Listed], dict]:
    results = gates.run(s)
    earlier = reads = None
    try:
        earlier = records(spool, log or s.root / LOG)
    except (
        gates.SourceError
    ) as e:  # a run record that cannot be read leaves the date gate unjudged, said at its line
        unread = DateResult(
            "GATE-13", "not_covered", [], f"a run record could not be read: {e}", e.at, listed=[]
        )
    if earlier is not None:
        try:
            reads = watch_reads(watch_spool, watch_log or s.root / WATCH_LOG)
        except gates.SourceError as e:  # the same for the watch reader's records
            unread = DateResult(
                "GATE-13",
                "not_covered",
                [],
                f"a watch read record could not be read: {e}",
                e.at,
                listed=[],
            )
    results.append(gates.scrubbed(unread if reads is None else _date_gate(s, day, earlier, reads)))
    listed = [x for r in results for x in r.listed]  # every gate's, kept apart from what is due
    pol = s.loaded()
    rec = {
        "run_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "day": day.isoformat(),
        "commit": commit,
        "source": "checkout"
        if main_checkout(s.root)
        else "export",  # the scheduled run judges an export of main
        "policy_version": pol.model.policy_version if pol else None,
        "schemas": {k: SCHEMA_VERSIONS[k] for k in ("register", "portfolio", "policy")},
        "gates": [
            {"gate": r.gate, "state": r.state, "findings": [str(f) for f in r.findings]}
            for r in results
        ],
        "listed": [str(x) for x in listed],
        # every finding, and every gate that could not judge, is something due
        "due_items": sum(len(r.findings) for r in results)
        + sum(r.state == "not_covered" for r in results),
    }
    if record and spool is not None:
        spool.mkdir(parents=True, exist_ok=True)
        (spool / f"{rec['run_at'].replace(':', '').replace('-', '')}.json").write_text(
            json.dumps(rec, indent=1) + "\n"
        )
    return results, listed, rec


def fold(spool: Path | None, log: Path) -> int:
    """Append to the tracked log each spooled run it does not hold yet, oldest first: how a strategy release puts every
    run on record in git. Returns how many it added; the spool is left as it is."""
    held = {r["run_at"] for r in records(None, log)}
    new = [r for r in records(spool) if r["run_at"] not in held]
    if new:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r, sort_keys=True) + "\n")
    return len(new)


def fold_watch(spool: Path | None, log: Path) -> int:
    """Append to the tracked watch log each spooled watch read it does not hold yet, oldest first, each typed on the
    way (a record the model refuses folds nothing and is named at its line). Returns how many it added; the spool is
    left as it is."""
    held = {r.key for r in watch_reads(None, log)}
    new = [r for r in watch_reads(spool) if r.key not in held]
    if new:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r.record, sort_keys=True, ensure_ascii=False) + "\n")
    return len(new)


def staleness(spool: Path | None, log: Path, day: date, pol: Loaded, portfolio: dict) -> str | None:
    """The one warning line `make verify-prepush` shows, or None when the newest run is in time and found nothing due."""
    runs = records(spool, log)
    if not runs:
        return "strategy check: no run recorded; run make strategy-check, and install the scheduled agent if it is not (D4-15)"
    newest = runs[-1]
    entry = _effective(pol, portfolio, "strategy-check")
    last = parse_day(newest["run_at"][:10])
    late = day > add(last, entry["every"])
    started = [
        c
        for c in _cycle_starts(pol, portfolio, day)
        if entry.get("at_cycle_start") and last < c <= day
    ]  # the same comparison `due` makes
    n = newest.get("due_items", 0)
    if not late and not started and not n:
        return None
    parts = [f"strategy check: last run {newest['run_at'][:10]}"]
    if late:
        parts.append("past its interval")
    if started:
        parts.append(f"a cycle started on {started[-1]} since")
    if n:
        parts.append(f"it found {n} due item{'s' if n != 1 else ''}")
    return ", ".join(parts) + "; run make strategy-check"


def _record_unjudged(a, spool: Path | None, why: str) -> None:
    """A run that could not judge is still on record, every gate not covered, so the warning counts it as due."""
    if a.no_record or spool is None:
        return
    gates_ = [*gates.STRUCTURAL, "GATE-13"]
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = {
        "run_at": at,
        "day": a.day.isoformat(),
        "commit": a.commit,
        "source": "unread",
        "gates": [{"gate": g, "state": "not_covered", "findings": [], "why": why} for g in gates_],
        "listed": [],
        "due_items": len(gates_),
    }
    spool.mkdir(parents=True, exist_ok=True)
    (spool / f"{at.replace(':', '').replace('-', '')}.json").write_text(
        json.dumps(rec, indent=1) + "\n"
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="the strategy check")
    ap.add_argument("--day", type=parse_day, default=datetime.now(UTC).date())
    ap.add_argument("--spool", type=Path, default=None)
    ap.add_argument(
        "--watch-spool", type=Path, default=None, help="the watch reader's unfolded records"
    )
    ap.add_argument("--commit", default=None)
    ap.add_argument(
        "--git", type=Path, default=None, help="the checkout that resolves pinned commits"
    )
    ap.add_argument("--if-due", action="store_true")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--staleness", action="store_true")
    ap.add_argument(
        "--fold",
        action="store_true",
        help="fold the spool's new runs, and the watch spool's new reads, into the tracked logs",
    )
    a = ap.parse_args(argv)
    spool = a.spool or default_spool()
    watch_spool = a.watch_spool or default_watch_spool()
    if (
        a.fold
    ):  # a release step on the run records alone: it reads no source and records no run of its own
        try:
            print(f"strategy check: {fold(spool, gates.ROOT / LOG)} run(s) folded into {LOG}")
        except (
            gates.SourceError
        ) as e:  # a record it cannot read is named in the one form; nothing is folded
            print(
                gates.scrub(
                    e.failure(
                        "nothing folded: a run record could not be read",
                        "fix the record and fold again",
                    )
                )
            )
            return 1
        try:
            print(
                f"strategy check: {fold_watch(watch_spool, gates.ROOT / WATCH_LOG)} watch read(s) folded into "
                f"{WATCH_LOG}"
            )
        except gates.SourceError as e:
            print(
                gates.scrub(
                    e.failure(
                        "nothing folded: a watch read record could not be read",
                        "fix the record and fold again",
                    )
                )
            )
            return 1
        return 0
    try:
        s = Sources.read()
    except gates.SourceError as e:
        if a.staleness:  # a warning, never a failure
            print(
                f"strategy check: a source could not be read ({gates.scrub(str(e))}); run make strategy-check"
            )
            return 0
        why = f"a source could not be read: {gates.scrub(str(e))}"
        print(gates.scrub(e.failure()))  # its one form: the file and line, the rule and the edit
        _record_unjudged(a, spool, why)
        return 1
    s.git = a.git or main_checkout()
    pol = s.loaded()
    if a.staleness:
        # a warning, never a failure: a record that cannot be read is said, and the pre-push goes on
        try:
            line = staleness(spool, s.root / LOG, a.day, pol, s.portfolio.data) if pol else None
        except Exception as e:  # a warning, never a failure, whatever a record holds
            line = (
                f"strategy check: its run records or its dates could not be read ({type(e).__name__}: "
                f"{gates.scrub(str(e))[:120]}); "
                "run make strategy-check"
            )
        if line:
            print(line)
        return 0
    if a.if_due and pol is not None:
        try:  # a date it cannot read (a cycle anchor the calendar lacks) is said and recorded, never a traceback
            is_due = due(pol, s.portfolio.data, a.day, records(spool, s.root / LOG))
        except (
            gates.SourceError
        ):  # a run record it cannot read: the run is due, and judging names the record
            is_due = True
        except Exception as e:
            why = f"the date gate could not judge: {type(e).__name__}: {gates.scrub(str(e))}"
            file, line = gates._where(e)  # a record it cannot read was caught above as due
            print(
                gates.one_line(f"{file}:{line}: GATE-13 not covered: {why}; {gates.UNJUDGED_EDIT}")
            )
            _record_unjudged(a, spool, why)
            return 1
        if not is_due:
            print("strategy check: not due")
            return 0
    started = datetime.now(UTC)
    results, listed, rec = run(
        s,
        a.day,
        spool,
        a.commit or default_commit(),
        record=not a.no_record,
        watch_spool=watch_spool,
    )
    took = (datetime.now(UTC) - started).total_seconds()
    for r in results:  # each gate's state, then each of its failures in its one form
        print(f"{r.gate}: {r.state}")
        for line in r.failures():
            print(f"  {gates.scrub(line)}")
    for x in listed:
        print(f"  {gates.scrub(str(x))}")
    print(f"strategy check: {rec['due_items']} due, judged {rec['day']}, in {took:.1f} s")
    return 1 if any(r.state in ("refused", "not_covered") for r in results) else 0  # P-027


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
