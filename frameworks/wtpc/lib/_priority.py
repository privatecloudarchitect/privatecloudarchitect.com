"""wtpc/lib/_priority — rank our own policies without moving anybody else's.

VCF Operations resolves an object to the single highest-ranked policy among the groups that hold it, and the
priority list is one shared, global order. On a shared instance other teams rank their own policies, so the
framework reorders only its own: it keeps every foreign policy exactly where it is and arranges its own
policies inside the positions they already hold. A policy of ours that is not ranked yet goes immediately
after the last position ours hold. Whether a foreign policy above ours actually takes one of our members is
the effective-policy parity gate's question (validate_live.py), and moving ours above it is an explicit,
opt-in decision (--rank-above-foreign), never a side effect of a converge.
"""
from __future__ import annotations


def within_own_slots(current: list[str], ours_in_order: list[str]) -> list[str]:
    """The ranked list with our policies in `ours_in_order`, each foreign policy left at its position."""
    ours = set(ours_in_order)
    ranked = set(current)
    slots = [i for i, pid in enumerate(current) if pid in ours]
    out = list(current)
    for i, pid in zip(slots, [p for p in ours_in_order if p in ranked]):
        out[i] = pid
    at = slots[-1] + 1 if slots else len(out)
    out[at:at] = [p for p in ours_in_order if p not in ranked]
    return out


def above_foreign(current: list[str], ours_in_order: list[str]) -> list[str]:
    """The opt-in order: our policies first, in `ours_in_order`, then every other ranked policy as it was."""
    return list(ours_in_order) + [p for p in current if p not in set(ours_in_order)]
