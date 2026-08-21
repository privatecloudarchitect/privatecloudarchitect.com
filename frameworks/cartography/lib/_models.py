"""frameworks/cartography/lib/_models - the reconcile primitive and the recommendation shapes.

The pure decision core: a generator decides the DESIRED tags per object; this decides the minimal
action for each against the object's CURRENT tags, read from the vCenter source of truth.
Deliberately generic: category is a plain string, the object reference is whatever the actuator
resolves, and fill-gap policy is a parameter rather than a hardcode.

Action vocabulary:
  attach       no current value; set it (writes)
  change       a different value exists and change was permitted (writes)
  already-set  the value is already present (idempotent no-op)
  gap-kept     a fill-gap-only category already has a different value; leave it (no-op)
  hold-change  a different value exists and change was NOT permitted; surfaced, not applied

Teardown action vocabulary (reconcile_teardown, the inverse of the above):
  detach       our value is present; remove it (removes)
  absent       no value present in this category; nothing to remove (no-op)
  hold-foreign a different value is present; a human owns it, leave it (no-op)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DesiredTag:
    """One desired (object, category, value) assignment - the generator-to-management seam."""

    object_ref: str
    category: str
    value: str


@dataclass(frozen=True)
class TagAction:
    """The decided action for one desired assignment, judged against the object's current tags."""

    object_ref: str
    category: str
    value: str
    action: str
    current: str | None

    @property
    def writes(self) -> bool:
        return self.action in ("attach", "change")

    @property
    def removes(self) -> bool:
        return self.action == "detach"


def reconcile_actions(
    desired: list[DesiredTag],
    current_by_object: dict[str, dict[str, str]],
    *,
    gap_fill_only: frozenset[str] = frozenset(),
    allow_change: bool = False,
) -> list[TagAction]:
    """Decide the minimal action for each desired assignment against the CURRENT tags. Pure.

    Idempotent: an already-present value yields already-set, and a re-run yields identical
    no-op actions. A fill-gap-only category is set when absent and never overwritten, even
    with allow_change."""
    actions: list[TagAction] = []
    for d in desired:
        current = current_by_object.get(d.object_ref, {}).get(d.category)
        if current == d.value:
            action = "already-set"
        elif current is None:
            action = "attach"
        elif d.category in gap_fill_only:
            action = "gap-kept"
        elif not allow_change:
            action = "hold-change"
        else:
            action = "change"
        actions.append(TagAction(object_ref=d.object_ref, category=d.category,
                                 value=d.value, action=action, current=current))
    return actions


def reconcile_teardown(
    desired: list[DesiredTag],
    current_by_object: dict[str, dict[str, str]],
) -> list[TagAction]:
    """Decide the removal action for each desired assignment against the CURRENT tags. Pure.

    The symmetric inverse of reconcile_actions: a value is removed only when it is exactly the
    value this framework would have written AND is exactly the value currently present. A
    different value in the same category is a human's decision and is held, never removed; an
    absent value is already gone. So a teardown undoes precisely what the matching write did,
    and nothing a person changed afterward."""
    actions: list[TagAction] = []
    for d in desired:
        current = current_by_object.get(d.object_ref, {}).get(d.category)
        if current == d.value:
            action = "detach"
        elif current is None:
            action = "absent"
        else:
            action = "hold-foreign"
        actions.append(TagAction(object_ref=d.object_ref, category=d.category,
                                 value=d.value, action=action, current=current))
    return actions
