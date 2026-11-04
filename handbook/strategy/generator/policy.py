"""The policy loader: the one way the strategy layer's code reads a ratified choice (charter section 5.12, GATE-14).

Every value the generator, the gates, the instrument or the adopter's companion needs comes through `Loaded.get(id)`,
which refuses an id `policy.yaml` does not hold, so a misspelt or retired choice fails where it is asked for, never
silently. The loader also checks the file against itself (unique ids, every reader and change class from its own
vocabularies, every dependency and every method selection resolving) and checks the register and a portfolio against
the vocabularies, walking the fields each vocabulary names.
"""

from __future__ import annotations

import calendar
import copy
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from .models import (
    DURATION,
    Method,
    Policy,
    PolicyEntry,
    Portfolio,
    Register,
    entry_value_problem,
)

HERE = Path(__file__).resolve().parent.parent
POLICY_PATH = HERE / "policy.yaml"
REGISTER_PATH = HERE / "register.yaml"
PORTFOLIO_PATH = HERE / "portfolio.example.yaml"


class UnknownEntryError(KeyError):
    """An id policy.yaml does not hold."""


class PolicyError(ValueError):
    """policy.yaml, or a file checked against it, breaks one of its own rules."""


# the C scanner where PyYAML was built with libyaml (the same grammar, the same marks, several times the pace: the
# structural gates compose the register once per run to name a finding's line, and at the catalog's full size the
# pure-Python scanner was the largest single cost under the processor-time ceiling; step 4, batch 2), else the Python one
_BASE_LOADER = yaml.CSafeLoader if yaml.__with_libyaml__ else yaml.SafeLoader


class DataLoader(_BASE_LOADER):
    """How the layer reads its three data files (the register, a portfolio, the policy). A day stays the text it is
    written as, quoted or not, so the models type it and one parser reads it (`models.parse_day`); a key written twice in
    one mapping is refused, never the last one kept in silence (G-856)."""

    def construct_mapping(self, node, deep=False):
        seen: dict[Any, int] = {}
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            line = key_node.start_mark.line + 1
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None,
                    None,
                    f"the key {key!r} is written twice in one mapping (lines {seen[key]} and {line}); a reader "
                    "would keep only the last",
                    key_node.start_mark,
                )
            seen[key] = line
        return super().construct_mapping(node, deep=deep)


# no implicit timestamps: an unquoted 2026-10-25 is read as the text it is, never as a date object no model types
DataLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in _BASE_LOADER.yaml_implicit_resolvers.items()
}


def load_data(text: str) -> Any:
    """A data file's text as the layer reads it (`DataLoader`)."""
    return yaml.load(text, Loader=DataLoader)  # a SafeLoader subclass: no arbitrary objects


def read_yaml(path: Path) -> Any:
    return load_data(path.read_text(encoding="utf-8"))


class Loaded:
    """A validated policy, read by id."""

    def __init__(self, model: Policy) -> None:
        self.model = model
        self.entries: dict[str, PolicyEntry] = {}
        for e in model.entries:
            if e.id in self.entries:
                raise PolicyError(f"policy.yaml holds the entry {e.id!r} twice")
            self.entries[e.id] = e
        self.overrides: dict[str, Any] = {}  # an estate's, applied by for_estate
        self.methods: dict[tuple[str, int], Method] = {}
        for m in model.methods:
            if (m.id, m.version) in self.methods:
                raise PolicyError(
                    f"policy.yaml registers the method {m.id} version {m.version} twice"
                )
            self.methods[(m.id, m.version)] = m
        self._check_self()

    # reading
    def get(self, entry_id: str) -> Any:
        """An entry's value as this view reads it: an estate's override where for_estate applied one."""
        if entry_id in self.overrides:
            return self.overrides[entry_id]
        return self.entry(entry_id).value

    def for_estate(self, overrides: list) -> Loaded:
        """This policy as an estate runs it: each override of an entry marked overridable, never one-way, read in
        place of the policy's value (charter section 5.12), so every reader reads one view and none applies its own."""
        view = copy.copy(self)
        view.overrides = {}
        for o in overrides or []:
            if not isinstance(o, dict) and not hasattr(o, "entry"):
                raise ValueError(
                    f"an override is an entry, its value and the decision that set it, never {o!r}"
                )
            entry_id = o.get("entry") if isinstance(o, dict) else o.entry
            value = o.get("value") if isinstance(o, dict) else o.value
            e = self.entries.get(entry_id)
            if e is not None and e.overridable and not e.one_way:
                # an override is read by the entry's readers, so it holds the entry's shape
                why = entry_value_problem(entry_id, value, self.vocabulary)
                if why:
                    raise ValueError(
                        f"the override of {entry_id} is not of the shape its readers read ({why})"
                    )
                # a selection an override makes is one the policy registers, as the file's own must be
                for method, version in selections(value):
                    if (method, version) not in self.methods:
                        raise ValueError(
                            f"the override of {entry_id} selects {method} version {version}, which no method "
                            "registers"
                        )
                # two values and two decisions: no reader can tell which applies
                if entry_id in view.overrides:
                    raise ValueError(
                        f"the entry {entry_id} is overridden twice; an estate overrides an entry once, with the "
                        "decision that set it"
                    )
                view.overrides[entry_id] = value
        return view

    def entry(self, entry_id: str) -> PolicyEntry:
        try:
            return self.entries[entry_id]
        except KeyError:
            raise UnknownEntryError(
                f"policy.yaml holds no entry {entry_id!r}; it holds {', '.join(sorted(self.entries))}"
            ) from None

    def vocabulary(self, name: str) -> list[str]:
        try:
            return self.model.vocabularies[name].members
        except KeyError:
            raise UnknownEntryError(f"policy.yaml holds no vocabulary {name!r}") from None

    def method(self, method_id: str, version: int) -> Method:
        try:
            return self.methods[(method_id, version)]
        except KeyError:
            raise UnknownEntryError(
                f"policy.yaml registers no method {method_id} version {version}"
            ) from None

    def selected(self, entry_id: str) -> Method:
        """The method an entry selects, for an entry whose value is {method, version}."""
        v = self.get(entry_id)
        if not (isinstance(v, dict) and "method" in v and "version" in v):
            raise PolicyError(f"the entry {entry_id!r} selects no method")
        return self.method(v["method"], v["version"])

    def measure_method(self, value_id: str) -> Method:
        """The method that computes a register value, as `measure-methods` names it."""
        sel = self.get("measure-methods")
        if value_id not in sel:
            raise UnknownEntryError(f"measure-methods names no method for the value {value_id!r}")
        return self.method(sel[value_id]["method"], sel[value_id]["version"])

    def changed_since(self, version: int) -> list[str]:
        """The entries whose current value arrived after a policy version: what a portfolio written against that
        version reads differently today."""
        return sorted(e.id for e in self.model.entries if e.since > version)

    # the file's own rules
    def _check_self(self) -> None:
        m = self.model
        # each value of the shape its readers read, first: every rule below reads values by that shape
        shaped = [
            f"entry {e.id}: its value is not of the shape its readers read ({why})"
            for e in m.entries
            if (why := entry_value_problem(e.id, e.value, self.vocabulary))
        ]
        if shaped:
            raise PolicyError("policy.yaml breaks its own rules:\n  " + "\n  ".join(shaped))
        problems = []
        for e in m.entries:
            if e.change not in self.vocabulary("change_classes"):
                problems.append(f"entry {e.id}: change {e.change!r} is not a change class")
            for r in e.read_by:
                if r not in self.vocabulary("readers"):
                    problems.append(f"entry {e.id}: reader {r!r} is not in the readers vocabulary")
            for d in e.depends_on:
                if d not in self.entries:
                    problems.append(
                        f"entry {e.id}: depends on {d!r}, which policy.yaml does not hold"
                    )
            if e.since > m.policy_version:
                problems.append(
                    f"entry {e.id}: since {e.since} is after policy_version {m.policy_version}"
                )
            if e.one_way and e.overridable:
                problems.append(f"entry {e.id}: a one-way entry cannot be overridable")
        for (mid, ver), meth in self.methods.items():
            if meth.status not in self.vocabulary("method_status"):
                problems.append(
                    f"method {mid} {ver}: status {meth.status!r} is not a method status"
                )
            for r in meth.reads_entries:
                if r not in self.entries:
                    problems.append(
                        f"method {mid} {ver}: reads {r!r}, which policy.yaml does not hold"
                    )
        selected = {sel for e in m.entries for sel in selections(e.value)}
        for s in selected - set(self.methods):
            problems.append(f"an entry selects {s[0]} version {s[1]}, which no method registers")
        for s in set(self.methods) - selected:
            # a version in shadow runs beside the selected one, and a retired one stays so past outputs reproduce
            if self.methods[s].status == "current":
                problems.append(
                    f"the method {s[0]} version {s[1]} is current and selected by no entry"
                )
        if problems:
            raise PolicyError("policy.yaml breaks its own rules:\n  " + "\n  ".join(problems))


def selections(value: Any) -> list[tuple[str, int]]:
    """The method versions a value selects: a selection itself, or a mapping of selections (the measure methods, one
    per measure)."""

    def one(v: Any) -> bool:
        return isinstance(v, dict) and "method" in v and "version" in v

    if one(value):
        return [(value["method"], value["version"])]
    if isinstance(value, dict) and value and all(one(v) for v in value.values()):
        return [(v["method"], v["version"]) for v in value.values()]
    return []


def load_policy(path: Path = POLICY_PATH) -> Loaded:
    from .migrate import upgrade

    return Loaded(Policy.model_validate(upgrade("policy", read_yaml(path))[0]))


def load_register(path: Path = REGISTER_PATH) -> Register:
    return load_with_notes("register", path)[0]


def load_portfolio(path: Path = PORTFOLIO_PATH) -> Portfolio:
    return load_with_notes("portfolio", path)[0]


def load_with_notes(kind: str, path: Path) -> tuple[Register | Portfolio, list[str]]:
    """A register or a portfolio at the current schema version, migrated in memory from an older one, with a note per
    migration run: a file one version behind loads and is told so (section 5.12)."""
    from .migrate import upgrade

    doc, notes = upgrade(kind, read_yaml(path))
    model = {"register": Register, "portfolio": Portfolio}[kind]
    return model.model_validate(doc), notes


# ── vocabularies over the files they cover ─────────────────────────────────────────────────────────────────────────
NOTE = re.compile(r"\s*\(([^)]*)\)\s*$")


def _walk(node: Any, parts: list[str], at: str):
    """Yield (location, value) for a field path: `a.b`, `[]` every list item, `*` every map value, `**` any depth."""
    if not parts:
        yield at, node
        return
    head, rest = parts[0], parts[1:]
    if head == "**":
        yield from _walk(node, rest, at)
        if isinstance(node, dict):
            for k, v in node.items():
                yield from _walk(v, parts, f"{at}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from _walk(v, parts, f"{at}[{i}]")
        return
    if head == "*":
        if isinstance(node, dict):
            for k, v in node.items():
                yield from _walk(v, rest, f"{at}.{k}")
        return
    many = head.endswith("[]")
    key = head[:-2] if many else head
    if not isinstance(node, dict) or key not in node:
        return
    child = node[key]
    if many:
        for i, v in enumerate(child if isinstance(child, list) else []):
            yield from _walk(v, rest, f"{at}.{key}[{i}]")
    else:
        yield from _walk(child, rest, f"{at}.{key}")


def field_values(spec: str, docs: dict[str, Any]):
    """The (location, value) pairs a vocabulary's field spec covers in the documents given by root name. A spec on no
    document given (the drift-read lines when none are passed) covers nothing."""
    note = NOTE.search(spec)
    path = NOTE.sub("", spec).strip()
    root, _, rest = path.partition(".")
    if root not in docs:
        return
    for where, value in _walk(docs[root], rest.split("."), root):
        if note and "before the colon" in note.group(1) and isinstance(value, str):
            value = value.split(":", 1)[0]
        yield where, value
    if note and "absent means" in note.group(1):
        default = note.group(1).split("absent means", 1)[1].strip()
        parent = rest.rsplit(".", 1)[0]
        leaf = rest.rsplit(".", 1)[1]
        for where, item in _walk(docs[root], parent.split("."), root):
            if isinstance(item, dict) and leaf not in item:
                yield f"{where}.{leaf}", default


def check_vocabularies(
    loaded: Loaded, docs: dict[str, Any], extra_members: dict[str, list[str]] | None = None
) -> list[str]:
    """Every value a vocabulary covers that the vocabulary does not list, with its location. `extra_members` adds ids
    defined elsewhere (the planning tiers) to the check of a vocabulary-free field."""
    problems = []
    # a location a specific spec covers (no `**`) is that vocabulary's alone: a wildcard spec of another vocabulary
    # (`portfolio.**.kind`, the figure kinds) does not judge it (a portfolio's own trigger event has a kind of its own,
    # trigger_kinds; found by the first adopter portfolio, step 9)
    claimed = {
        where
        for vocab in loaded.model.vocabularies.values()
        for spec in vocab.fields
        if "**" not in spec
        for where, _value in field_values(spec, docs)
    }
    for name, vocab in loaded.model.vocabularies.items():
        members = set(vocab.members)
        for spec in vocab.fields:
            for where, value in field_values(spec, docs):
                if "**" in spec and where in claimed:
                    continue
                if value is not None and value not in members:
                    problems.append(f"{where}: {value!r} is not in the vocabulary {name}")
    for spec, members in (extra_members or {}).items():
        for where, value in field_values(spec, docs):
            if value is not None and value not in members:
                problems.append(f"{where}: {value!r} is not one of {sorted(members)}")
    return problems


# ── durations (ISO 8601), as the policy writes them (the pattern is the models', so a value is typed by it) ──────────


def months(iso: str) -> float:
    """An ISO 8601 date duration in months (a year 12, a week 7 days, a month 30.4375 days). Times are refused: the
    policy's durations are calendar ones."""
    m = DURATION.match(iso or "")
    if not m or iso == "P":
        raise PolicyError(f"{iso!r} is not an ISO 8601 date duration (PnYnMnWnD)")
    y, mo, w, d = (int(x) if x else 0 for x in m.groups())
    return y * 12 + mo + (w * 7 + d) / 30.4375


def add(day: date, iso: str) -> date:
    """A date moved forward by an ISO 8601 date duration, on the calendar: years and months by the calendar (the 31st of
    a shorter month is its last day), weeks and days by count. The date gate's arithmetic (GATE-13)."""
    m = DURATION.match(iso or "")
    if not m or iso == "P":
        raise PolicyError(f"{iso!r} is not an ISO 8601 date duration (PnYnMnWnD)")
    y, mo, w, d = (int(x) if x else 0 for x in m.groups())
    year, month = divmod(day.month - 1 + mo + 12 * y, 12)
    year += day.year
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(day.day, last)) + timedelta(weeks=w, days=d)
