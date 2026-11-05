"""The drift reads (20-PILOT.md step 5; 40-BREADTH.md step 7; charter section 5.6): a companion's scrubbed records in,
drift-read lines out, at the contract version `policy.yaml` selects. No adapter changes a companion's record.

This module is the registry, the loader and the one builder every line passes through. `ADAPTERS` maps the companion
string a capability's `drift_read` names to the pinned copies of the records its adapter reads and the adapter's module
under `generator/adapters/`, imported on first use so the generator's import cost does not grow with the adapters. The
register, not the adapter, decides what a read is for: the capability a line belongs to is the one whose `drift_read`
names the companion.

The loader alone opens files. It verifies each copy against its sha256 in `records/pinned/pins.yaml` and refuses a
replayed record; a copy that is missing, altered or replayed, or an adapter that refuses its records, yields one
`check_failed` line per declaration, so a page still renders and the read never counts as in sync. An adapter is pure
over the records it is given, and every declaration gets a line on every read: one its companion does not read is
`unread` and `not_covered`, so the denominator is whole.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from .files import parsed
from .models import DriftLine, Parameter, Pins, Register
from .policy import Loaded

LAYER = Path(__file__).resolve().parent.parent
ROOT = LAYER.parents[2]
PINS = LAYER / "records" / "pinned" / "pins.yaml"
PINNED = "docs/design/enterprise-strategy-layer/records/pinned"


class RefusedError(ValueError):
    """A record an adapter will not turn into lines."""


@dataclass(frozen=True)
class Adapter:
    # the pinned copies the adapter reads, each a path from the repository root
    records: tuple[str, ...]
    # its module under generator/adapters/
    module: str
    # whether its lines read figures the portfolio carries under the capability's parameters (schema 5; 64's ruling)
    parameters: bool = False


# each adapter reads the pinned copies of its companion's records (records/pinned/pins.yaml; 40-BREADTH.md step 2),
# never the lane's live records, so a lane that refreshes a record fails no push; a strategy release refreshes the copy
ADAPTERS: dict[str, Adapter] = {
    "handbook/host-lifecycle": Adapter(
        (f"{PINNED}/handbook-host-lifecycle.record.json",), "host_lifecycle"
    ),
    "handbook/platform-backup": Adapter(
        (f"{PINNED}/handbook-platform-backup.recovery.json",), "platform_backup"
    ),
    "frameworks/cartography": Adapter(
        (f"{PINNED}/frameworks-cartography.coverage.json",), "cartography"
    ),
    "handbook/construct-model": Adapter(
        (
            f"{PINNED}/handbook-construct-model.edges.json",
            f"{PINNED}/handbook-construct-model.naming.json",
            f"{PINNED}/handbook-construct-model.naming-standard.json",
        ),
        "construct_model",
    ),
    # the catalog sweep of content-libraries (lab/state/images), since day1.json holds no declared state yet (f8), and
    # content-libraries' own read of each namespace's image pins and locks (libraries.py --pins --lock, 1b's companion)
    "handbook/day1-provisioning": Adapter(
        (
            f"{PINNED}/handbook-day1-provisioning.catalog-pin-read.json",
            f"{PINNED}/handbook-content-libraries.libraries.json",
        ),
        "day1_provisioning",
    ),
    "handbook/day2-pathways": Adapter(
        (f"{PINNED}/handbook-day2-pathways.pathways.json",), "day2_pathways"
    ),
    "handbook/hardening-audit": Adapter(
        (f"{PINNED}/handbook-hardening-audit.hardening.json",), "hardening_audit", parameters=True
    ),
    "handbook/isolation-design": Adapter(
        (f"{PINNED}/handbook-isolation-design.isolation.json",), "isolation_design"
    ),
    "handbook/microsegmentation": Adapter(
        (f"{PINNED}/handbook-microsegmentation.posture.json",), "microsegmentation"
    ),
    "handbook/platform-lifecycle": Adapter(
        (f"{PINNED}/handbook-platform-lifecycle.lifecycle.json",), "platform_lifecycle"
    ),
    # 64's companions, on 64's rulings as their lane (2026-11-02)
    "handbook/identity-lifecycle": Adapter(
        (f"{PINNED}/handbook-identity-lifecycle.leavers.json",), "identity_lifecycle"
    ),
    # catalog_check.py's record of the estate's credential catalog, and integrations-identity's session census as a
    # drift-only proxy for the client-per-integration declaration (64)
    "handbook/service-accounts": Adapter(
        (
            f"{PINNED}/handbook-service-accounts.catalog-check.json",
            f"{PINNED}/handbook-integrations-identity.exchange.json",
        ),
        "service_accounts",
    ),
    # 3c's companions, on 3c's rulings as their lane (2026-11-02)
    "handbook/alerting-doctrine": Adapter(
        (f"{PINNED}/handbook-alerting-doctrine.alerts.json",), "alerting_doctrine"
    ),
    "handbook/capacity-forecasting": Adapter(
        (f"{PINNED}/handbook-capacity-forecasting.runway.json",), "capacity_forecasting"
    ),
    "handbook/cost-showback": Adapter(
        (f"{PINNED}/handbook-cost-showback.coverage.json",), "cost_showback"
    ),
    "handbook/incident-response": Adapter(
        (f"{PINNED}/handbook-incident-response.triage.json",), "incident_response"
    ),
    "handbook/log-alerts": Adapter(
        (f"{PINNED}/handbook-log-alerts.deploy-status.json",), "log_alerts"
    ),
    # metrics-collection's scripts write no record: its lines read log-collection's and flow-collection's (3c, B7)
    "handbook/metrics-collection": Adapter(
        (
            f"{PINNED}/handbook-log-collection.log-paths.json",
            f"{PINNED}/handbook-flow-collection.flow-paths.json",
            f"{PINNED}/handbook-flow-collection.exporters.json",
        ),
        "metrics_collection",
    ),
    "handbook/ops-estate": Adapter((f"{PINNED}/handbook-ops-estate.content.json",), "ops_estate"),
}


def line(
    *,
    capability: str,
    declaration,
    store: str | None,
    declared_version: str | None,
    scope: str,
    mode: str,
    result: str,
    items_declared: int,
    items_drifted: int,
    items: list[dict],
    read_at: str,
    checked_at: str | None,
    companion: str,
    check: str,
    record: str,
    exit: int | None,
    pol: Loaded,
    replay: bool = False,
) -> dict:
    """One line of the drift-read contract, validated."""
    return DriftLine.model_validate(
        {
            "capability": capability,
            "declaration": {
                "system": declaration.system,
                "object": declaration.object,
                "writer": declaration.writer,
                "store": store,
                "declared_version": declared_version,
            },
            "scope": scope,
            "mode": mode,
            "contract_version": pol.get("drift-contract")["version"],
            "result": result,
            "items_declared": items_declared,
            "items_drifted": items_drifted,
            "items": items,
            "read_at": read_at,
            "checked_at": checked_at,
            "source": {
                "companion": companion,
                "check": check,
                "record": record,
                "exit": exit,
                "replay": replay,
            },
        }
    ).model_dump()


def unread(
    *,
    capability: str,
    declaration,
    scope: str,
    read_at: str,
    companion: str,
    check: str,
    record: str,
    exit: int | None,
    pol: Loaded,
) -> dict:
    """The line for a declaration the companion does not read: unread, not covered, nothing counted."""
    return line(
        capability=capability,
        declaration=declaration,
        store=None,
        declared_version=None,
        scope=scope,
        mode="unread",
        result="not_covered",
        items_declared=0,
        items_drifted=0,
        items=[],
        read_at=read_at,
        checked_at=None,
        companion=companion,
        check=check,
        record=record,
        exit=exit,
        pol=pol,
    )


def _failed(cap, companion: str, record: str, read_at: str, why: str, pol: Loaded) -> list[dict]:
    """One check_failed line per declaration: a read that could not judge, never counted as in sync."""
    return [
        line(
            capability=cap.id,
            declaration=d,
            store=None,
            declared_version=None,
            scope="estate",
            mode="detected",
            result="check_failed",
            items_declared=0,
            items_drifted=0,
            items=[],
            read_at=read_at,
            checked_at=None,
            companion=companion,
            check=why,
            record=record,
            exit=None,
            pol=pol,
        )
        for d in cap.declarations
    ]


def _pins(root: Path, pins_dir: Path | None = None) -> dict[str, object]:
    """Each pin by the key a run resolves records with: the pin's file path from the repository root, or, under
    `pins_dir` (an adopter's flat folder, pins.yaml beside the copies; 40-BREADTH.md step 9), its file's basename. Two
    pins of one basename are refused there, since a flat folder cannot hold both (3c's judgment of step 9, F6)."""
    path = (pins_dir / "pins.yaml") if pins_dir is not None else root / PINS.relative_to(ROOT)
    # parsed once per process until the file moves: a render reads it once per capability (generator/files.py)
    pins = parsed(path, lambda text: Pins.model_validate(yaml.safe_load(text))).pins
    if pins_dir is None:
        return {p.file: p for p in pins}
    by_name: dict[str, object] = {}
    for p in pins:
        name = Path(p.file).name
        if name in by_name:
            raise ValueError(
                f"{path}: two pins share the basename {name!r}, which a flat records folder cannot hold"
            )
        by_name[name] = p
    return by_name


def _unread(cap, companion: str, record: str, read_at: str, why: str, pol: Loaded) -> list[dict]:
    """One not_covered line per declaration: a companion the estate did not supply a record of holds none of its
    declarations (R4), so nothing is counted, in sync or failed."""
    return [
        unread(
            capability=cap.id,
            declaration=d,
            scope="estate",
            read_at=read_at,
            companion=companion,
            check=why,
            record=record,
            exit=None,
            pol=pol,
        )
        for d in cap.declarations
    ]


def read_capability(
    cap_id: str,
    pol: Loaded,
    register: Register,
    root: Path = ROOT,
    parameters: Mapping[str, Parameter] | None = None,
    pins_dir: Path | None = None,
) -> list[dict]:
    """The capability's drift lines from its companion's pinned records; none where no adapter is built yet.
    `parameters` are the capability's figures in the portfolio being rendered; an adapter that reads them is handed
    them, and one absent, or of kind not_recorded, reads as not read (64's ruling, 2026-11-02). `pins_dir` is an
    adopter's records folder (40-BREADTH.md step 9): pins.yaml beside the copies, flat, each record found by its
    basename; a record the adopter did not supply is a declaration no record holds, not_covered (R4), where the
    reference run's missing pin is a broken repository, check_failed (1b, 2026-11-02). An adapter that reads two
    records stops at the first one not supplied, so the capability's every declaration is then not covered, the one the
    supplied record could have read included; reading what is supplied and leaving the rest not covered is a later
    change, adapter by adapter, with each lane."""
    cap = next(c for c in register.capabilities if c.id == cap_id)
    companion = cap.drift_read.companion
    adapter = ADAPTERS.get(companion) if companion else None
    if adapter is None:
        return []
    pins = _pins(root, pins_dir)
    if not pins:
        where = (pins_dir / "pins.yaml") if pins_dir is not None else PINS.relative_to(ROOT)
        raise ValueError(f"{where} pins no record: the views have nothing to read")
    # an unpinned record has no date of its own: its failed line carries the pin set's newest date, never an epoch a
    # page could print and never a clock (only the core reads one, for `generated_at`; 64's review)
    newest = max(str(p.pinned) for p in pins.values())
    records: dict[str, dict] = {}
    for path in adapter.records:
        key = Path(path).name if pins_dir is not None else path
        pin = pins.get(key)
        read_at = str(pin.pinned) if pin else newest
        file = (pins_dir / key) if pins_dir is not None else root / path
        if pin is None:
            if (
                pins_dir is not None
            ):  # the record named as the adopter would have supplied it, by its basename
                return _unread(
                    cap,
                    companion,
                    key,
                    read_at,
                    f"not read: no record {key} of {companion} supplied",
                    pol,
                )
            return _failed(cap, companion, path, read_at, "the record is not pinned", pol)
        if not file.is_file():
            return _failed(cap, companion, path, read_at, "the pinned record is missing", pol)
        data = file.read_bytes()
        if hashlib.sha256(data).hexdigest() != pin.sha256:
            return _failed(
                cap, companion, path, read_at, "the pinned record differs from its pin", pol
            )
        try:
            rec = json.loads(data)
        except ValueError:
            rec = None
        if not isinstance(rec, dict):
            # a transcript or any other non-object is no record an adapter can read (3c's batch, 2026-11-02)
            return _failed(
                cap, companion, path, read_at, "the pinned record is not a JSON object", pol
            )
        if rec.get("replay"):
            return _failed(
                cap, companion, path, read_at, "a replayed record is no read of an estate", pol
            )
        records[path] = rec
    module = importlib.import_module(f"{__package__}.adapters.{adapter.module}")
    try:
        if adapter.parameters:
            return module.lines(records, pol, register, cap_id, parameters=dict(parameters or {}))
        return module.lines(records, pol, register, cap_id)
    except RefusedError as e:
        first = adapter.records[0]
        return _failed(cap, companion, first, str(pins[first].pinned), str(e), pol)


PRINCIPAL_KEYS = frozenset(
    {"account", "principal", "user", "username", "subject", "client", "credential"}
)
_PLACEHOLDER = re.compile(r"^\{\{[a-z0-9-]+\}\}$")
_BACKSLASHED = re.compile(r"[A-Za-z0-9_-]+\\(?!\{\{)")  # DOMAIN\name, unless a placeholder follows


def _walk(node, path: str = ""):
    """Every (path, key, string) in a line, the path in the form items[0].actual.user."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, path.rsplit(".", 1)[-1], node


def line_leaks(x: dict, lists=None) -> list[str]:
    """Why a drift line must not reach a view, each reason naming a kind and a place and never a value (1b's rule, so
    the guard republishes nothing it caught): a value under a principal key that is no placeholder, a backslashed
    principal in any string but a naming pattern, an email address, or estate identifiers the scrub list catches
    (scrublist.caught, with the passed lists or the publisher's). The rules the reference tests assert over every adapter's
    lines, as one function an adopter's run can call (1b and 3c, step 9, 2026-11-02)."""
    from . import scrublist  # the list read as data; no renderer and no clock behind it

    why = []
    for path, key, value in _walk(x.get("items") or [], "items"):
        if key in PRINCIPAL_KEYS and not _PLACEHOLDER.match(value):
            why.append(f"a value under `{key}` at {path} that is no placeholder")
    for path, key, value in _walk(x):
        if key != "pattern" and _BACKSLASHED.search(value):
            why.append(f"a backslashed principal at {path}")
        if "@" in value:
            why.append(f"an email address at {path}")
    caught = scrublist.caught(json.dumps(x, ensure_ascii=False), lists)
    if caught:
        why.append(f"{caught} identifier(s) the scrub list catches")
    return why


def guard_lines(lines: list[dict], lists=None) -> list[dict]:
    """Every line checked before it reaches a view: a line that leaks (line_leaks) becomes check_failed with its items
    dropped and the reasons in its check text, so a record that names an estate's value is never rendered; a clean line
    passes as it is."""
    out = []
    withheld: dict[
        str, int
    ] = {}  # withheld scopes numbered per kind, so no two lines share one scope string
    for x in lines:
        why = line_leaks(x, lists)
        if not why:
            out.append(x)
            continue
        held = dict(x)
        held["result"] = "check_failed"
        held["mode"] = "detected"
        held["items"] = []
        held["items_drifted"] = 0
        if (
            ":" in str(x.get("scope", ""))
        ):  # a scope's key names the estate's thing: withheld with the items, numbered in the run's order (1b)
            kind = str(x["scope"]).split(":", 1)[0]
            withheld[kind] = withheld.get(kind, 0) + 1
            held["scope"] = f"{kind}:[withheld {withheld[kind]}]"
        held["source"] = dict(x["source"], check=f"not read: the record leaks ({'; '.join(why)})")
        out.append(DriftLine.model_validate(held).model_dump())
    return out


def lines(
    record: dict, record_path: str, pol: Loaded, register: Register, capability: str | None = None
) -> list[dict]:
    """The host-lifecycle adapter over one record, as PH2 called it (the generator's tests read it this way). A replay
    raises RefusedError here; through read_capability it is a check_failed line."""
    from .adapters import host_lifecycle

    if record.get("replay"):
        raise RefusedError("a replayed record is no read of an estate")
    capability = capability or next(
        c.id for c in register.capabilities if c.drift_read.companion == host_lifecycle.COMPANION
    )
    return host_lifecycle.lines({record_path: record}, pol, register, capability)
