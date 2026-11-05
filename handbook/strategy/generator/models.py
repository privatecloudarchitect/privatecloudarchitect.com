"""Typed models of the enterprise strategy layer's files (charter 00-CHARTER.md section 5.12; 20-PILOT.md step 2).

The register (the domain's definitions), a portfolio (one estate's plan), the policy (the method's parameters) and one
line of the drift-read contract each load through a model here, so a file that drifts from its schema fails at the
boundary (P-007), never deep inside a computation. The models forbid fields they do not name: a misspelt or new field
is a schema change, which takes a new schema version and a migration (section 5.12), and the structural fingerprint of
each model is pinned in `schema.lock.yaml` beside this file, so a model edited without a new version fails its test.

Values that are free-form by design stay open: a policy entry's `value`, a method's `parameters`, and the portfolio's
per-step ledgers keyed by the register's step ids.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

SCHEMA_VERSIONS = {
    "register": 7,  # 7: a typed door link's words; 6: the front door's readers (DEC-06; 50-FRONT-DOOR.md section 9)
    "portfolio": 5,
    "policy": 2,
    "drift_read": 1,
    "series": 1,
    "advisory": 1,
    "lines": 1,
    "lead_time": 1,
    "outside_model": 1,
    "lanes": 1,
    "pins": 1,
    "catalog_map": 2,
    "practice": 1,  # instrument/practice.py's record (40-BREADTH.md step 4, batch 1)
    "watch_read": 1,  # instrument/watch.py's record of one read of a watch entry's source (charter section 5.8)
    "driver_stresses_draft": 1,  # drafts/driver-stresses.yaml, DEC-19's draft, read by no gate (40-BREADTH.md step 5)
    "front_door": 2,  # 2: a link's words and the brief's label; 1: the feed the home renderer reads (DEC-06)
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ── policy.yaml ─────────────────────────────────────────────────────────────────────────────────────────────────────
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
STAMP = re.compile(
    r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?)Z"
)  # a platform's milliseconds kept


def a_day(value: str | None, what: str, time: bool = False) -> None:
    """A calendar day, written YYYY-MM-DD (or, where `time`, a UTC time on it): never a week date, which the standard
    library's `date.fromisoformat` accepts and which sorts as text among days, and never a day the calendar lacks."""
    if value is None:
        return
    stamp = STAMP.fullmatch(value) if time else None
    if DAY.fullmatch(value) or stamp:
        try:
            # the ten characters are digits and dashes by the match; the calendar refuses a day it lacks
            date(int(value[:4]), int(value[5:7]), int(value[8:10]))
            if stamp:
                form = (
                    "%H:%M:%S.%f" if stamp.group(4) else "%H:%M:%S" if stamp.group(3) else "%H:%M"
                )
                datetime.strptime(stamp.group(2), form)
            return
        except ValueError:
            pass
    raise ValueError(
        f"{what} {value!r} is not a calendar day (YYYY-MM-DD{', or YYYY-MM-DDTHH:MM:SSZ' if time else ''})"
    )


RUN_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def parse_stamp(value: str) -> datetime:
    """The one way the layer reads a run's time: a UTC time to the second, by a_day's rule and written
    YYYY-MM-DDTHH:MM:SSZ, fixed width, so run records sort by it as text."""
    a_day(value, "a UTC time", time=True)
    if not RUN_STAMP.fullmatch(value):
        raise ValueError(f"a UTC time {value!r} is not written YYYY-MM-DDTHH:MM:SSZ")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def parse_day(value: str) -> date:
    """The one way the layer reads a day: by a_day's rule, then as a date (a stamp's day is its first ten characters)."""
    a_day(value, "a day", time=True)
    return date.fromisoformat(value[:10])


def _day(value: str) -> str:
    a_day(value, "a day")
    return value


def _stamp(value: str) -> str:
    a_day(value, "a day", time=True)
    return value


Day = Annotated[
    str, AfterValidator(_day)
]  # a calendar day; its JSON schema is a string's, so no fingerprint moves
Stamp = Annotated[str, AfterValidator(_stamp)]  # a calendar day, or a UTC time on one


class Vocabulary(Strict):
    members: list[str]
    fields: list[str]


class HistoryItem(Strict):
    value: Any
    since: int
    until_version: int
    ended: Day


class PolicyEntry(Strict):
    id: str
    value: Any
    decided_by: list[str]
    since: int
    effective_from: Day
    overridable: bool
    change: str
    read_by: list[str]
    depends_on: list[str] = []
    one_way: str | None = None
    basis: str | None = None
    ends_when: str | None = None
    history: list[HistoryItem]


class Definition(Strict):
    text: str
    at_commit: str | None


class Level(Strict):
    id: str
    ordinal: int


class Golden(Strict):
    """A method version's golden fixture (schema 2; GATE-14): what it holds, and the test that holds it, as
    `path::name` from the repository root."""

    holds: str
    test: str | None


class Method(Strict):
    id: str
    version: int
    status: str
    decided_by: list[str]
    since: int
    definition: Definition
    parameters: dict[str, Any] = {}
    reads_entries: list[str] = []
    levels: list[Level] | None = None
    golden: Golden


class Provenance(Strict):
    fields: dict[str, str]


class Policy(Strict):
    schema_: int = Field(alias="schema")
    policy_version: int
    effective_from: Day
    shapes: dict[str, dict[str, str]]
    vocabularies: dict[str, Vocabulary]
    entries: list[PolicyEntry]
    methods: list[Method]
    provenance: Provenance


# ── the value each entry the code reads holds ───────────────────────────────────────────────────────────────────────
# The loader holds each such entry's value, and each override of it, to the shape its readers read, so a value of the
# wrong shape is refused where it is loaded, naming the entry and the file, never met later as a bare TypeError. An
# entry no code reads (a record of a ratified choice) declares no shape, so a record changes with no code edit.
class _Value(Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)


# an ISO 8601 date duration, as the policy writes every interval; the one pattern the loader's arithmetic reads too
DURATION = re.compile(
    r"\AP(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?\Z"
)  # \Z: no trailing newline passes


def _duration(value: str) -> str:
    if not DURATION.match(value) or value == "P":
        raise ValueError(f"{value!r} is not an ISO 8601 date duration (PnYnMnWnD)")
    return value


Duration = Annotated[str, AfterValidator(_duration)]


class KeyedBy:
    """A mapping keyed by a vocabulary's members, every member once: adding a member is a data change, so the loader
    reads the members from the policy, never from here."""

    def __init__(self, vocabulary: str, value: Any) -> None:
        self.vocabulary, self.value = vocabulary, value


class CycleValue(_Value):
    length: Duration
    first_start: str  # a day, or the event the first cycle starts at


class ExceptionExpiryValue(_Value):
    expires_after_cycles: int
    max_consecutive_renewals: int
    after_cap: str


class StrategyCheckValue(_Value):
    every: Duration
    at_cycle_start: bool


class TierValue(_Value):
    id: str
    label: str
    from_: Duration = Field(alias="from")
    to: Duration | None


class MethodSelectionValue(_Value):
    method: str
    version: int


class EstimateAdjustmentValue(_Value):
    required: bool
    applies_to: list[str]
    factor: str


class CapacityValue(_Value):
    per: str
    period: Duration
    chain_funding: str
    beyond_the_line: str


class AboveWorldClassValue(_Value):
    level: str
    when: str


class WorldClassBarValue(_Value):
    world_class_level: str
    above_world_class: AboveWorldClassValue
    role_grade: str
    show_distribution: bool
    rank_departments: bool
    illustrative_evidence: str


class DriftContractValue(_Value):
    contract: str
    version: int
    definition: Definition


def _strategy_path(value: str) -> str:
    if not re.fullmatch(r"/strategy(/[a-z0-9]+(?:-[a-z0-9]+)*)*", value):
        raise ValueError(
            f"{value!r} is not a strategy page's path (/strategy, or /strategy/ and a lower-case id)"
        )
    return value


StrategyPath = Annotated[
    str, AfterValidator(_strategy_path)
]  # a path the site serves a strategy page at


class PublicationValue(_Value):
    public: list[str]
    private: list[str]


class CompletenessValue(_Value):
    outside_model: str
    adaptation: str
    cross_checks: list[str]


ENTRY_VALUES: dict[str, Any] = {
    "cycle": CycleValue,
    "review-intervals": KeyedBy("half_life_tiers", Duration),
    "exception-expiry": ExceptionExpiryValue,
    "strategy-check": StrategyCheckValue,
    "planning-tiers": list[TierValue],
    "planning-horizon": MethodSelectionValue,
    "prioritization": MethodSelectionValue,
    "estimate-adjustment": EstimateAdjustmentValue,
    "capacity": CapacityValue,
    "measure-methods": dict[
        str, MethodSelectionValue
    ],  # keyed by the measure each selection serves
    "adoption-method": MethodSelectionValue,
    "world-class-bar": WorldClassBarValue,
    "drift-contract": DriftContractValue,
    "publication": PublicationValue,
    "strategy-pages": list[StrategyPath],
    "instrument-gaps": Literal[
        "carry", "wait"
    ],  # DEC-21: carry a capability no lane can yet measure, or hold it unwritten
    "completeness": CompletenessValue,  # the outside model and the cross-checks the catalog's map is held to (GATE-2)
}


def entry_value_problem(entry_id: str, value: Any, members=None) -> str | None:
    """Why a value is not of the shape its entry's readers read (the first field refused, and why), or None; an entry
    that declares no shape is a record, and any value is its own. `members` reads a vocabulary's members (the loader's
    own), for a mapping keyed by one."""
    shape = ENTRY_VALUES.get(entry_id)
    if shape is None:
        return None
    if isinstance(shape, KeyedBy):
        if not isinstance(value, dict):
            return "Input should be a valid dictionary"
        if members is not None and set(value) != set(members(shape.vocabulary)):
            return (
                f"its keys are {sorted(value)}, and the {shape.vocabulary} vocabulary lists "
                f"{sorted(members(shape.vocabulary))}"
            )
        shape = dict[str, shape.value]
    try:
        TypeAdapter(shape).validate_python(value, strict=True)
    except ValidationError as e:
        err = e.errors()[0]
        where = ".".join(str(x) for x in err["loc"])
        return f"{where + ': ' if where else ''}{err['msg']}"
    return None


# ── register.yaml ───────────────────────────────────────────────────────────────────────────────────────────────────
class Role(Strict):
    id: str
    name: str
    owns: str | None = None


class RelatesTo(Strict):
    route: str
    promise: str
    how: Literal["derived", "linked", "divergent"]
    reason: str | None = None


class Declaration(Strict):
    system: str
    object: str
    writer: str
    system_name: str | None = (
        None  # schema 3: the system's name as a page says it; absent, its id in words
    )


class DriftRead(Strict):
    """Where a capability's drift is read: a companion and its check, or, before any companion reads it, `not_covered`
    and the reason (schema 3; charter section 5.6, P-027)."""

    companion: str | None = None
    check: str | None = None
    not_covered: str | None = None

    @model_validator(mode="after")
    def _one_form(self) -> DriftRead:
        read = bool(self.companion) and bool(self.check)
        if read == bool((self.not_covered or "").strip()) or (
            not read and (self.companion or self.check)
        ):
            raise ValueError(
                "a drift read names a companion and its check, or says not_covered and why; one form, never both"
            )
        return self


class AgentEntry(Strict):
    stack: Literal["operating", "product"]
    layer: str
    acts: str


class Message(Strict):
    """The message that sent an untaught territory to a lane, and the lane's answer (schema 3; B10): pending while it has
    no answer, its date always recorded, the answer's date set exactly when the answer is."""

    sent: Day
    answer: str | None = None
    answered: Day | None = None

    @model_validator(mode="after")
    def _answered_with_its_date(self) -> Message:
        if (self.answer is None) != (self.answered is None):
            raise ValueError(
                "a message's answer and the day it was answered are written together, or neither"
            )
        return self


class Untaught(Strict):
    """A capability's territory no chapter teaches yet, the lane it was sent to and the message on record (schema 3)."""

    territory: str
    lane: str
    message: Message


class HandOff(Strict):
    """Where one part of a capability is taught (a chapter), served (a note, a companion) or not taught yet."""

    kind: Literal["taught", "served", "untaught"]
    pages: list[str] = []
    what: str
    category: str | None = None  # an untaught part's category, a candidate for a lane
    lane: str | None = None  # schema 3: the lane an untaught part was sent to
    message: Message | None = None  # schema 3: the message that sent it, and the lane's answer

    @model_validator(mode="after")
    def _untaught_names_its_category(self) -> HandOff:
        """An untaught part is recorded with its category (charter section 5.5), the name a page gives it, never the
        part's own text in its place; a lane and a message belong to an untaught part only."""
        if self.kind == "untaught" and not (self.category or "").strip():
            raise ValueError("an untaught hand-off names its category (charter section 5.5)")
        if self.kind != "untaught" and (self.lane is not None or self.message is not None):
            raise ValueError("only an untaught hand-off names a lane and a message")
        return self


class EstablishStep(Strict):
    id: str
    step: str
    requires: list[str]
    proven_by: str
    investment_unit: str
    handoff: list[HandOff] | None = None


class SustainLoop(Strict):
    id: str
    loop: str
    runner: str
    cadence: str
    trigger: list[str]
    toil: str
    toil_reason: str
    carried_by: str | None
    effort_unit: str
    handoff: list[HandOff] | None = None


class InstrumentGap(Strict):
    """A value whose instrument, the record or companion that would read it, no lane has built yet (schema 3; DEC-21):
    the reason, and the lane that would build it. Not `not_recorded`, which is a figure no record holds."""

    not_covered: str
    lane: str


class Value(Strict):
    id: str
    serves: str
    category: str
    outcome: str
    measure: str
    measure_note: str | None = None
    unit: str
    stages: list[str]
    paired_with: str | None
    instrument: str | InstrumentGap
    direction: Literal["lower", "higher"]
    target_owner: str


class Capability(Strict):
    """A capability (charter section 5.1). Schema 4 (40-BREADTH.md step 4, the first practice batch): `practice` keys
    the layer's own practice to the outside model's capability it implements, by the name the outside model and the
    catalog's map write (DEC-18; GATE-2's clause 2.1 is met by the key, 2.14 requires its hand-off, 2.16 holds it to
    the map); an untaught entry is typed only (schema 2's plain text left with schema 3, as section 5.12's contraction
    says); the retired-value tombstone of schema 3 left with it, having resolved for its one schema version."""

    id: str
    name: str | None = None  # schema 3: the name a page says it by; absent, its id in words
    practice: str | None = (
        None  # schema 4: the outside model's capability this one implements (DEC-18)
    )
    object_in_focus: str
    parent: str | None
    outcome: str
    scope: str
    accountable: str
    jobs: list[str]
    taught_by: list[str]
    links: list[str]
    untaught: list[Untaught]
    relates_to: list[RelatesTo]
    declarations: list[Declaration]
    drift_read: DriftRead
    agent_entries: list[AgentEntry]
    establish: list[EstablishStep]
    sustain: list[SustainLoop]
    value: list[Value]
    # a practice capability names no job (charter section 5.5): GATE-2's clause 2.17 holds it at its line, so the
    # model stays open and the refusal keeps the one form every gate failure has


class Citation(Strict):
    """An external source an assessment rests on, as it was read (schema 2; GATE-6, BLOCK-010): where, the day it was
    fetched, the source's own version or date, and what it said. A reference within the repository stays a string."""

    cite: str
    fetched: Day | None
    version: str | None
    quote: str | None = None


class Ref(Strict):
    """Evidence within the repository, or the assessment's own reasoning, written as text (schema 3); never an external
    source, which is a citation (GATE-6 refuses a URL here)."""

    ref: str


Evidence = Citation | Ref


class Guidance(Strict):
    half_life: str
    evolution_stage: str | None
    stance: str | None
    assessed: Day
    review_by: str
    confidence: str
    evidence: list[Evidence]

    @model_validator(mode="after")
    def _review_by_is_derived(self) -> Guidance:
        """A review-by day is derived from the assessed day and the half-life, never typed (charter section 5.7)."""
        if self.review_by != "derived":
            raise ValueError(f"a guidance's review_by is derived, never typed: {self.review_by!r}")
        return self


class Initiative(Strict):
    id: str
    name: str | None = None  # schema 3
    summary: str
    establishes: list[str]
    improves: list[str]
    requires: list[str]
    sponsor: str
    from_: str = Field(alias="from")
    from_event: str | None
    from_scan: str | None = None  # schema 3: the proactive scan an initiative came from
    cost_of_delay_through: str | None
    guidance: list[Guidance]


class Stress(Strict):
    capability: str
    basis: str
    inferred: bool


class Driver(Strict):
    id: str
    status: str
    decided_by: list[str]
    change: str
    effective_from: Day
    kinds: list[str] | None = None
    stresses: list[Stress]
    stresses_planned: list[str] = []
    trigger_when: str


class DraftDriver(Strict):
    """One driver of DEC-19's draft: its stresses onto written capabilities and the planned capabilities it will stress
    once a batch writes them (40-BREADTH.md step 5)."""

    id: str
    stresses: list[Stress]
    stresses_planned: list[str] = []


class DriverStressesDraft(Strict):
    """The drivers' stresses onto the capabilities PH4 wrote, drafted for the operator's ruling (DEC-19 through D4-16;
    schema `driver_stresses_draft` 1). Read by no gate; a test holds that every driver id is a register driver and every
    stress names a written capability, planned ids under `stresses_planned`. The register's drivers change only on the
    ruling."""

    schema_: int = Field(alias="schema")
    drafted: Day
    decision: str
    drivers: list[DraftDriver]

    @model_validator(mode="after")
    def _each_driver_once(self) -> DriverStressesDraft:
        listed_once([("the draft's drivers", self.drivers, _id)])
        return self


class WatchEntry(Strict):
    id: str
    name: str | None = None  # schema 3
    source: str | None
    kind: str
    reader: str
    every: str
    machine_readable: bool | Literal["partly"]
    last_read: Day | None
    decided_by: list[str]
    since: Day
    status: str | None = None
    note: str | None = None
    optional: bool | None = None
    every_scope: str | None = None
    also_on: str | None = None


class TriggerEvent(Strict):
    id: str
    date: Day
    read_at: Stamp
    source: str
    kind: str
    driver: str | None = None
    grade: str
    reopened: list[str]  # initiative ids whose guidance the event re-opened
    spawned: list[str]
    no_change: bool
    ruled_at: Day | None = (
        None  # schema 4: the day its outcome was recorded (the re-assessment, the spawned initiative's first plan, or  # the no-change ruling); None while the outcome's day is unrecorded, which the practice's instrument names
    )


class Signal(Strict):
    """A change a watch reading found (schema 3; charter section 5.8): when it was read, where, the watch entry that
    found it, what changed and its grade."""

    id: str
    read_at: Stamp
    source: str
    watch: str | None = None
    what: str
    grade: str


class ScanArea(Strict):
    area: str
    found: list[str]  # the signals the scan found in this area; empty means none found
    searched: list[
        str
    ] = []  # schema 5: the searches made, so "none found" says where it looked (research/r4 5(c))


class Scan(Strict):
    """One proactive cycle's scan, area by area (schema 3; charter section 5.8); its `searched` and `note` since schema 5
    (40-BREADTH.md step 5): a scan run outside any cycle says so."""

    id: str
    date: Day
    areas: list[ScanArea]
    note: str | None = None


def listed_once(lists: list[tuple[str, list, Any]]) -> None:
    """Each item of a list named once by its key. Two items under one key are two records of one thing: a reader that
    takes the first and one that takes the last would disagree, and nothing would say so (G-855). An item with no key
    (a free-form entry without an id) is not compared."""
    for where, items, key in lists:
        seen: set = set()
        for x in items:
            k = key(x)
            if k is None:
                continue
            if k in seen:
                raise ValueError(f"{where} lists {k!r} twice; each is listed once")
            seen.add(k)


def _id(x: Any) -> Any:
    return x.get("id") if isinstance(x, dict) else getattr(x, "id", None)


# ── the front door (schema 6; DEC-06, 50-FRONT-DOOR.md section 9) ───────────────────────────────────────────────────
ROLES_DOOR = "roles"  # a door derived from the roles: one brief per role, and the chapters that teach its loops
_ANCHOR = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # the site's slug form for a heading anchor
PROMISE_WORDS = 16  # the design brief's rule: one sentence of at most sixteen words
# the brief's voice rules a model can hold: no number, typed or in words (a count on the door is computed beside the
# links, so a typed one goes stale); no em or en dash; no "we" (the reader's estate, never ours)
_NUMBER_WORDS = re.compile(  # a cardinal said in words; a hyphenated compound ("one-way") is a word, not a count
    r"(?<![\w-])(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"million|dozen)(?![\w-])",
    re.I,
)


def _door_voice(field: str, text: str) -> None:
    if re.search(r"\d", text) or _NUMBER_WORDS.search(text):
        raise ValueError(
            f"the door's {field} carries a number; a count is computed beside the door's links"
        )
    if re.search("[–—]", text):
        raise ValueError(f"the door's {field} carries an em or en dash")
    if re.search(r"\b[Ww]e\b|\b[Oo]ur\b", text):
        raise ValueError(
            f"the door's {field} says we or our; it is written for the reader's estate"
        )


def _site_path(path: str, where: str) -> str:
    """A path the site serves, with an optional anchor in the site's slug form; the gate holds the path to the site's
    manifest and the anchor to the page's body at the site's build (GATE-15)."""
    base, _, anchor = path.partition("#")
    if not base.startswith("/") or " " in base or "//" in base:
        raise ValueError(f"{where}: {path!r} is not a site path")
    if anchor and not _ANCHOR.fullmatch(anchor):
        raise ValueError(f"{where}: the anchor of {path!r} is not in the site's slug form")
    return path


class Link(Strict):
    """A typed door's link with its own words (schema 7): a destination whose heading would mislead out of its page
    (an anchor's heading reads without its page's subject), said in one line held by the promise's voice rules."""

    path: str
    words: str

    @model_validator(mode="after")
    def _one_line_in_voice(self) -> Link:
        if not self.words.strip() or "\n" in self.words:
            raise ValueError("a link's words are one line of text")
        _door_voice("link's words", self.words)
        return self


def link_path(entry: str | Link) -> str:
    return entry if isinstance(entry, str) else entry.path


class Door(Strict):
    """What a reader's door on the landing page carries, in both layers (50-FRONT-DOOR.md section 8): the typed
    title and promise (one line each), the strategy views it opens and the handbook pages it pairs with, each a path
    or a path with its own words. A door written as `roles` in both layers is derived: one brief per role, and the
    chapters that teach the role's loops; a derived door carries no typed words."""

    title: str
    promise: str
    strategy: list[str | Link] | str  # paths the policy publishes, or `roles`
    handbook: list[str | Link] | str  # paths the site serves (an anchor allowed), or `roles`

    @model_validator(mode="after")
    def _paths_or_roles(self) -> Door:
        for layer in ("strategy", "handbook"):
            v = getattr(self, layer)
            if isinstance(v, str) and v != ROLES_DOOR:
                raise ValueError(f"the door's {layer} is {v!r}; a list of paths, or {ROLES_DOOR!r}")
        if (self.strategy == ROLES_DOOR) != (self.handbook == ROLES_DOOR):
            raise ValueError(f"a door derived from the roles is {ROLES_DOOR!r} in both layers")
        if isinstance(self.strategy, list):
            if not self.strategy:
                raise ValueError("the door opens no strategy view")
            for p in map(link_path, self.strategy):
                if not p.startswith("/strategy"):
                    raise ValueError(f"the door's strategy path {p!r} is not a strategy view")
        if isinstance(self.handbook, list):
            if not self.handbook:
                raise ValueError("the door pairs with no handbook page")
            for p in map(link_path, self.handbook):
                _site_path(p, "the door's handbook side")
                if p.startswith("/strategy"):
                    raise ValueError(f"the door's handbook path {p!r} is a strategy view")
        for field in ("title", "promise"):
            text = getattr(self, field)
            if not text.strip() or "\n" in text:
                raise ValueError(f"the door's {field} is one line of text")
            _door_voice(field, text)
        if len(self.promise.split()) > PROMISE_WORDS:
            raise ValueError(f"the door's promise runs past {PROMISE_WORDS} words")
        return self


class Reader(Strict):
    """One of the three readers the layer serves (charter section 6), with the door the landing page shows them."""

    id: str
    name: str
    question: str
    door: Door


# the feed the generator emits for the home renderer (render.front_door): the doors as data, lists never counts
class FrontDoorRole(Strict):
    id: str
    name: str
    brief: str  # the role's public brief, a strategy page the policy publishes
    chapters: list[
        str
    ]  # the published chapters that teach the capabilities the brief shows as the role's work


class FrontDoorLink(Strict):
    path: str
    words: str


class FrontDoorDoor(Strict):
    title: str
    promise: str
    strategy: list[str | FrontDoorLink] | None = None
    handbook: list[str | FrontDoorLink] | None = None
    roles: list[FrontDoorRole] | None = (
        None  # the door derived from the roles, in place of typed paths
    )

    @model_validator(mode="after")
    def _typed_or_derived(self) -> FrontDoorDoor:
        typed = self.strategy is not None and self.handbook is not None
        if typed == (self.roles is not None):
            raise ValueError(
                "a feed's door carries its strategy and handbook paths, or its roles, never both"
            )
        return self


class FrontDoorReader(Strict):
    id: str
    name: str
    question: str
    door: FrontDoorDoor


class FrontDoorProvenance(Strict):
    policy_version: int
    schemas: dict[str, int]
    input_digest: str


class FrontDoor(Strict):
    """The front door's feed (schema `front_door`): the readers in the register's order, the words the page prints
    that the generator owns, and the provenance every served output carries. Read by the home renderer, which refuses
    a feed it cannot type, a schema it does not know and a policy version the site's strategy pages do not carry."""

    schema_: int = Field(alias="schema")
    readers: list[FrontDoorReader]
    labels: dict[str, str]
    provenance: FrontDoorProvenance


class Register(Strict):
    schema_: int = Field(alias="schema")
    fixed: Day
    roles: list[Role]
    planned_capabilities: list[str]
    capabilities: list[Capability]
    initiatives: list[Initiative]
    drivers: list[Driver]
    watch_list: list[WatchEntry]
    signals: list[Signal]
    scans: list[Scan]
    trigger_events: list[TriggerEvent]
    readers: list[
        Reader
    ] = []  # schema 6: the front door's readers, in the order the landing page shows them

    @model_validator(mode="after")
    def _each_listed_once(self) -> Register:
        listed_once(
            [
                ("the register's readers", self.readers, _id),
                ("the register's roles", self.roles, _id),
                ("the register's planned capabilities", self.planned_capabilities, lambda x: x),
                ("the register's capabilities", self.capabilities, _id),
                ("the register's initiatives", self.initiatives, _id),
                ("the register's drivers", self.drivers, _id),
                ("the register's watch list", self.watch_list, _id),
                ("the register's signals", self.signals, _id),
                ("the register's scans", self.scans, _id),
                ("the register's trigger events", self.trigger_events, _id),
            ]
            + [
                (f"the capability {c.id}'s {part}", getattr(c, part), _id)
                for c in self.capabilities
                for part in ("establish", "sustain", "value")
            ]
            # a value id names one value in the whole register: a rate, a target or an unconverted measure names a
            # value by its id alone (schema 3)
            + [
                (
                    "the register's value ids",
                    [v.id for c in self.capabilities for v in c.value],
                    lambda x: x,
                )
            ]
        )
        return self


def resolve_value(register: Register, value_id: str) -> Value:
    """The live value an id names (charter section 5.12, stable identifiers). Schema 3 also followed a retired id to
    its successor once; the tombstone left with schema 4, so an id the register does not hold is refused, and a file
    that still writes a retired id is migrated through `migrate.RENAMED` (the register) or corrected (a portfolio)."""
    live = {v.id: v for c in register.capabilities for v in c.value}
    if value_id in live:
        return live[value_id]
    raise ValueError(
        f"{value_id!r} names no value in the register; name a value a capability holds"
    )


# ── portfolio (portfolio.example.yaml, and an adopter's own) ───────────────────────────────────────────────────────
class Sourced(Strict):
    """A figure or decision with its kind (charter section 5.9)."""

    kind: str
    source: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _not_recorded_holds_no_value(self) -> Sourced:
        """A figure no record holds has no value to compute with, so it is never read as zero (DEC-14)."""
        if self.kind == "not_recorded":
            held = [
                f
                for f in ("value", "delta", "rate", "factor")
                if getattr(self, f, None) is not None
            ]
            if held:
                raise ValueError(f"a figure whose kind is not_recorded holds no {', '.join(held)}")
        return self


class Figure(Sourced):
    value: float | int | None = None

    @model_validator(mode="after")
    def _a_recorded_figure_holds_its_value(self) -> Figure:
        """A figure of any kind but not_recorded holds its value: one without would read "not recorded" on a page and
        drop who supplied it (DEC-14)."""
        if self.kind != "not_recorded" and self.value is None:
            raise ValueError(
                f"a figure whose kind is {self.kind} holds no value; record its value, or its kind as not_recorded"
            )
        return self


class Override(Strict):
    entry: str
    value: Any
    effective_from: Day
    decided_by: str
    kind: str


class PolicyRef(Strict):
    version: int
    overrides: list[Override]

    @model_validator(mode="after")
    def _one_override_per_entry(self) -> PolicyRef:
        """An entry overridden twice has two values and two decisions, and no reader can tell which the estate runs."""
        seen: set[str] = set()
        for o in self.overrides:
            if o.entry in seen:
                raise ValueError(
                    f"the entry {o.entry} is overridden twice; an estate overrides an entry once, with the decision "
                    "that set it"
                )
            seen.add(o.entry)
        return self


class Approval(Strict):
    kind: str
    status: str
    source: str | None = (
        None  # schema 3: who supplied it, so an adopter's own can be an input (GATE-7, 7.5)
    )


class ApprovedNode(Strict):
    """One node an approval covers, as the ask carried it (40-BREADTH.md step 2): its address from the portfolio's root,
    its form at the approval's schema version (every field but `note`, no child that carries its own kind), and the
    digest the ask showed. Never rewritten: a later schema carries it forward in memory to compare (served.py)."""

    path: list[str]
    node: Any
    digest: str


class NodeApproval(Strict):
    """A typed approval of the reference portfolio's nodes (schema 3): the day, the ruling quoted in charter section 1.1
    that made it, who gave it, the schema version its nodes are written in, the committed ask it was recorded from, and
    each node it covers."""

    date: Day
    decision: str
    source: str
    schema_: int = Field(alias="schema")
    ask: str | None = None
    nodes: list[ApprovedNode]


class Department(Sourced):
    id: str


class Assignment(Sourced):
    role: str
    scope: str
    department: str
    basis: str | None = None


class RoleHolder(Strict):
    id: str  # schema 3: the key an approval addresses it by
    role: str
    scope: str
    holder: str
    from_: Day | None = Field(alias="from")
    to: Day | None
    kind: str
    source: str | None = (
        None  # schema 3: who supplied it, so an input names its supplier (GATE-7, 7.5)
    )
    note: str | None = None


class Capacity(Sourced):
    role: str
    value: float
    unit: str


class StepState(Strict):
    done: bool
    kind: str
    read_at: Stamp | None = None
    source: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _done_is_recorded(self) -> StepState:
        """A step counts as done only on a record that says how it is known (charter section 5.5, level one)."""
        if self.done and self.kind == "not_recorded":
            raise ValueError("a done step is recorded: its kind cannot be not_recorded")
        return self


class CapabilityState(Strict):
    scope: str
    established: bool
    steps: dict[str, StepState]


class Reading(Strict):
    id: str  # schema 3: the key an approval addresses it by
    value: str
    advisory: str | None = None
    kind: str
    read_at: Stamp
    source: str
    reading: str
    confidence: str


class Target(Sourced):
    target_kind: str
    value: float | int
    window: str
    allowance: str | None
    consequence: str | None


class TargetGrade(Sourced):
    level: str
    reason: str


class Waiver(Sourced):
    """An exception: a part of a capability excused from drift for a time, by a decision (schema 2; charter section
    5.6). Its expiry is derived from policy.yaml's `exception-expiry`, never typed, and `renewals` counts the renewals
    in a row, which the same entry caps (GATE-13)."""

    id: str
    part: str
    reason: str
    decided_by: str
    granted: Day
    renewals: int = 0


class Parameter(Sourced):
    """A figure a declaration leaves to the estate (schema 5; 40-BREADTH.md step 5): the audit-trail minimum a hardening
    declaration names, say. The register's declaration states what the parameter means; the portfolio states the estate's
    value, with its unit and the kind of the decision that set it (DEC-14). A parameter no record holds (the served
    projection stubs an unapproved one `not_recorded`) carries neither value nor unit; any other kind carries both."""

    value: float | int | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def _a_recorded_parameter_holds_its_value_and_unit(self) -> Parameter:
        if self.kind != "not_recorded" and (self.value is None or not (self.unit or "").strip()):
            raise ValueError(f"a parameter whose kind is {self.kind} holds its value and its unit")
        if self.kind == "not_recorded" and (self.value is not None or self.unit is not None):
            raise ValueError("a parameter no record holds holds no value and no unit")
        return self


class PortfolioCapability(Strict):
    id: str
    grade: Literal["derived"]
    target_grade: TargetGrade
    state: list[CapabilityState]
    readings: list[Reading]
    investment: dict[str, Figure]
    effort: dict[str, Figure]
    targets: dict[str, Target]
    exceptions: list[Waiver]
    parameters: dict[
        str, Parameter
    ] = {}  # schema 5: the figures the capability's declarations leave to the estate


class ConversionRate(Sourced):
    measure: str
    rate: float
    low: float
    high: float
    unit: str
    method: str

    @field_validator("unit")
    @classmethod
    def _a_rate_states_its_unit(cls, unit: str) -> str:
        """A rate is read in its unit, which every page that shows the rate names, so a blank unit is no unit."""
        if not unit.strip():
            raise ValueError("a conversion rate states no unit")
        return unit


class EstimateAdjustment(Sourced):
    factor: float
    applies_to: list[str]
    method: str


class Status(Sourced):
    value: str


class Applicability(Sourced):
    decision: str
    reason: str


class Baseline(Sourced):
    value: float | None = None


class CostOfDelay(Sourced):
    delta: float
    baseline: Baseline
    after: Baseline | None = None
    profile: str
    deadline: Day | None


class Duration(Sourced):
    value: float
    unit: str


class EffortChange(Strict):
    loop: str
    value: float


class AddedEffort(Sourced):
    loops: list[str] = []
    change: EffortChange | None = None


class PlanningAssessment(Sourced):
    id: str  # schema 3: the key an approval addresses it by
    full_value_in: str
    first_value_in: str
    tier: Literal["derived"]
    first_value_tier: Literal["derived"]
    assessed: Day
    review_by: Literal["derived"]
    confidence: str
    evidence: list[Evidence]


class PortfolioInitiative(Strict):
    id: str
    status: Status
    commitment: str | None
    rank: Literal["derived"]
    applicability: Applicability | None = None
    cost_of_delay: CostOfDelay | None
    duration: Duration
    added_effort: AddedEffort
    planning: list[PlanningAssessment]


class DecisionEntry(Sourced):
    id: str  # schema 3: the key an approval addresses it by
    date: Day
    initiative: str | None = None
    decision: str
    by: str
    reason: str


class Unconverted(Sourced):
    """A measure shown beside the rank and never weighted into it, with the kind of that decision (schema 3)."""

    measure: str


def _measure(x: Any) -> Any:
    return x if isinstance(x, str) else getattr(x, "measure", None)


class Portfolio(Strict):
    schema_: int = Field(alias="schema")
    estate: str
    policy: PolicyRef
    approval: Approval
    approvals: list[
        NodeApproval
    ] = []  # schema 3: typed approvals beside the file-level one, which is still read
    departments: list[Department]
    assignments: list[Assignment]
    role_history: list[RoleHolder]
    ownership: dict[str, Any]
    capacity: list[Capacity]
    capabilities: list[PortfolioCapability]
    conversion_rates: list[ConversionRate]
    unconverted: list[
        Unconverted
    ]  # schema 3 typed an item and still read the plain id; schema 4 reads the typed form only
    estimate_adjustment: EstimateAdjustment
    initiatives: list[PortfolioInitiative]
    local_capabilities: list[Capability]  # schema 3: the register's model for an estate's own
    local_initiatives: list[Initiative]
    drivers: list[Driver]
    trigger_events: list[TriggerEvent]
    scans: list[Scan] = []
    decision_log: list[DecisionEntry]

    @model_validator(mode="after")
    def _each_listed_once(self) -> Portfolio:
        listed_once(
            [
                ("the portfolio's departments", self.departments, _id),
                ("the portfolio's assignments", self.assignments, lambda a: (a.role, a.scope)),
                ("the portfolio's capacity", self.capacity, lambda c: c.role),
                ("the portfolio's capabilities", self.capabilities, _id),
                ("the portfolio's conversion rates", self.conversion_rates, lambda r: r.measure),
                ("the portfolio's unconverted measures", self.unconverted, _measure),
                ("the portfolio's role history", self.role_history, _id),
                ("the portfolio's decision log", self.decision_log, _id),
                ("the portfolio's scans", self.scans, _id),
                ("the portfolio's initiatives", self.initiatives, _id),
                # an estate's own capability or initiative never shares an id with one the portfolio plans
                (
                    "the portfolio's capabilities",
                    [*self.capabilities, *self.local_capabilities],
                    _id,
                ),
                ("the portfolio's initiatives", [*self.initiatives, *self.local_initiatives], _id),
                ("the portfolio's drivers", self.drivers, _id),
                ("the portfolio's trigger events", self.trigger_events, _id),
            ]
            + [
                (f"the capability {c.id}'s states", c.state, lambda st: st.scope)
                for c in self.capabilities
            ]
            + [(f"the capability {c.id}'s readings", c.readings, _id) for c in self.capabilities]
            + [(f"the initiative {i.id}'s planning", i.planning, _id) for i in self.initiatives]
        )
        return self


# ── one line of the drift-read contract (charter section 5.6) ─────────────────────────────────────────────────────────
class DeclarationRef(Strict):
    system: str
    object: str
    writer: str
    store: str | None
    declared_version: str | None


class DriftItem(Strict):
    declared: Any
    actual: Any
    resolution: str


class DriftSource(Strict):
    companion: str
    check: str
    record: str
    exit: int | None
    replay: bool


class DriftLine(Strict):
    capability: str
    declaration: DeclarationRef
    scope: str
    mode: str
    contract_version: int
    result: str
    items_declared: int
    items_drifted: int
    items: list[DriftItem]
    read_at: Stamp
    checked_at: Stamp | None
    source: DriftSource


# ── one reading of the dated series (20-PILOT.md step 3) ─────────────────────────────────────────────────────────────
class HostRow(Strict):
    key: str | None
    joinable: bool
    cluster: str | None
    version: str | None
    build: str | None
    connection_state: str | None
    in_maintenance: bool | None


class HostCount(Strict):
    cluster: str
    version: str | None
    build: str | None
    count: int


class StoredCompliance(Strict):
    status: str | None
    compliant: int | None
    non_compliant: int | None
    incompatible: int | None
    unavailable: int | None
    scan_time: str | None


class LastRemediation(Strict):
    state: Literal["stored", "unavailable", "failed", "not_recorded"]
    read_at: str | None = None
    status: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    end_time_from: str | None = None
    failed: int | None = None
    skipped: int | None = None
    successful: int | None = None
    commit: str | None = None
    notifications: dict[str, int] = {}
    error_type: str | None = None
    message: str | None = None
    why: str | None = None


class SeriesCluster(Strict):
    label: str
    declared_base_image: str | None
    stored_compliance: StoredCompliance | None
    last_remediation: LastRemediation


class DepotImage(Strict):
    version: str
    release_date: str | None


class SeriesDepot(Strict):
    versions: list[DepotImage] | None
    versions_why: str | None = None
    read_at: str | None


class SeriesVcenter(Strict):
    label: str
    read: bool
    why: str | None = None
    read_at: str | None
    connection_recorded: bool
    unread: int | None
    unidentified: int | None
    collisions: int | None
    hosts: list[HostRow]
    host_counts: list[HostCount]
    clusters: list[SeriesCluster]
    depot: SeriesDepot


class SeriesProvenance(Strict):
    instrument: str
    instrument_sha: str
    reader: str
    reader_sha: str | None
    policy_version: int
    series_schema: int
    input_digest: str
    generated_at: str


class SeriesReading(Strict):
    series_schema: int
    kind: Literal["imported", "keyed", "failed"]
    read_at: str
    source: str
    key_fingerprint: str | None
    vcenters_named: int
    vcenters_read: int
    failure: str | None
    vcenters: list[SeriesVcenter]
    provenance: SeriesProvenance


# ── the instrument's inputs and output (20-PILOT.md step 4) ─────────────────────────────────────────────────────────
class AdvisoryDates(Strict):
    initial_publication_date: str
    issue_date: str
    updated_on: str | None = None


class ChangeLogEntry(Strict):
    date: str
    revision: str
    text: str


class AdvisoryRecord(Strict):
    schema_: int = Field(alias="schema")
    id: str
    revision: str
    source: str
    fetched: str
    page_sha256: str
    dates: AdvisoryDates
    change_log: list[ChangeLogEntry]
    notes: dict[str, str]
    columns: list[str]
    rows: list[list[str]]


class LineMapping(Strict):
    prefix: str
    line: str
    grade: str
    basis: str


class LineMap(Strict):
    schema_: int = Field(alias="schema")
    product: str
    lines: list[LineMapping]


class Bound(Strict):
    upper: int
    lower: int | None
    lower_why: str | None


class Span(Strict):
    min: int
    max: int


class ReleaseDate(Strict):
    line: str
    image: str
    release_date: str
    days_before_t0: int
    from_reading: str


class MethodStamp(Strict):
    version: int
    status: str


class MeasureProvenance(Strict):
    methods: dict[str, MethodStamp]
    policy_version: int
    input_digest: str
    generated_at: str


class LeadTime(Strict):
    advisory: str
    revision: str
    t0: str
    product: str
    lines: dict[str, dict[str, Any]]
    line_mapping: list[dict[str, str]]
    readings: list[str]
    state: Literal["open", "closed"]
    grade: str | None
    closing_reading: str | None = None
    total_days: Bound | None
    stages: dict[str, Span] | None
    release_dates: list[ReleaseDate]
    provenance: MeasureProvenance


# ── the outside model's named capabilities (research/outside-model.yaml; 40-BREADTH.md steps 1 and 2) ───────────────
class OutsideSource(Strict):
    """A source step 1 read: the outside model, a cross-check, the product-stack read DEC-08 asks for, or the context a
    chapter cites; its own version or date as the page states it, and the day it was fetched (BLOCK-010)."""

    id: str
    name: str
    role: str
    version: str
    fetched: Day


class OutsideCapability(Strict):
    """One capability a source names, as it names it, with step 1's proposal for its place (step 3 places it)."""

    source: str
    perspective: str
    identifier: str | None = None
    name: str
    definition: str
    url: str
    proposed_class: Literal["a", "b", "c", "d"]
    proposed_key: str | None
    proposed_competency: str | None = None
    maps_to_caf: list[str] | None = None
    open_question: str | None = None
    note: str | None = None
    source_note: str | None = None


class OutsideModel(Strict):
    schema_: int = Field(alias="schema")
    written: Day
    model: (
        str  # the id of the source that is the outside model; the others are cross-checks and reads
    )
    classes: dict[str, str]
    dash_rule: str
    sources: list[OutsideSource]
    capabilities: list[OutsideCapability]

    @model_validator(mode="after")
    def _each_listed_once_and_sourced(self) -> OutsideModel:
        listed_once(
            [
                ("the outside model's sources", self.sources, _id),
                (
                    "the outside model's capabilities",
                    self.capabilities,
                    lambda c: (c.source, c.name),
                ),
            ]
        )
        known = {s.id for s in self.sources}
        unknown = sorted({c.source for c in self.capabilities} - known)
        if unknown or self.model not in known:
            raise ValueError(
                f"a capability or the model names a source the file does not list: {unknown or [self.model]}"
            )
        if set(self.classes) != {"a", "b", "c", "d"}:
            raise ValueError("the classes are a, b, c and d, each with its meaning")
        return self


# ── the lanes (lanes.yaml; 40-BREADTH.md steps 2 and 3) ────────────────────────────────────────────────────────────
class Lane(Strict):
    """A lane of the open sprint registry: its id (the session's short name), the session that holds it, its parts as
    the registry's lane table names them, and the site pages it owns, as each lane confirmed them."""

    id: str
    session: str
    aliases: list[
        str
    ] = []  # other names the lane signs with (a judge's `judged_by`), so a join by name finds it
    parts: list[str]
    pages: list[str]


class Lanes(Strict):
    schema_: int = Field(alias="schema")
    registry: str  # the open registry the lanes are read from, a path from the repository root
    lanes: list[Lane]

    @model_validator(mode="after")
    def _each_page_one_lane(self) -> Lanes:
        listed_once(
            [
                ("the lanes", self.lanes, _id),
                ("the lanes' pages", [p for ln in self.lanes for p in ln.pages], lambda x: x),
            ]
        )
        return self


# ── the pinned drift records (records/pinned/pins.yaml; 40-BREADTH.md step 2) ────────────────────────────────────────
class Pin(Strict):
    """A companion record the views read, copied byte for byte so a lane's refresh of its record fails no push; a
    strategy release refreshes the copy and this line together."""

    file: str  # the copy, a path from the repository root
    source: str  # the companion's record it copies, a path from the repository root
    sha256: str
    pinned: Day


class Pins(Strict):
    schema_: int = Field(alias="schema")
    pins: list[Pin]

    @model_validator(mode="after")
    def _each_pinned_once(self) -> Pins:
        listed_once(
            [
                ("the pins' copies", self.pins, lambda p: p.file),
                ("the pins' sources", self.pins, lambda p: p.source),
            ]
        )
        return self


# ── the catalog's map (catalog-map.yaml; its placements land in 40-BREADTH.md step 3) ───────────────────────────────
class Placement(Strict):
    """Where one capability the outside model names is placed, once: in the register (its capability id, written or
    planned), untaught (the lane it is sent to), or out of scope (the reason, within `product-stack-scope`). A planned
    placement carries the first job and competency the lead proposes for it until step 4 writes it; the layer's own
    practice names its lane and no job (DEC-18)."""

    capability: str  # the outside model's capability, by its name as the source names it
    place: Literal["register", "untaught", "out_of_scope"]
    register_id: str | None = None  # the register capability, written or planned, that covers it
    lane: str | None = (
        None  # the lane that writes or teaches it: the practice's 64, an untaught territory's lane
    )
    reason: str | None = (
        None  # why it is placed as it is: required out of scope, said for every placement
    )
    territory: str | None = (
        None  # schema 2: an untaught placement's territory, the name a page gives it
    )
    message: Message | None = (
        None  # schema 2: the message that sent an untaught territory to its lane (B10)
    )
    proposed_job: str | None = None
    proposed_competency: str | None = None

    @model_validator(mode="after")
    def _each_place_names_what_it_needs(self) -> Placement:
        need = {
            "register": ("register_id",),
            "untaught": ("lane", "territory"),
            "out_of_scope": ("reason",),
        }[self.place]
        missing = [k for k in need if not (getattr(self, k) or "").strip()]
        if missing:
            raise ValueError(f"a placement {self.place} names its {', '.join(missing)}")
        if self.place == "out_of_scope" and (
            self.register_id or self.proposed_job or self.proposed_competency
        ):
            raise ValueError("a placement out of scope names no register id, job or competency")
        return self


class CrossCheckMapping(Strict):
    """A cross-check's named capability mapped to the outside model's capabilities that cover it, or the reason none
    does."""

    source: str
    name: str
    maps_to: list[str]
    reason: str | None = None

    @model_validator(mode="after")
    def _mapped_or_reasoned(self) -> CrossCheckMapping:
        if not self.maps_to and not (self.reason or "").strip():
            raise ValueError(f"{self.source}'s {self.name} is mapped to nothing and says no reason")
        return self


class CatalogMap(Strict):
    schema_: int = Field(alias="schema")
    model: str
    placements: list[Placement]
    mappings: list[CrossCheckMapping]

    @model_validator(mode="after")
    def _each_placed_once(self) -> CatalogMap:
        listed_once(
            [
                ("the map's placements", self.placements, lambda p: p.capability),
                ("the map's mappings", self.mappings, lambda m: (m.source, m.name)),
            ]
        )
        return self


class PracticeMeasure(Strict):
    """One measure of the layer's own practice as `instrument/practice.py` reads it (40-BREADTH.md step 4): measured,
    with its value, unit, basis and the items it was counted over, or not recorded with the reason, holding no value
    (P-027)."""

    kind: Literal["measured", "not_recorded"]
    value: float | int | None = None
    unit: str | None = None
    basis: str | None = None
    items: list[Any] | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _one_form(self) -> PracticeMeasure:
        if self.kind == "measured" and (
            self.value is None or not self.unit or not self.basis or self.items is None
        ):
            raise ValueError("a measured practice measure carries its value, unit, basis and items")
        if self.kind == "not_recorded" and (
            self.value is not None or not (self.reason or "").strip()
        ):
            raise ValueError("a practice measure not recorded holds no value and says why")
        return self


class PracticeRecord(Strict):
    """One dated reading of the practice's measures (schema 1): the day it was read as of, the run's stamp, the
    commit, the schemas and the policy version, and each measure by its id."""

    schema_: int = Field(alias="schema")
    read_at: Stamp
    day: Day
    commit: str | None
    tree: (
        Literal["clean", "modified"] | None
    )  # the layer's files as the commit holds them, or with edits
    schemas: dict[str, int]
    policy_version: int
    measures: dict[str, PracticeMeasure]


class WatchFetch(Strict):
    """One request the watch reader made: the URL as fetched (the final one, after a same-host redirect), the status,
    the body's size and its digest, so the record names what was read without holding it."""

    url: str = Field(max_length=2000)
    status: int | None  # None when no response came
    bytes: int | None
    sha256: str | None = Field(default=None, max_length=64)


class WatchRead(Strict):
    """One read of a watch entry's machine-readable source by the watch reader (`instrument/watch.py`; charter section
    5.8): a dated record of the source as fetched, with the source's own version and date, what the entry's filter
    selected, and what is new since the previous read; never a judgment. A record whose `fetched` is false (the fetch
    failed) is on record and counts as no read. The date gate takes the newer of a record and the entry's `last_read`
    (13.3), and refuses a read whose new candidates no trigger event or signal rules on within the entry's interval
    (13.8). The record is written to a spool the check reads and a release folds into `runs/watch.jsonl`."""

    schema_: int = Field(alias="schema")
    entry: str = Field(max_length=80)  # the watch entry's id
    reader: str = Field(max_length=80)  # the reader and its version, `cisa-kev@1`
    read_at: Stamp  # the read's UTC time, YYYY-MM-DDTHH:MM:SSZ
    day: Day  # the read's UTC day, what the date gate compares
    fetched: bool
    fetches: list[WatchFetch] = Field(max_length=64)
    source_version: str | None = Field(max_length=400)  # the source's own version, as written
    source_date: str | None = Field(max_length=120)  # the source's own date, as written
    count: int | None  # rows, commits, releases or pages the read saw
    candidates: list[Annotated[str, Field(max_length=200)]] = Field(
        max_length=4000
    )  # what the entry's filter selects
    new: list[Annotated[str, Field(max_length=200)]] = Field(
        max_length=4000
    )  # candidates the previous read did not hold
    dated: dict[str, Annotated[str, Field(max_length=120)]] = Field(
        default_factory=dict
    )  # each candidate's own date in the source, as written
    previous: str | None = Field(
        max_length=120
    )  # what `new` is against: the previous record's read_at, or the entry's day
    previous_basis: Literal["record", "last_read", "since", "repository"] | None
    error: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)  # the filter, in words

    @model_validator(mode="after")
    def _consistent(self) -> WatchRead:
        if self.read_at[:10] != self.day:
            raise ValueError(f"a watch read's day {self.day} is not its read_at's ({self.read_at})")
        if not self.fetched and (self.candidates or self.new):
            raise ValueError("a watch read that fetched nothing selects nothing")
        if self.fetched and self.error:
            raise ValueError("a watch read that fetched carries no error")
        if not self.fetched and not self.error:
            raise ValueError("a watch read that fetched nothing says why")
        if set(self.new) - set(self.candidates):
            raise ValueError("every new item of a watch read is one of its candidates")
        return self


MODELS: dict[str, type[BaseModel]] = {
    "register": Register,
    "portfolio": Portfolio,
    "policy": Policy,
    "drift_read": DriftLine,
    "series": SeriesReading,
    "advisory": AdvisoryRecord,
    "lines": LineMap,
    "lead_time": LeadTime,
    "outside_model": OutsideModel,
    "lanes": Lanes,
    "pins": Pins,
    "catalog_map": CatalogMap,
    "practice": PracticeRecord,
    "front_door": FrontDoor,
    "watch_read": WatchRead,
    "driver_stresses_draft": DriverStressesDraft,
}


_FINGERPRINTS: dict[
    type[BaseModel], str
] = {}  # a class's schema does not change while it is loaded


def fingerprint(model: type[BaseModel]) -> str:
    """The structural fingerprint of a model: its JSON schema, canonical, hashed. A field added, removed, renamed or
    retyped changes it; a docstring does not. Computed once per model class: the schema lock is read in every gate run
    and every check."""

    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in ("description", "title")}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o

    if model not in _FINGERPRINTS:
        schema = strip(model.model_json_schema(by_alias=True))
        _FINGERPRINTS[model] = hashlib.sha256(
            json.dumps(schema, sort_keys=True).encode()
        ).hexdigest()[:16]
    return _FINGERPRINTS[model]
