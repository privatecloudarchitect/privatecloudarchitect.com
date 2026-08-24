"""Copy-discipline gate for authored dashboard content.

A WTPC dashboard teaches the CURRENT model. Copy that narrates the content's own evolution
("was replaced", "no longer", "the original rule", "used to") is a changelog tell: it parses only
for a reader who already knows the history, and it goes stale the instant that history is a footnote.
This gate fails the build on that class of phrasing, so it is caught during copy construction rather
than in review. State the model as the model.

Kept deliberately conservative (unambiguous self-history markers only) so it never fires on legitimate
prose; "now" / "is now" are intentionally NOT markers.
"""
import re

_MARKERS = [
    r"\bwas replaced\b", r"\bwere replaced\b", r"\breplaced by\b", r"\b(?:has|have) been replaced\b",
    r"\bsuperseded\b", r"\bused to be\b", r"\bformerly\b",
    r"\bthe original (?:rule|model|approach|design|behaviou?r|method|way|version|scheme)\b",
    r"\bthe older (?:rule|model|approach|design|behaviou?r|method|way|version|scheme)\b",
    r"\bdeprecated\b", r"\bwe (?:changed|moved|switched|renamed|replaced)\b",
    r"\bchanged from\b", r"\bmoved from\b",
]
# Deliberately NOT markers: "no longer", "used to", "previously", "now"/"is now" - each false-positives
# on legitimate current-state prose (a working set that "no longer fits", a tool "used to derive X").
_RX = re.compile("|".join(_MARKERS), re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def changelog_sentences(html: str) -> list[str]:
    """The offending sentences (HTML tags stripped) in one widget's copy, or []."""
    text = _WS.sub(" ", _TAG.sub(" ", html)).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if _RX.search(s)]


def assert_current_voice(widgets: dict) -> None:
    """widgets: {label: html}. Raise AssertionError listing every changelog-style sentence found.

    The build calls this so authored copy states the current model, never its own history."""
    bad = []
    for label, html in widgets.items():
        for s in changelog_sentences(html):
            bad.append(f"  [{label}] {s}")
    if bad:
        raise AssertionError(
            "changelog-style copy is forbidden (state the current model, not its history):\n"
            + "\n".join(bad))
