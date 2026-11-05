"""The strategy layer's views, rendered and validated (30-GATES.md step 6; DEC-07 places them on the site).

  strategy-<capability>.html        a capability's page: what it returns, what it costs once and each period, who owns
                                    it, how far the reference estate has got, and where each part is taught
  board-reference.html              the reference portfolio's board: the rank, the capacity line, where the rank turns,
                                    the planning tiers, every illustrative input labelled
  costs-and-value-reference.html    V-03's view: each capability's one-time investment against its recurring effort, its
                                    targets and the cost of waiting
  role-<role>.html                  a role's public brief, from the register alone (charter section 6)
  index.html                        every capability, the two portfolio views and every role brief

Each view's root names the files it renders (`data-source`), so GATE-7 knows which views show portfolio figures. All
are wrapped in the site's own layout (deploy/privatecloudarchitect/site/src/layout.html), so they render with the
house type, tokens and themes; every fact comes from the register, the portfolio, the generator's report or the
measure's output, never typed here (GATE-10). A hand-off goes only to a published page, or the render fails.
Validation renders each page in both themes at a desktop and a phone width with the site's own probe
(render_validate.py), and fails on a sideways scroll, an overflowing node or a face that did not load.

Run from the repository root: .venv/bin/python -m generator.render (with docs/design/enterprise-strategy-layer on the
path), or docs/design/enterprise-strategy-layer/generator/render.py.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

LAYER = Path(__file__).resolve().parent.parent
ROOT = LAYER.parents[2]
SITE = ROOT / "deploy" / "privatecloudarchitect" / "site"
OUT = LAYER / "generator" / "rendered"
E = html.escape
# the generation stamp, where this renderer writes it (the provenance line), and nowhere else on a page: the one part
# of a page that differs on every render, which every comparison of a page with its committed copy sets aside
GENERATED = re.compile(r'(<p class="prov"[^>]*>)Generated \S+ by')
PROV_OPEN = re.compile(r'<p class="prov"[^>]*>')
STAMPED = re.compile(r"Generated (\S+) by")


def stampless(text: str) -> str:
    """A page with its generation stamp set aside for a comparison: the stamp replaced by a mark only a stamp leaves,
    so a page whose stamp was deleted by hand never compares equal to a stamped one."""
    return GENERATED.sub(r"\1Generated <stamp> by", text)


def stamp_shaped(page: str) -> bool:
    """Whether every provenance line on a page opens with a generation stamp that the one parser of a run's time reads
    (models.parse_stamp): a line with no stamp, or with one the calendar or the clock lacks, fails."""
    if str(LAYER) not in sys.path:
        sys.path.insert(0, str(LAYER))
    from generator.models import parse_stamp

    for m in PROV_OPEN.finditer(page):
        s = STAMPED.match(page, m.end())
        try:
            parse_stamp(s.group(1) if s else "")
        except ValueError:
            return False
    return True


STYLE = """<style>
.esl table{border-collapse:collapse;width:100%;font-size:15px;margin:8px 0 18px}
.esl th,.esl td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
.esl td{overflow-wrap:break-word}  /* a word breaks only when it cannot fit, so a column is never narrower than its words */
.esl td small{display:block;white-space:normal;color:var(--soft)}
.esl th{color:var(--soft);font-weight:600}
.esl .scroll{overflow-x:auto}
.esl .illus{display:inline-block;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--soft);
  border:1px solid var(--line-2);border-radius:4px;padding:0 5px;margin-left:6px;white-space:nowrap}
.esl .state{font-weight:600}
.esl .prov{color:var(--faint);font-size:14px;border-top:1px solid var(--line);margin-top:28px;padding-top:10px}
@media (max-width:640px){
 .esl table,.esl table tbody{display:block;width:100%;min-width:0}  /* the layout's tables keep a min-width */
 .esl table thead{display:none}
 .esl table tr{display:block;border-bottom:1px solid var(--line);padding:6px 0}
 .esl table td{display:block;border:0;padding:3px 8px}
 .esl table td::before{content:attr(data-label);display:block;font-size:12px;letter-spacing:.04em;
   text-transform:uppercase;color:var(--soft)}
}
</style>"""

SPAN = {"D": "day", "W": "week", "M": "month", "Y": "year"}


def _all_parts(iso: str) -> list[tuple[int, str]]:
    """Each part of an ISO 8601 date duration, largest first; a form it cannot read is refused, never shown raw."""
    m = re.fullmatch(r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?", iso or "")
    if not m or iso == "P":
        raise ValueError(f"{iso!r} is not a date duration the pages can put in words")
    return [(int(n), SPAN[u]) for n, u in zip(m.groups(), "YMWD", strict=True) if n]


def _parts(iso: str) -> tuple[int, str] | None:
    """The one part of a single-unit duration, or None for a compound one."""
    parts = _all_parts(iso)
    return parts[0] if len(parts) == 1 else None


def span(iso: str) -> str:
    """An ISO 8601 date duration in words: three months, one year and six months. Computed, never looked up, so no
    duration the policy defines is written here (GATE-14)."""
    return " and ".join(f"{n} {unit}{'' if n == 1 else 's'}" for n, unit in _all_parts(iso))


def _months(iso: str) -> int | None:
    """A duration in whole months, when it is made of years and months only."""
    parts = _all_parts(iso)
    if any(unit not in ("year", "month") for _n, unit in parts):
        return None
    return sum(n * 12 if unit == "year" else n for n, unit in parts)


def per(iso: str) -> str:
    """A period as a rate: a month, a quarter, half a year, a year, or every N units."""
    p, m = _parts(iso), _months(iso)
    if p and p[0] == 1:
        return f"a {p[1]}"
    named = {3: "a quarter", 6: "half a year", 12: "a year"}
    return named.get(m, f"every {span(iso)}") if m else f"every {span(iso)}"


def every(iso: str) -> str:
    """A cadence for an 'every' column: month, week, quarter, or N units."""
    p, m = _parts(iso), _months(iso)
    if p and p[0] == 1:
        return p[1]
    named = {3: "quarter", 6: "half year", 12: "year"}
    return named.get(m, span(iso)) if m else span(iso)


def words(ident: str) -> str:
    """An id as words, for a reader: restore-recency as restore recency."""
    return str(ident).replace("-", " ")


def named(register, ident: str) -> str:
    """A capability, an initiative, a watch entry or a planned capability as a page names it: its `name` where the
    register gives one (schema 3), its id in words otherwise."""
    for x in [*register.capabilities, *register.initiatives, *register.watch_list]:
        if x.id == ident:
            return x.name or words(ident)
    return words(ident)


def system_named(declaration) -> str:
    """A declaration's system as a page names it: its `system_name` where the register gives one (schema 3), else its
    id, set as code."""
    if declaration.system_name:
        return E(declaration.system_name)
    return f"<code>{E(declaration.system)}</code>"


def _the(text: str) -> str:
    """ "the X" unless X already opens with an article or a quantifier: the register writes "each policy's enablement
    list" and "the statistics level" as objects, and a page never doubles the article (step 10's review)."""
    low = text.lower()
    return (
        text
        if low.startswith(("the ", "each ", "every ", "a ", "an ", "all ", "one ", "any "))
        else f"the {text}"
    )


def _public(text: str) -> str:
    """A register text as a public page prints it: a citation of the layer's own research record or a fetch note, in
    parentheses, is dropped; the public source it accompanies stays (step 10's review: a reader off the project cannot
    resolve "research/r4 S-01")."""
    return re.sub(r"\s*\((?:[^()]*\bresearch/r\d[^()]*|the text fetched [0-9-]+)\)", "", text)


# the adoption bar's levels in words by their order, as the research record defined them (10-RESEARCH.md M13) and
# core.grade reads them from the policy's method; a page names a level and says what it requires, never the name alone,
# and holds no level's id (the ids are the policy's, read through the loader: GATE-14's clause 14.1)
LEVEL_WORDS = {
    0: "not every establish step is done",
    1: "every establish step is done",
    2: "one accountable department holds it in the scope, every declaration has a writer, and its drift read is in "
    "place",
    3: "sustained on its cadence, drift in sync or covered, every value measured by its instrument against a recorded "
    "target",
    4: "a target grade recorded in the decision log justifies its cost",
}
ORDINALS = {0: "first", 1: "second", 2: "third", 3: "fourth", 4: "fifth"}


def _plural(n: int, one: str, many: str) -> str:
    """A count with its noun: "1 loop", "2 loops"."""
    return f"{count(n)} {one if n == 1 else many}"


def _brief(text: str | None, limit: int = 140) -> str:
    """A reading's first clause for a standing line: up to its first semicolon or full stop, and no longer than the
    limit, with an ellipsis where it was cut."""
    if not text:
        return ""
    head = re.split(r"(?<=[.;])\s", text, maxsplit=1)[0]
    if len(head) > limit:
        cut = head[: limit - 1]
        head = (cut.rsplit(" ", 1)[0] if " " in cut else cut) + "\u2026"
    depth, last_balanced = (
        0,
        len(head),
    )  # never cut inside a parenthesis: close at the last balanced point
    for i, ch in enumerate(head):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth == 0:
            last_balanced = i + 1
    if depth > 0:
        head = head[: head.rfind("(", 0, last_balanced + 1)].rstrip() + "\u2026"
    return head.rstrip(" ,:;")


MODE_WORDS = {
    "detected": "detected, the companion comparing the declared state with the one it observed",
    "replayed": "replayed from a stored record",
}


def value_name(register, value_id: str) -> str:
    """A value as a reader names it: its outcome, as the register words it, never its id, which keys the records and
    may outlive a change in what is measured. An id no register value holds (a conversion rate's or an unconverted
    measure the portfolio names) is refused: it has no outcome to show, and the rank would weigh a measure no value
    reads."""
    from generator.models import resolve_value

    return resolve_value(
        register, value_id
    ).outcome  # a retired id reads as its successor (schema 3)


# the words that open a name the register writes as a sentence and that are set in lower case inside one; no other
# word is, so a product or a proper name (Kubernetes, Salt, ESX) keeps its capital wherever it opens a name
DETERMINERS = {
    "a",
    "an",
    "the",
    "no",
    "every",
    "each",
    "all",
    "any",
    "some",
    "one",
    "both",
    "either",
    "neither",
}


def inline(name: str) -> str:
    """A name the register words as a sentence, set inside one: its opening word in lower case when that word is a
    determiner (A, No, Every), and as the register writes it otherwise."""
    first = name.split(" ", 1)[0]
    if first.lower() in DETERMINERS and first == first.capitalize():  # "No", "A"; never "NO"
        return first.lower() + name[len(first) :]
    return name


def role_text(name: str) -> str:
    """A role's name set inside a sentence: each word in lower case, save one with a capital after its first letter (an
    acronym or a product's name: SRE, VMware), which keeps the register's case."""
    return " ".join(w if any(c.isupper() for c in w[1:]) else w.lower() for w in name.split(" "))


def part_name(cap, part_id: str) -> str:
    """An establish step or a sustain loop as a reader names it: its text, as the register words it and as its
    capability's page names it, never its id; an id the capability holds no part for is said in words."""
    for s in cap.establish:
        if s.id == part_id:
            return s.step
    for lp in cap.sustain:
        if lp.id == part_id:
            return lp.loop
    return words(part_id)


def amount(value: float, unit: str) -> str:
    """A figure with its unit, the unit's first word singular when the figure is one."""
    if value == 1:
        first, _, rest = unit.partition(" ")
        unit = (first[:-1] if first.endswith("s") else first) + (" " + rest if rest else "")
    return f"{value:g} {unit}"


# The renderer's format version: raised by hand when a change to the renderer changes what a served page says, and
# pinned with a fingerprint of the served pages rendered from frozen slices (rendered/format.lock.yaml), so a served
# page's digest names the renderer that wrote it (40-BREADTH.md step 2, S1).
FORMAT = 7  # 7: schema 6's versions in the provenance line and the input digest they enter (the front door's readers, DEC-06); 6: the agentic page and the drivers' view served from their slices (step 12); 5: the layer's public name on every page (step 11, DEC-01); 4: the standing line, every value defined with its direction, the drift read's instrument and comparison, the levels in words, the public wording (step 10); 3: schema 5's versions in the provenance line (step 5); 2: schema 4's and a drift read no companion makes yet, said (step 4)
NAME = "The Architect's NOC"  # the layer's public name (DEC-01, 00-CHARTER.md section 10), on every page's eyebrow and the index's description, and on the companion's frame; "the strategy layer" stays the descriptive phrase in prose, and the pages' paths are unchanged (D-053)


def fig(
    value,
    unit: str | None,
    kind: str | None,
    source: str | None = None,
    node: tuple | None = None,
    text: str | None = None,
    label: bool | str = True,
    tail: str = "",
) -> str:
    """Every figure a page prints from a portfolio node or computes from several: its text (`amount`, or the figure
    alone), its label (`illus`) inside, wrapped as `<span data-node data-kind>` so the site check finds each figure, its
    kind and the node it was read from (40-BREADTH.md step 2, S4). A figure whose sentence already says how it is known
    (a measured reading "measured on" a day) may leave its label out; an illustrative or input one never does."""
    if label is False and kind in ("illustrative", "input"):
        raise ValueError(f"an {kind} figure is printed with its label ({value!r})")
    shown = text if text is not None else (amount(value, unit) if unit else f"{value:g}")
    where = f' data-node="{E("/".join(node), quote=True)}"' if node else ""
    said = label if isinstance(label, str) else (illus(kind, source) if label else "")
    return f'<span{where} data-kind="{E(kind or "", quote=True)}">{E(shown)}{said}{tail}</span>'


NOT_YET = "not yet published"  # a node the served projection withheld, never "not recorded" (40-BREADTH.md, S3)


def _held(served, address: tuple) -> bool:
    """Whether the served projection withheld the node at an address; a review view (`served` None) withholds none."""
    return served is not None and address in served.withheld


def count(n: int) -> str:
    """A count the page computed itself (steps done, reads in sync, a place in the rank): no figure of a portfolio's,
    so it carries no kind (40-BREADTH.md step 2, S4)."""
    if not isinstance(n, int):
        raise ValueError(f"a count is a whole number, never {n!r}")
    return str(n)


def illus(kind: str | None, source: str | None = None) -> str:
    """The one place a figure's kind is said beside it: the illustrative label, who supplied an input, or that it was
    measured."""
    if kind == "illustrative":
        return '<span class="illus">illustrative</span>'
    if kind == "input":
        if not (
            source or ""
        ).strip():  # an input is shown with who supplied it; naming no one is refused
            raise ValueError(
                "an input figure names no supplier (its `source`); name who supplied it and when"
            )
        return f" <small>(supplied by {E(source)})</small>"
    if kind == "measured":
        return " <small>(measured)</small>"
    if kind == "not_recorded":
        return " <small>(not recorded)</small>"
    raise ValueError(  # a kind with no words would reach a page bare
        f"the kind {kind!r} has no words to say it beside a figure; a new kind is a method change (DEC-14)"
    )


def graded(reading) -> str:
    """A measured reading's date and grade, beside it, as the chapters grade every claim."""
    said = [
        x
        for x in (
            f"read {reading.read_at[:10]}" if reading.read_at else "",
            f"graded {reading.confidence}",
        )
        if x
    ]
    if reading.kind == "illustrative":  # labelled as every illustrative figure is
        return f"{illus('illustrative')} <small>({E(', '.join(said))})</small>"
    head = {"measured": "measured", "not_recorded": "not recorded"}.get(reading.kind)
    if reading.kind == "input":  # an input reading names who supplied it, as every input does
        illus("input", reading.source)  # refused when it names no one
        head = f"supplied by {reading.source}"
    if head is None:
        illus(reading.kind)  # a kind with no words is refused here as everywhere
    return f" <small>({E(head)}, {E(', '.join(said))})</small>"


def table(head: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{E(h)}</th>" for h in head)
    body = "".join(
        "<tr>"
        + "".join(f'<td data-label="{E(h)}">{c}</td>' for h, c in zip(head, r, strict=True))
        + "</tr>"
        for r in rows
    )
    return f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def wrap(title: str, description: str, path: str, content: str) -> str:
    """The site's layout, filled as the site's build fills it."""
    page = (SITE / "src" / "layout.html").read_text()
    page = (
        page.replace("{{title}}", E(title))
        .replace("{{description}}", E(description))
        .replace("{{path}}", path)
    )
    page = page.replace("{{og_image}}", "").replace("{{og_title}}", E(title))
    page = re.sub(r"\{\{nav_[a-z]+\}\}", "", page)
    return page.replace(
        "{{content}}", "<!-- strategy-content -->" + content
    )  # where the page's own content starts


def _not_strategy(cap_id: str, paths) -> None:
    """A capability's links and hand-offs point at the site's own pages: a strategy page is reached from the routes
    that own its jobs and from the index, never from the register, so one named there refuses the render."""
    named = sorted({p for p in paths if p == "/strategy" or p.startswith("/strategy/")})
    if named:
        raise ValueError(
            f"{cap_id} links or hands off to a strategy page ({', '.join(named)}); point it at a chapter, a note or a "
            "playbook, since a strategy page is reached from the routes and the index"
        )


def handoffs(cap, comp_map: dict, pages: dict[str, str]) -> list[tuple[str, str, str]]:
    """(kind, path, title) for each competency that teaches the capability and each page that serves it; a page that is
    not published refuses the render (A2)."""
    teaches = {c["id"]: c["teaches"] for c in comp_map["competencies"] if c.get("teaches")}
    phaseless = {
        j["id"] for j in comp_map.get("jobs") or [] if not j.get("phase")
    }  # the foundation (check_jobs)
    job = {c["id"]: c.get("job") for c in comp_map["competencies"]}
    _not_strategy(cap.id, cap.links)
    out, missing = [], []
    for cid in cap.taught_by:
        path = teaches.get(cid)
        if path is None or path not in pages:
            missing.append(f"competency {cid}")
            continue
        # a foundation competency is background, never "taught by" (charter section 5.5)
        out.append(("background" if job.get(cid) in phaseless else "taught by", path, pages[path]))
    for path in cap.links:
        if path not in pages:
            missing.append(path)
            continue
        out.append(("serves it", path, pages[path]))
    if missing:
        raise ValueError(f"{cap.id} hands off to what is not published: {', '.join(missing)}")
    return out


COMPANION = "https://github.com/privatecloudarchitect/privatecloudarchitect.com/"


def part_handoffs(cap, pages: dict[str, str]) -> tuple[list[list[str]], list[tuple[str, str]]]:
    """Per establish step and sustain loop: (rows of part, where, what) for what is taught or served, and (category,
    what) for what is not taught yet. A site page must be published; the one place off the site a hand-off may go is
    the public companion repository."""
    _not_strategy(
        cap.id,
        [p for part in [*cap.establish, *cap.sustain] for h in part.handoff or [] for p in h.pages],
    )
    rows, untaught, missing = [], [], []
    for kind_label, parts in (("once", cap.establish), ("each period", cap.sustain)):
        for part in parts:
            text = getattr(part, "step", None) or part.loop
            for h in part.handoff or []:
                if h.kind == "untaught":
                    untaught.append(
                        (h.category, h.what, text)
                    )  # the model holds every untaught part to its category; the part named with it
                    continue
                links = []
                for page in h.pages:
                    if page.startswith("/"):
                        if page not in pages:
                            missing.append(page)
                            continue
                        links.append(f'<a href="{E(page)}">{E(pages[page].split(" · ")[0])}</a>')
                    elif page.startswith(COMPANION):
                        links.append(f'<a href="{E(page)}">the companion</a>')
                    else:
                        missing.append(page)
                rows.append(
                    [
                        f"{E(text)} <small>({E(kind_label)})</small>",
                        f"{E(h.kind)}: " + ", ".join(links),
                        E(h.what),
                    ]
                )
    if missing:
        raise ValueError(f"{cap.id} hands a part to what is not published: {', '.join(missing)}")
    return rows, untaught


def _overrides(rep: dict) -> str:
    """Every override the estate applies, each with its kind and the decision that supplied it, on every page made
    from the portfolio: whatever entry it overrides, the page may show what it changed."""
    if not rep.get("overrides"):
        return ""
    for o in rep["overrides"]:
        if not str(
            o.get("decided_by") or ""
        ).strip():  # refused here as GATE-14 refuses it, never shown blank
            raise ValueError(
                f"the override of {o['entry']} names no decision; name the decision that made it"
            )
    return (
        "<p>This estate overrides the policy: "
        + "; ".join(
            f"{E(words(o['entry']))}{illus(o['kind'], o['decided_by'])}"
            + ("" if o["kind"] == "input" else f" <small>(decided by {E(o['decided_by'])})</small>")
            for o in rep["overrides"]
        )
        + ".</p>"
    )


def _status_words(status: str) -> str:
    """A method's status as a reader says it: a shadow version is "in shadow", and every other status, a member added to
    `method_status` among them, is its name in words, so adding a status stays a data change (charter section 5.12)."""
    return "in shadow" if status == "shadow" else words(status).replace("_", " ")


def _used(rep: dict, view: str, extra: dict | None = None) -> dict:
    """The report's provenance with the methods this view's figures came from, and no other (a measure's added)."""
    p = rep["provenance"]
    methods = {m: v for m, v in p["methods"].items() if m in rep["view_methods"][view]}
    return dict(p, methods=methods | (extra or {}))


def _provenance(p: dict, published: bool = False) -> str:
    """Every provenance field the output carries, in words and, for the gates, as data (GATE-14)."""
    methods = (
        "; ".join(
            f"{m} version {v['version']} ({_status_words(v['status'])})"
            for m, v in sorted(p["methods"].items())
        )
        or "no policy method (a view of the register alone)"
    )
    schemas = ", ".join(f"{k} {v}" for k, v in sorted(p["schemas"].items()))
    contracts = ", ".join(str(c) for c in p.get("contracts") or []) or "none read by this view"
    data = E(
        json.dumps({k: v for k, v in p.items() if k != "generated_at"}, sort_keys=True), quote=True
    )
    return (
        f'<p class="prov" data-prov="{data}">Generated {E(p.get("generated_at", ""))} by {E(methods)}, under '
        f"policy version {p['policy_version']}; schemas {E(schemas)}; drift-read contract {E(contracts)}; inputs "
        f"{E(p['input_digest'])}, overrides {E(p['overrides_digest'])}."
        + ("" if published else " Rendered for review, not published.")
        + "</p>"
    )


def strategy_page(
    cap_id: str,
    rep: dict,
    register,
    portfolio,
    measure: dict | None,
    drift_lines: list[dict],
    comp_map: dict,
    pages: dict[str, str],
    served=None,
) -> str:
    """A capability's page. A served one (`served`, its slice) says "not yet published" where the projection withheld a
    node (40-BREADTH.md step 2, S3)."""
    cap = next(c for c in register.capabilities if c.id == cap_id)
    pc = next((c for c in portfolio.capabilities if c.id == cap_id), None)
    if (
        pc is None or not pc.state
    ):  # refused by name, never a bare KeyError, and never a page of guesses
        raise ValueError(
            f"the portfolio records no state for {cap_id}; record its state, each step not recorded, to render "
            "its page"
        )
    st = pc.state[0]
    g = next(x for x in rep["grades"] if x["capability"] == cap_id and x["scope"] == st.scope)
    roles = {r.id: r.name for r in register.roles}
    parts = [
        STYLE,
        '<div class="esl" data-source="register portfolio" data-view="capability">',
        f'<span class="eyebrow">{E(NAME)}, capability</span>',
        f"<h1>{E(cap.outcome)}</h1>",
    ]
    lead = next((v for v in cap.value if v.stages), cap.value[0])
    parts.append(
        f'<p class="dek">{E(lead.outcome)}: {E(lead.measure)}. It serves {E(lead.serves)}, and '
        f"the {E(role_text(roles[cap.accountable]))} owns it.</p>"
    )
    if cap.practice:
        # the layer's own practice is keyed to the outside model's capability it implements, never to a handbook
        # job, and stays wired to the handbook through the capability whose output it reads (DEC-18)
        parts.append(
            f"<p>The strategy layer's own practice, keyed to the outside model's <b>{E(cap.practice)}</b>: it names "
            "no handbook job, and reads the output of the capabilities its hand-offs below name.</p>"
        )
    standing_at = len(
        parts
    )  # the standing line goes here once the figures it states are computed (step 10)
    lead_now = lead_target = "not recorded"
    lead_reading = lead_tgt = None
    value_verdicts: list[
        bool | None
    ] = []  # per value: within its target, past it, or None where either is missing

    from generator.core import newest_index

    parts.append("<h2>What it is worth</h2>")
    rows = []
    for v in cap.value:
        # a value's newest reading, by its day (of two on one day, the later in the list), as every reader picks it
        mine = [r for r in pc.readings if r.value == v.id]
        k = newest_index(mine, day=lambda r: r.read_at)
        reading = mine[k] if k is not None else None
        now = (
            fig(
                None,
                None,
                reading.kind,
                reading.source,
                node=("capabilities", cap_id, "readings", reading.id),
                text=reading.reading,
                label=graded(reading),
            )
            if reading
            else NOT_YET
            if served
            and any(
                a[:3] == ("capabilities", cap_id, "readings") and w.get("value") == v.id
                for a, w in served.withheld.items()
            )
            else "not recorded"
        )
        tgt = pc.targets.get(v.id)
        target = (
            fig(
                tgt.value,
                v.unit,
                tgt.kind,
                tgt.source,
                node=("capabilities", cap_id, "targets", v.id),
                tail=f", {E(tgt.target_kind)}, over {E(per(tgt.window))}",
            )
            if tgt
            else NOT_YET
            if _held(served, ("capabilities", cap_id, "targets", v.id))
            else "not recorded"
        )
        got = _first_number(reading.reading) if reading else None
        try:
            want = float(tgt.value) if tgt is not None and tgt.value is not None else None
        except (TypeError, ValueError):
            want = None
        value_verdicts.append(
            None
            if got is None or want is None
            else (got <= want if v.direction == "lower" else got >= want)
        )
        if v is lead:
            lead_reading, lead_tgt, lead_target = reading, tgt, target
            lead_now = (  # the reading's first clause, with its kind and grade, never the whole figure text
                fig(
                    None,
                    v.unit,
                    reading.kind,
                    reading.source,
                    node=("capabilities", cap_id, "readings", reading.id),
                    text=_brief(reading.reading),
                    label=graded(reading),
                )
                if reading
                else now
            )
        rows.append([E(v.outcome), E(v.unit), target, now])
    parts.append(table(["Value", "Unit", "Target", f"On the {E(rep['estate'])} estate"], rows))
    # every value defined, with the way that is better; a measure note where the register adds one (step 10's review:
    # before this only the lead value was defined, in the dek)
    for v in cap.value:
        note = f"; {E(v.measure_note)}" if v.measure_note else ""
        parts.append(
            f"<p><small>{E(v.outcome)}: {E(v.measure)} ({E(v.direction)} is better{note}).</small></p>"
        )
    if measure:
        b = measure["total_days"] or {}
        status = _status_words(next(iter(measure["provenance"]["methods"].values()))["status"])
        closed = (
            f"graded {E(str(measure['grade']))}, at most {fig(b.get('upper'), 'days', 'measured', label=False)} "
            "from its publication on "
            f"{E(measure['t0'])}"
            if measure.get("grade") and b.get("upper") is not None
            else f"open since its publication on {E(measure['t0'])}, so neither graded nor bounded yet"
        )
        parts.append(
            f'<p>The latest reading of {E(measure["advisory"])}: <span class="state">{E(measure["state"])}</span>, '
            f"measured on {E(measure['provenance']['generated_at'][:10])} and {closed}; the method that reads it is "
            f"{E(status)}.</p>"
        )

    parts.append("<h2>What it costs once</h2>")
    rows = []
    for s in cap.establish:
        done = st.steps.get(s.id)
        inv = pc.investment.get(s.id)
        cost = (
            fig(
                inv.value,
                s.investment_unit,
                inv.kind,
                inv.source,
                node=("capabilities", cap_id, "investment", s.id),
            )
            if inv and inv.value is not None
            else NOT_YET
            if _held(served, ("capabilities", cap_id, "investment", s.id))
            else "not recorded"
        )
        # a step the portfolio's state leaves out is not recorded, and says so; one the projection withheld, not yet
        # published
        state = (
            NOT_YET
            if _held(served, ("capabilities", cap_id, "state", st.scope, "steps", s.id))
            else ("done" if done and done.done else "open")
            + (illus(done.kind, done.source) if done else illus("not_recorded"))
        )
        rows.append([E(s.step), state, cost])
    parts.append(table(["Establish step", f"On the {E(rep['estate'])} estate", "Investment"], rows))

    parts.append("<h2>What it costs each period</h2>")
    rows = []
    for loop in cap.sustain:
        eff = pc.effort.get(loop.id)
        cost = (
            fig(
                eff.value,
                loop.effort_unit,
                eff.kind,
                eff.source,
                node=("capabilities", cap_id, "effort", loop.id),
            )
            if eff and eff.value is not None
            else NOT_YET
            if _held(served, ("capabilities", cap_id, "effort", loop.id))
            else "not recorded"
        )
        rows.append(
            [
                E(loop.loop),
                E(every(loop.cadence)),
                "the " + E(role_text(roles.get(loop.runner, loop.runner))),
                E(loop.toil),
                cost,
            ]
        )
    parts.append(table(["Sustain loop", "Every", "Run by", "Kind", "Effort"], rows))
    parts.insert(
        standing_at,
        _standing(
            cap,
            cap_id,
            rep,
            register,
            portfolio,
            g,
            lead,
            lead_now,
            lead_target,
            lead_reading,
            lead_tgt,
            served,
            values=value_verdicts,
            drift_lines=drift_lines,
        ),
    )

    parts.append(f"<h2>Who owns it, and how far the {E(rep['estate'])} estate has got</h2>")
    assigned = [
        a for a in portfolio.assignments if a.role == cap.accountable and a.scope == st.scope
    ]
    dept = ", ".join(
        fig(
            None,
            None,
            a.kind,
            a.source,
            node=("assignments", f"{a.role}:{a.scope}"),
            text=f"the {a.department} department",
        )
        for a in assigned
    ) or (
        f"a department {NOT_YET}"
        if _held(served, ("assignments", f"{cap.accountable}:{st.scope}"))
        else f"no department{illus('not_recorded')}"
    )
    mine = [x for x in drift_lines if x["capability"] == cap_id]
    judged = [x for x in mine if x["result"] in JUDGED]
    in_sync = sum(1 for x in judged if x["result"] == "in_sync")
    parts.append(
        f'<p>The <a href="/strategy/roles/{E(cap.accountable)}">{E(role_text(roles[cap.accountable]))}</a>, held by '
        f"{dept}. Each declaration has one writer: "
        + ", ".join(
            f"{_the(E(d.object))}, kept in {system_named(d)} and written by the "
            f"{E(role_text(roles.get(d.writer, d.writer)))}"
            for d in cap.declarations
        )
        + (
            f". The drift read ({_drift_when(judged, cap_id)}{_drift_how(judged)}) finds {count(in_sync)} of "
            f"{count(len(judged))} reads in sync, {_drift_per(judged, cap_id)}{_drifted_words(judged)}{_unread(mine)}.</p>"
            if judged
            else f". No declaration of it is read yet{_unread(mine)}.</p>"
            if mine
            else ". No drift read is recorded for it yet.</p>"
        )
    )
    evidence = (
        f"graded on the evidence of the recorded steps{illus(g['basis'], g.get('basis_source'))}"
        f"{_unrecorded(cap, st, served)}"
        if g["steps_recorded"]
        else f"none of them recorded{illus('not_recorded')}"
    )
    parts.append(
        f'<p>Adoption: <span class="state">{E(words(g["level"]))}</span> ({E(LEVEL_WORDS.get(g["ordinal"], ""))}), '
        f"{count(g['steps_done'])} of {count(g['steps'])} establish steps done, {evidence}. The bar, "
        f"&ldquo;world-class&rdquo;, is the level {E(words(g['world_class']))} "
        f"({E(LEVEL_WORDS.get(g['world_class_ordinal'], ''))}), the {ORDINALS.get(g['world_class_ordinal'], '')} of "
        f"{count(g['levels'])} levels: {E(', '.join(words(x) for x in g.get('ladder', [])))}.</p>"
    )

    parts.append("<h2>Where each part is taught</h2>")
    rows, untaught = part_handoffs(cap, pages)
    if rows:
        parts.append(table(["Part", "Where", "What it gives"], rows))
    if untaught:
        by_category: dict[str, list[tuple[str, str]]] = {}
        for c, w, part in untaught:
            by_category.setdefault(c, []).append((part, w))
        parts.append(
            "<p>Not taught on the site yet, each a candidate for a chapter:</p><ul>"
            + "".join(  # each part on its own line: a part's text is sentence-case and never opens mid-sentence
                f"<li><b>{E(c)}</b>"
                + "".join(f"<br>{E(part)} ({E(w)})" for part, w in items)
                + "</li>"
                for c, items in by_category.items()
            )
            + "</ul>"
        )
    whole = handoffs(cap, comp_map, pages)
    if whole:
        parts.append(
            "<p>The capability as a whole: "
            + ", ".join(
                f'<a href="{E(path)}">{E(title.split(" · ")[0])}</a> ({E(kind)})'
                for kind, path, title in whole
            )
            + ".</p>"
        )
    elif cap.practice:
        parts.append(
            "<p>The capability as a whole is the strategy layer's own practice: no chapter teaches it, and these pages "
            "serve it, by the layer's decision to place them on the site.</p>"
        )
    else:  # a capability whose own territory is untaught: its untaught entries say where it was sent
        parts.append("<p>The capability as a whole is taught by no published chapter yet.</p>")
    parts.append(
        f'<p>Across the portfolio: <a href="/strategy/board">where the {E(rep["estate"])} estate invests next</a>; '
        '<a href="/strategy/costs-and-value">what each capability returns, and what it costs once and to keep</a>; '
        '<a href="/strategy">every capability and role brief</a>.</p>'
    )
    parts.append(_overrides(rep))
    parts.append(
        _provenance(
            _used(rep, "capability", (measure or {}).get("provenance", {}).get("methods")),
            f"/strategy/{cap_id}" in pages,
        )
    )
    parts.append("</div>")
    return "".join(parts)


def _unrecorded(cap, st, served=None) -> str:
    """How many of a capability's establish steps no record holds, said beside the grade that rests on the others; on
    a served page, a step the projection withheld is counted apart, as not yet published."""
    held = {
        s.id
        for s in cap.establish
        if _held(served, ("capabilities", cap.id, "state", st.scope, "steps", s.id))
    }
    n = sum(
        1
        for s in cap.establish
        if s.id not in held
        and (st.steps.get(s.id) is None or st.steps[s.id].kind == "not_recorded")
    )
    return (f", {count(n)} not recorded" if n else "") + (
        f", {count(len(held))} {NOT_YET}" if held else ""
    )


# the results that judged a declaration; a not_covered line judged nothing and is stated apart, never counted as a read
JUDGED = ("in_sync", "drifted", "check_failed")


def _unread(lines: list[dict]) -> str:
    """The declarations no companion reads, each with its reason as the line's check gives it ("not read: <why>")."""
    whys = []
    for x in lines:
        if x["result"] == "not_covered":
            why = x["source"]["check"].removeprefix("not read: ")
            if why not in whys:
                whys.append(why)
    if not whys:
        return ""
    n = sum(1 for x in lines if x["result"] == "not_covered")
    return f"; {count(n)} {'declaration is' if n == 1 else 'declarations are'} not read: {E('; '.join(whys))}"


def _first_number(text: str | None) -> float | None:
    """The first figure a reading states, its dates set aside (a reading may open with the day it was read)."""
    if not text:
        return None
    m = re.search(r"(?<![\d.-])(-?\d+(?:\.\d+)?)", re.sub(r"\d{4}-\d{2}-\d{2}", " ", text))
    return float(m.group(1)) if m else None


def _verdict(got: float, want: float, direction: str) -> str:
    """A reading against its target in the direction's own words."""
    if direction == "lower":
        return " (within the target)" if got <= want else " (past the target)"
    return " (at or above the target)" if got >= want else " (below the target)"


def _placement(rep: dict, iid: str, register) -> str:
    """Where the board puts an initiative: funded in a period, ranked unfunded, not ranked (what it waits on), or
    not on the board."""
    board = rep.get("board") or {}
    for row in (board.get("capacity") or {}).get("funded") or []:
        if row.get("id") == iid:
            return f"funded {E(str(row.get('period') or 'this period'))}"
    if any(row.get("id") == iid for row in board.get("ranked") or []):
        return "ranked, unfunded this period"
    for row in board.get("unranked") or []:
        if row.get("id") == iid:
            waits = [
                E(named(register, x["capability"]))
                for x in row.get("blocked_by") or []
                if x.get("capability")
            ]
            return "not ranked, waits on " + ", ".join(waits) if waits else "not ranked"
    return "not on the board"


def _standing(
    cap,
    cap_id,
    rep,
    register,
    portfolio,
    g,
    lead,
    lead_now,
    lead_target,
    reading,
    tgt,
    served,
    values=(),
    drift_lines=(),
) -> str:
    """The verdict in the skim (step 10's review, the decision-maker's lens): where the estate stands against the bar,
    the lead value against its target, what serves the capability and with what commitment, what it waits on, and
    what it costs once and each period; every figure one the body shows, in the body's own words."""
    verdict = ""
    got, want = _first_number(reading.reading if reading else None), None
    try:
        want = float(tgt.value) if tgt is not None and tgt.value is not None else None
    except (TypeError, ValueError):
        want = None
    if got is not None and want is not None:
        verdict = _verdict(got, want, lead.direction)
    serving = [
        d for d in register.initiatives if f"capability:{cap_id}" in [*d.establishes, *d.improves]
    ]
    plans = {p.id: p for p in portfolio.initiatives}
    if serving:
        said = []
        for d in serving:
            plan = plans.get(d.id)
            state = E(words(plan.status.value)) if plan else "no plan recorded"
            if plan and plan.commitment:
                state += f", {E(words(plan.commitment))}"
            said.append(f"{E(named(register, d.id))} ({state}; {_placement(rep, d.id, register)})")
        initiatives = (
            f"Served by {_plural(len(serving), 'initiative', 'initiatives')}: {'; '.join(said)}."
        )
    else:
        initiatives = "No initiative serves it yet."
    ordinals = {x["capability"]: x["ordinal"] for x in rep["grades"]}
    required = sorted(
        {
            x.split(":", 1)[1]
            for s in cap.establish
            for x in s.requires
            if x.startswith("capability:")
        }
    )
    waits = []
    for c in required:
        if served is not None and c in served.not_yet_published:
            waits.append(f"{E(named(register, c))} ({NOT_YET})")
        elif ordinals.get(c, 0) == 0:  # the lowest level, or no grade recorded at all
            waits.append(f"{E(named(register, c))} (not established)")
    waiting = f" Waits on {', '.join(waits)}." if waits else ""
    row = next((x for x in rep.get("costs_and_value") or [] if x["capability"] == cap_id), None)
    if row:
        held_once = sum(
            1
            for x in row["not_recorded_once"]
            if _held(served, ("capabilities", cap_id, "investment", x))
        )
        held_keep = sum(
            1
            for x in row["not_recorded_keep"]
            if _held(served, ("capabilities", cap_id, "effort", x))
        )
        costs = (
            f" Costs {_totals_words(row['once_total'], held_once)} once and "
            f"{_totals_words(row['keep_total'], held_keep)} each period."
        )
    else:
        costs = ""
    judged = [x for x in drift_lines if x.get("capability") == cap_id and x.get("result") in JUDGED]
    if judged:
        in_sync = sum(1 for x in judged if x["result"] == "in_sync")
        drift = f" Drift read: {count(in_sync)} of {count(len(judged))} reads in sync."
    else:
        drift = " No drift read recorded yet."
    scored = [v for v in values if v is not None]
    values_said = (
        f" Of {_plural(len(scored), 'value', 'values')} with a reading and a target, "
        f"{count(sum(1 for v in scored if v))} within and {count(sum(1 for v in scored if not v))} past."
        if scored
        else ""
    )
    return (
        f"<p><b>Standing on the {E(rep['estate'])} estate.</b> Adoption {E(words(g['level']))}, "
        f"{count(g['steps_done'])} of {count(g['steps'])} establish steps done, against the bar "
        f"{E(words(g['world_class']))}. {E(lead.outcome)}: {lead_now} against a target of {lead_target}{verdict}."
        f"{values_said}{drift} {initiatives}{waiting}{costs}</p>"
    )


def _drift_per(lines: list[dict], cap_id: str) -> str:
    """What one drift-read line covers, from its scope: one per cluster, say, as the adapter scopes it."""
    kinds = {x["scope"].split(":", 1)[0] for x in lines if x["capability"] == cap_id}
    return f"one per {E(kinds.pop())}" if len(kinds) == 1 else "one per scope"


def _drift_when(lines: list[dict], cap_id: str) -> str:
    """A drift read's kind, in words, and the days its stored results were checked, as the record holds them."""
    mine = [x for x in lines if x["capability"] == cap_id]
    days = sorted({x["checked_at"][:10] for x in mine if x.get("checked_at")})
    modes = ", ".join(MODE_WORDS.get(m, m) for m in sorted({x["mode"] for x in mine}))
    if not days:
        return f"{modes}; no stored check time"
    span_ = days[0] if len(days) == 1 else f"{days[0]} to {days[-1]}"
    return f"{modes}; stored results checked {span_}"


def _placeholders_as_words(text: str) -> str:
    """A record's scrubbed placeholder ({{vcenter-1}}) as a page prints it: one of its kind, never the token."""
    return re.sub(
        r"\{\{([a-z][a-z-]*?)-\d+\}\}", lambda m: f"one {m.group(1).replace('-', ' ')}", text
    )


def _drift_how(lines: list[dict]) -> str:
    """Which companion made the read, what its check compares and which record holds it, from the lines' sources:
    the instrument named on the page beside its finding (step 10's review)."""
    seen: list[tuple] = []
    for x in lines:
        src = x.get("source") or {}
        key = (src.get("companion"), src.get("check"), src.get("record"))
        if any(key) and key not in seen:
            seen.append(key)
    said = []
    for companion, check, record in seen:
        bits = []
        if companion:
            bits.append(f"by the {E(str(companion).rsplit('/', 1)[-1])} companion")
        if check:
            bits.append(f"comparing {E(_placeholders_as_words(str(check)))}")
        if record:
            bits.append(f"from its record {E(str(record).rsplit('/', 1)[-1])}")
        said.append(", ".join(bits))
    return f"; {'; '.join(said)}" if said else ""


def _drifted_words(lines: list[dict]) -> str:
    """The reads that drifted, each by the declaration it read and the kind of scope it read it on; never a name."""
    drifted: list[str] = []
    unjudged: list[str] = []
    for x in lines:
        obj = (x.get("declaration") or {}).get("object") or "a declaration"
        kind = str(x.get("scope", "")).split(":", 1)[0] or "scope"
        w = f"{E(str(obj))} on one {E(kind)}"
        if x.get("result") == "drifted" and w not in drifted:
            drifted.append(w)
        elif x.get("result") not in ("in_sync", "drifted") and w not in unjudged:
            unjudged.append(f"{w} ({E(str(x.get('result', '')).replace('_', ' '))})")
    out = ""
    if drifted:
        out += f"; drifted: {', '.join(drifted)}"
    if unjudged:
        out += f"; not judged: {', '.join(unjudged)}"
    return out


def _effort_head(rows: list[dict]) -> str:
    """The added-effort column's head, in the unit the core reports it in."""
    units = {r.get("added_effort_unit") for r in rows if r.get("added_effort_unit")}
    return f"Added effort, {units.pop()}" if len(units) == 1 else "Added effort"


def _unit_head(rows: list[dict]) -> str:
    """A duration column's head, in the unit the portfolio states its durations in."""
    units = {r["duration_unit"] for r in rows}
    return f"Duration, {units.pop()}" if len(units) == 1 else "Duration"


def _effort_held(served, initiative_id: str) -> bool:
    """Whether a part of an initiative's added effort (its own figure, or a loop's effort it adds) was withheld by the
    served projection: read through core's address helper, which selects the parts the method reads."""
    if served is None:
        return False
    from generator.core import added_effort_addresses

    plans = {p.id for p in served.portfolio.initiatives}
    if initiative_id not in plans:
        return False
    return any(
        a in served.withheld
        for a in added_effort_addresses(served.register, served.portfolio, initiative_id)
    )


def _off_board_words(register, why: dict) -> str:
    """Why an initiative's score is not shown on a served board, in words (served.project's `off_board`)."""
    said = {
        "cost_through": "its cost runs through {cap}, which is " + NOT_YET,
        "cost_of_delay": "its cost of delay is " + NOT_YET,
        "rate": "the conversion rate it is costed through is " + NOT_YET,
        "duration": "its duration is " + NOT_YET,
        "added_effort": "its added effort names a loop of {cap}, which is " + NOT_YET,
    }[why["why"]]
    return said.format(cap=E(named(register, why["capability"]))) if why["capability"] else said


def board_page(
    rep: dict,
    register,
    labels: dict[str, str],
    pages: dict[str, str] | None = None,
    rate_units: dict[str, str] | None = None,
    served=None,
) -> str:
    """The board. A served one (`served`, its slice) names a capability not yet published where it blocks or is
    established, lists each initiative off the board after the rank, and labels the rank and the capacity line partial
    while one is (S2, S3)."""
    from generator.core import (
        newest_assessments,
    )  # the assessments the readiness rules judge, and no other

    b = rep["board"]
    names = {i.id: i.summary for i in register.initiatives}
    parts = [
        STYLE,
        '<div class="esl" data-source="register portfolio" data-view="board">',
        f'<span class="eyebrow">{E(NAME)}, {E(rep["estate"])} portfolio</span>',
        f"<h1>Where the {E(rep['estate'])} estate invests next</h1>",
        '<p class="dek">Each initiative ranked by what a month of waiting costs over the time it takes, an enabler by '
        "the chain it unblocks, funded within the constrained role's capacity. Every input marked illustrative was "
        "supplied for the worked example, not measured.</p>",
        "<h2>The rank</h2>",
    ]
    rows = [
        [
            fig(
                n, None, b["derived"]["kind"], b["derived"]["source"]
            ),  # a place rests on every score considered
            f"{E(named(register, r['id']))}<br><small>{E(names.get(r['id'], ''))}</small>",
            fig(r["score"], None, r["score_kind"], r["score_source"]),
            # the chain is the best prefix by cost of delay over duration among every initiative the rank considers, so
            # it rests on what a place in the rank rests on
            fig(
                None,
                None,
                b["derived"]["kind"],
                b["derived"]["source"],
                text=" then ".join(named(register, x) for x in r["chain"]),
            ),
            fig(r["duration"], None, r["duration_kind"], r["duration_source"]),
            (NOT_YET if _effort_held(served, r["id"]) else "not recorded")
            if r["added_effort_per_month"] is None
            else fig(
                r["added_effort_per_month"],
                None,
                r["added_effort_kind"],
                r["added_effort_source"],
                tail=f" <small>(partial: {NOT_YET} in part)</small>"
                if _effort_held(served, r["id"])
                else "",
            ),
        ]
        for n, r in enumerate(b["ranked"], 1)
    ]
    parts.append(
        table(
            [
                "Rank",
                "Initiative",
                "Score",
                "Chain",
                _unit_head(b["ranked"]),
                _effort_head(b["ranked"]),
            ],
            rows,
        )
    )
    if b["unranked"]:
        parts.append(
            "<p>Not ranked until its prerequisites are established: "
            + "; ".join(
                f"{E(named(register, u['id']))}, waiting on "
                + ", ".join(
                    f"{E(named(register, x['capability']))} ({NOT_YET})"
                    if served and x["capability"] in served.not_yet_published
                    else f"{E(named(register, x['capability']))}{illus(x['kind'], x['source'])}"
                    + (
                        f" <small>(partial: a step {NOT_YET})</small>"
                        if served
                        and any(
                            a[:2] == ("capabilities", x["capability"]) and a[2:3] == ("state",)
                            for a in served.withheld
                        )
                        else ""
                    )
                    for x in u["blocked_by"]
                )
                for u in b["unranked"]
            )
            + ".</p>"
        )
    off = served.off_board if served else {}
    if off:  # each scored without what is not yet published, so the rank above is partial (S2)
        parts.append(
            "<p><small>The rank is partial: "
            + "; ".join(
                f"{E(named(register, iid))}'s score is not shown: "
                + _off_board_words(register, why)
                for iid, why in sorted(off.items())
            )
            + ".</small></p>"
        )
    c = b["capacity"]
    parts.append(
        "<h2>The capacity line</h2>"
        + ("<p><small>Partial, as the rank is.</small></p>" if off else "")
    )
    parts.append(
        table(
            ["Item", _unit_head(c["funded"]), "Cumulative", "Funded"],
            [
                [
                    E(named(register, f["id"])),
                    fig(f["duration"], None, f["duration_kind"], f["duration_source"]),
                    fig(f["cumulative"], None, f["cumulative_kind"], f["cumulative_source"]),
                    f"{E(f['period'])}{illus(f['period_kind'], f['period_source'])}",
                ]
                for f in c["funded"]
            ],
        )
    )
    role_name = next((r.name for r in register.roles if r.id == c["role"]), c["role"])
    parts.append(
        f"<p>The {E(role_text(role_name))} gives "
        + fig(c["per_period"], c["unit"], c["kind"], c["source"], node=("capacity", c["role"]))
        + f", a period being {E(span(c['period']))}.</p>"
    )
    s = b["sensitivity"]
    parts.append("<h2>Where the rank turns</h2>")
    rows = [
        [
            E(value_name(register, m))
            + (
                f"<br><small>in {E(rate_units[m])}</small>"
                if rate_units and m in rate_units
                else ""
            ),
            fig(
                x["rate"],
                None,
                x["kind"],
                x["source"],
                node=("conversion_rates", m),
                text=f"{x['rate']:g} ({x['low']:g} to {x['high']:g})",
            ),
            fig(
                x["top_changes_below"],
                None,
                b["derived"]["kind"],
                b["derived"]["source"],
                text=None
                if x["top_changes_below"]
                else f"none, down to {x['searched']['down_to']:g}",
            ),
            fig(
                x["top_changes_above"],
                None,
                b["derived"]["kind"],
                b["derived"]["source"],
                text=None if x["top_changes_above"] else f"none, up to {x['searched']['up_to']:g}",
            ),
        ]
        for m, x in s["crossings"].items()
    ]
    parts.append(
        table(["Conversion rate", "Rate (range)", "Top changes below", "Top changes above"], rows)
    )
    joints = [j for j in s["joint_extremes"] if j["top"] != s["top"]]
    if joints:
        parts.append(
            "<p>At the joint extremes the top changes: "
            + "; ".join(
                f"{E(named(register, j['top']))} at "
                + fig(j["score"], None, b["derived"]["kind"], b["derived"]["source"])
                + ", with the conversion rates at "
                + " and ".join(
                    fig(
                        v,
                        None,
                        s["crossings"][k]["kind"],
                        s["crossings"][k]["source"],
                        node=("conversion_rates", k),
                        text=f"{v:g}"
                        + (f" {rate_units[k]}" if rate_units and k in rate_units else ""),
                    )
                    + f" ({E(inline(value_name(register, k)))})"
                    for k, v in j["rates"].items()
                )
                for j in joints
            )
            + ".</p>"
        )
    parts.append("<h2>The planning tiers</h2>")
    parts.append(
        table(
            ["Initiative", "Full value in", "Tier", "First value in", "Review by", "Confidence"],
            [
                [
                    E(named(register, p["initiative"])),
                    fig(None, None, p["kind"], p["source"], text=span(p["full_value_in"])),
                    E(labels[p["tier"]]),
                    fig(None, None, p["kind"], p["source"], text=span(p["first_value_in"])),
                    E(p["review_by"]),
                    E(p["confidence"]),
                ]
                for p in newest_assessments(rep["planning"])
            ],
        )
    )
    if b["illustrative_inputs"]:
        parts.append(
            '<h2>Illustrative inputs</h2><p class="illus-list">'
            + "; ".join(E(x) for x in b["illustrative_inputs"])
            + ".</p>"
        )
    parts.append(_overrides(rep))
    if b["unconverted"]:
        parts.append(
            "<p>Shown beside the rank, never weighted into it:</p><ul>"
            + "".join(
                # a typed item (schema 3, the only form from schema 4) says the kind of the decision to show it
                # beside the rank
                f"<li>{E(value_name(register, x['measure']))}{illus(x['kind'], x.get('source'))}</li>"
                for x in b["unconverted"]
            )
            + "</ul>"
        )
    parts.append(_provenance(_used(rep, "board"), "/strategy/board" in (pages or {})))
    parts.append("</div>")
    return "".join(parts)


def _totals_words(totals: list[dict], held: int = 0) -> str:
    """Totals per unit, each with its label; on a served page, a total with a part the projection withheld is labelled
    partial (S2), never shown as whole."""
    partial = f" <small>(partial: {count(held)} {NOT_YET})</small>" if held else ""
    return "; ".join(
        fig(t["value"], t["unit"], t["kind"], t["source"], tail=partial) for t in totals
    ) or ("not recorded" if not held else NOT_YET)


def costs_page(rep: dict, register, pages: dict[str, str], served=None) -> str:
    """V-03's view: each capability's one-time investment set against its recurring effort and what it returns. A served
    one (`served`, its slice) lists a withheld part apart and labels each total it misses partial (S2, S3)."""
    roles = {r.id: r.name for r in register.roles}
    caps = {c.id: c for c in register.capabilities}
    parts = [
        STYLE,
        '<div class="esl" data-source="register portfolio" data-view="costs">',
        f'<span class="eyebrow">{E(NAME)}, {E(rep["estate"])} portfolio</span>',
        "<h1>What each capability returns, and what it costs once and to keep</h1>",
        '<p class="dek">Each capability\'s values say what it returns, and the cost of delay what waiting loses; '
        "one-time work brings it into being, and recurring work keeps it. Each is in its own unit, summed only within a "
        "unit. Every figure marked illustrative was supplied for the worked example, not measured.</p>",
    ]
    if served is not None:
        parts.append(
            "<p>This published view holds the capabilities published so far; the register's other capabilities "
            "join it as each is published, and the review view holds them all.</p>"
        )
    rows = []
    for c in rep["costs_and_value"]:
        cap = caps[c["capability"]]
        held_once = [
            x
            for x in c["not_recorded_once"]
            if _held(served, ("capabilities", cap.id, "investment", x))
        ]
        held_keep = [
            x
            for x in c["not_recorded_keep"]
            if _held(served, ("capabilities", cap.id, "effort", x))
        ]
        once = _totals_words(c["once_total"], len(held_once))
        if c["once_adjusted"]:
            once += (
                "<br><small>"
                + "; ".join(
                    fig(
                        t["value"],
                        t["unit"],
                        t["kind"],
                        t["source"],
                        text=f"{amount(t['value'], t['unit'])} after the {t['factor']:g} estimate adjustment",
                        tail=f" <small>(partial: {count(len(held_once))} {NOT_YET})</small>"
                        if held_once
                        else "",
                    )
                    for t in c["once_adjusted"]
                )
                + "</small>"
            )
        if c["not_recorded_once"]:
            once += "".join(  # a part a line, so no part's own punctuation reads as a separator
                f"<br><small>{NOT_YET if x in held_once else 'not recorded'} for "
                f"{E(inline(part_name(cap, x)))}</small>"
                for x in c["not_recorded_once"]
            )
        returns = "<br>".join(
            f"{E(value_name(register, r['value']))}: "
            + (
                fig(
                    r["target"],
                    r["unit"],
                    r["kind"],
                    r["source"],
                    node=("capabilities", c["capability"], "targets", r["value"]),
                    tail=f", {E(r['target_kind'])}, over {E(per(r['window']))}",
                )
                if r["target"] is not None
                else f"target {NOT_YET}"
                if _held(served, ("capabilities", c["capability"], "targets", r["value"]))
                else "target not recorded"
            )
            for r in c["returns"]
        )
        waiting = (
            "<br>".join(
                f"{E(named(register, w['initiative']))}: "
                + fig(
                    w["delta"],
                    w["unit"],
                    w["kind"],
                    w["source"],
                    node=("initiatives", w["initiative"], "cost_of_delay"),
                    text=f"{amount(w['delta'], w['unit'])} less",
                )
                for w in c["waiting"]
            )
            # an initiative costed through this capability's value, its cost of delay withheld (S3)
            + "".join(
                f"<br>{E(named(register, d.id))}: {NOT_YET}"
                for d in register.initiatives
                if d.cost_of_delay_through in {v.id for v in cap.value}
                and _held(served, ("initiatives", d.id, "cost_of_delay"))
            )
        ).removeprefix("<br>") or "not recorded"
        rows.append(
            [
                f'<a href="/strategy/{E(cap.id)}">{E(named(register, cap.id))}</a><br><small>the '
                f"{E(role_text(roles.get(c['accountable'], c['accountable'])))}</small>",
                returns,
                waiting,
                once,
                _totals_words(c["keep_total"], len(held_keep))
                + (
                    "".join(
                        f"<br><small>{NOT_YET if x in held_keep else 'not recorded'} for "
                        f"{E(inline(part_name(cap, x)))}</small>"
                        for x in c["not_recorded_keep"]
                    )
                    if c["not_recorded_keep"]
                    else ""
                ),
            ]
        )
    parts.append(
        table(
            [
                "Capability",
                "Returns (target)",
                "Waiting costs",
                "Costs once",
                "Costs to keep",
            ],
            rows,
        )
    )
    parts.append(_overrides(rep))
    parts.append(_provenance(_used(rep, "costs"), "/strategy/costs-and-value" in pages))
    parts.append("</div>")
    return "".join(parts)


def role_page(brief: dict, register, comp_map: dict, pages: dict[str, str], prov: dict) -> str:
    """A role's public brief (section 6): what the role holds, from the register alone."""
    caps = {c.id: c for c in register.capabilities}
    path = f"/strategy/roles/{brief['role']}"
    parts = [
        STYLE,
        '<div class="esl" data-source="register" data-view="role">',
        f'<span class="eyebrow">{E(NAME)}, role brief</span>',
        f"<h1>{E(brief['name'])}</h1>",
    ]
    held = ("accountable_for", "writes", "runs", "measures", "drift_reads", "sponsors", "reads")
    if brief["owns"]:
        parts.append(f'<p class="dek">It owns {E(brief["owns"])}.</p>')
    elif any(brief[k] for k in held):
        n = {k: len(brief[k]) for k in held}
        n["drift_reads"] = sum(  # a drift read with no companion yet reads nothing
            1 for d in brief["drift_reads"] if not isinstance(d, dict) or d.get("companion")
        )
        said = [  # only what the role holds; the absence of the rest is stated where its section would be
            f"{text} {_plural(n[k], one, many)}"
            for k, text, one, many in (
                ("accountable_for", "accountable for", "capability", "capabilities"),
                ("writes", "writes", "declaration", "declarations"),
                ("runs", "runs", "loop", "loops"),
                ("drift_reads", "reads the drift of", "capability", "capabilities"),
                ("sponsors", "sponsors", "initiative", "initiatives"),
                ("reads", "watches", "source", "sources"),
            )
            if n[k]
        ]
        parts.append(
            f'<p class="dek">{E(said[0][0].upper() + said[0][1:])}'
            + "".join(f"; {E(x)}" for x in said[1:])
            + ".</p>"
        )
    if not any(brief[k] for k in held):
        parts.append(
            "<p>No capability, initiative or watch entry of the register names this role yet; the catalog's "
            "breadth adds them.</p>"
        )
    if brief["accountable_for"]:

        def links(cid: str, which: str) -> str:
            # the same classification as the capability's page: a foundation chapter is background, never taught by
            return ", ".join(
                f'<a href="{E(path)}">{E(title.split(" · ")[0])}</a>'
                for kind, path, title in handoffs(caps[cid], comp_map, pages)
                if kind == which
            )

        parts.append("<h2>Accountable for</h2>")
        parts.append(
            table(
                ["Capability", "Outcome", "Taught by", "Background"],
                [
                    [
                        f'<a href="/strategy/{E(cid)}">{E(named(register, cid))}</a>',
                        E(caps[cid].outcome),
                        links(cid, "taught by") or NOT_TAUGHT,
                        links(cid, "background") or "none",
                    ]
                    for cid in brief["accountable_for"]
                ],
            )
        )
    elif any(brief[k] for k in held if k != "accountable_for"):
        parts.append("<p>Accountable for no capability in this register.</p>")
    if any(e["steps"] for e in brief["establishes"]):
        parts.append("<h2>Establishes</h2>")
        parts.append(
            table(
                ["Capability", "Establish steps"],
                [
                    [
                        f'<a href="/strategy/{E(e["capability"])}">{E(named(register, e["capability"]))}</a>',
                        "<br>".join(  # a step a line, so no step's own punctuation reads as a separator
                            E(s.step) for s in caps[e["capability"]].establish if s.id in e["steps"]
                        ),
                    ]
                    for e in brief["establishes"]
                    if e["steps"]
                ],
            )
        )
    if brief["writes"]:
        parts.append("<h2>Writes</h2><p>")
        parts.append(
            "; ".join(
                f"{_the(E(w['object']))}, kept in "
                + system_named(
                    next(
                        d
                        for d in caps[w["capability"]].declarations
                        if d.system == w["system"] and d.object == w["object"]
                    )
                )
                + f" ({E(named(register, w['capability']))})"
                for w in brief["writes"]
            )
            + ".</p>"
        )
    if brief["runs"]:
        parts.append("<h2>Runs</h2>")
        parts.append(
            table(
                ["Loop", "Every", "Capability"],
                [
                    [
                        E(
                            next(
                                lp.loop
                                for lp in caps[r["capability"]].sustain
                                if lp.id == r["loop"]
                            )
                        ),
                        E(every(r["cadence"])),
                        E(named(register, r["capability"])),
                    ]
                    for r in brief["runs"]
                ],
            )
        )
    if brief["measures"]:
        parts.append(
            "<h2>Owns the targets of</h2><ul>"
            + "".join(
                f"<li>{E(value_name(register, m['value']))}, in {E(m['unit'])}</li>"
                for m in brief["measures"]
            )
            + "</ul>"
        )
    if brief["drift_reads"]:
        parts.append(
            "<h2>Reads its drift with</h2><p>"
            + "; ".join(
                (
                    f"<code>{E(d['companion'])}</code>: {E(d['check'])}"
                    if d["companion"]
                    # a read no companion makes yet (schema 3, charter section 5.6): said, never left blank
                    else f"no companion yet: {E(d.get('not_covered') or '')}"
                )
                + f" ({E(named(register, d['capability']))})"
                for d in brief["drift_reads"]
            )
            + ".</p>"
        )
    if brief["sponsors"]:
        parts.append(
            "<h2>Sponsors</h2><p>"
            + "; ".join(E(named(register, x)) for x in brief["sponsors"])
            + ".</p>"
        )
    if brief["reads"]:
        watch = {w.id: w for w in register.watch_list}
        rnames = {r.id: r.name for r in register.roles}

        def watch_words(wid: str) -> str:
            w = watch.get(wid)
            if w is None:
                return E(named(register, wid))
            return (
                f"{E(named(register, wid))} (every {E(every(w.every))}, read by the "
                f"{E(role_text(rnames.get(w.reader, w.reader)))})"
            )

        parts.append(
            "<h2>Watches</h2><p>" + "; ".join(watch_words(x) for x in brief["reads"]) + ".</p>"
        )
    parts.append(_provenance(prov, path in pages))
    parts.append("</div>")
    return "".join(parts)


def _brief_description(brief: dict) -> str:
    """What a role's brief holds, in its sections' own words, so the description a search result shows names only what
    the page holds."""
    said = [
        verb
        for key, verb in (
            ("accountable_for", "is accountable for"),
            ("establishes", "establishes"),
            ("writes", "writes"),
            ("runs", "runs"),
            ("measures", "owns the targets of"),
            ("drift_reads", "reads its drift with"),
            ("sponsors", "sponsors"),
            ("reads", "watches"),
        )
        if brief[key]
    ]
    if not said:
        return f"{brief['name']}: no capability, initiative or watch entry of the register names this role yet"
    return f"{brief['name']}: what it " + (
        ", ".join(said[:-1]) + " and " + said[-1] if len(said) > 1 else said[0]
    )


def agents_page(register, pages: dict[str, str], prov: dict) -> str:
    """Where agents enter, layer by layer (40-BREADTH.md step 6): the register's `agent_entries` alone, one row per
    (stack, layer) pair in the register's own order (core.agent_rows), the capabilities that carry each pair linked;
    the count of capabilities with an entry is the register's own state (data-plane design)."""
    from generator import core

    rows = core.agent_rows(register)
    carrying = sum(1 for c in register.capabilities if c.agent_entries)
    path = "/strategy/agents"
    parts = [
        STYLE,
        '<div class="esl" data-source="register" data-view="agents">',
        f'<span class="eyebrow">{E(NAME)}, the agentic layer</span>',
        "<h1>Where agents enter, layer by layer</h1>",
        '<p class="dek">In the operating stack an agent helps run the platform; in the product stack the enterprise\'s '
        "own applications embed agents and run as workloads. Each row is what the register says of one layer: where an "
        "agent could act there, and the capabilities that carry the entry.</p>",
        table(
            ["Stack", "Layer", "Where an agent could act", "The capabilities that carry it"],
            [
                [
                    E(r["stack"]),
                    E(r["layer"]),
                    "<br>".join(E(a) for a in r["acts"]),
                    ", ".join(
                        f'<a href="/strategy/{E(cid)}">{E(named(register, cid))}</a>'
                        for cid in r["capabilities"]
                    ),
                ]
                for r in rows
            ],
        ),
        f'<p><span data-plane="design">{count(carrying)}</span> of '
        f'<span data-plane="design">{count(len(register.capabilities))}</span> capabilities carry an entry.</p>',
    ]
    parts.append(_provenance(prov, path in pages))
    parts.append("</div>")
    return "".join(parts)


def drivers_page(register, pages: dict[str, str], prov: dict) -> str:
    """What each driver re-opens (40-BREADTH.md step 6): the register's drivers as they stand, each stress with its
    basis and grade, the initiatives that serve the capability with their newest guidance assessment
    (core.driver_reopens, the register alone), the planned stresses said for what they are, and the page's scope
    stated once with counts of the register's own state (data-plane design). No event, signal or scan is rendered."""
    from generator import core

    reopens = core.driver_reopens(register)
    inits = {d.id: d for d in register.initiatives}
    planned = set(register.planned_capabilities)
    written = {c.id for c in register.capabilities}
    stressed = {s.capability for d in register.drivers for s in d.stresses}
    path = "/strategy/drivers"
    parts = [
        STYLE,
        '<div class="esl" data-source="register" data-view="drivers">',
        f'<span class="eyebrow">{E(NAME)}, the drivers</span>',
        "<h1>What each driver re-opens</h1>",
        '<p class="dek">A driver is a kind of change the register watches for. Each one stresses capabilities, and a '
        "trigger on it re-opens the guidance of the initiatives that establish or improve them.</p>",
        f'<p>The register maps its drivers onto <span data-plane="design">{count(len(stressed))}</span> of '
        f'<span data-plane="design">{count(len(register.capabilities))}</span> written capabilities; a planned '
        "capability is stressed once a batch writes it.</p>",
    ]
    for d in register.drivers:
        parts.append(f"<h2>{E(words(d.id))}</h2>")
        parts.append(f"<p>Triggered by {E(d.trigger_when)}.</p>")
        rows = []
        for row in reopens[d.id]:
            cid = row["capability"]
            bases = [s for s in d.stresses if s.capability == cid]
            if not bases:
                continue  # a planned stress is listed after the table
            served = []
            for i in row["initiatives"]:
                g = inits[i["id"]].guidance[i["guidance"]] if i["guidance"] is not None else None
                served.append(
                    f"{E(words(i['id']))}: "
                    + (
                        f"assessed {E(g.assessed)}, {E(g.half_life)}, {E(g.confidence)}"
                        if g is not None
                        else "no guidance assessment"
                    )
                )
            rows.append(
                [
                    f'<a href="/strategy/{E(cid)}">{E(named(register, cid))}</a>',
                    "<br>".join(
                        f"{E(_public(s.basis))} ({'inferred' if s.inferred else 'stated'})"
                        for s in bases
                    ),
                    "<br>".join(served) if row["served"] else "served by none",
                ]
            )
        parts.append(table(["Stress", "Basis", "Served by"], rows))
        if d.stresses_planned:
            parts.append(
                "<p>Planned stresses: "
                + "; ".join(
                    (E(named(register, c)) if c in written else E(words(c)))
                    + (
                        " (planned)"
                        if c in planned
                        else " (written; its stress awaits the drivers' next ruling)"
                    )
                    for c in d.stresses_planned
                )
                + ".</p>"
            )
    parts.append(
        "<p>The planning assessments a trigger re-opens are each estate's own, in its portfolio.</p>"
    )
    parts.append(_provenance(prov, path in pages))
    parts.append("</div>")
    return "".join(parts)


def index_page(
    prov: dict, register, pages: dict[str, str], review: list[tuple[str, str]] | None = None
) -> str:
    """The strategy layer's index: every capability, the board, the costs and value, every role brief, and the
    register's two views (the agentic page and the drivers' view). With
    `review` (the views the generator emits, as (title, path)), the review index also lists each view the policy does
    not publish and the index does not already link, so a view the policy publishes leaves that list with no code edit
    (40-BREADTH.md step 6); the served index passes nothing and is unchanged."""
    parts = [
        STYLE,
        '<div class="esl" data-source="register" data-view="index">',
        f'<span class="eyebrow">{E(NAME)}</span>',
        "<h1>Capabilities, what they return and cost, and who holds them</h1>",
        '<p class="dek">Each capability is an outcome the platform keeps; its page says what it returns, what it costs once and '
        "to keep, and the chapters that teach it. An estate's portfolio ranks where it invests next.</p>",
        "<h2>Capabilities</h2>",
        table(
            ["Capability", "Outcome"],
            [
                [f'<a href="/strategy/{E(c.id)}">{E(named(register, c.id))}</a>', E(c.outcome)]
                for c in register.capabilities
            ],
        ),
        "<h2>Across the portfolio</h2>",
        '<p><a href="/strategy/board">The board: where to invest next</a>; '
        '<a href="/strategy/costs-and-value">what each capability returns, and what it costs once and to keep</a>.</p>',
        "<h2>Role briefs</h2><ul>",
        "".join(
            f'<li><a href="/strategy/roles/{E(r.id)}">{E(r.name)}</a></li>' for r in register.roles
        ),
        "</ul>",
        # the register's two views (step 6), published with the index since step 12: a link to a page the site does
        # not serve is read as its text by the site's copy (render.site), so the index links them whatever the policy
        "<h2>Across the register</h2>",
        '<p><a href="/strategy/agents">Where agents enter, layer by layer</a>; '
        '<a href="/strategy/drivers">what each driver re-opens</a>.</p>',
    ]
    if review:
        linked = "".join(parts)
        extra = [(t, p) for t, p in review if p not in pages and f'href="{p}"' not in linked]
        if extra:
            parts.append(
                "<h2>Rendered for review, not published</h2><ul>"
                + "".join(f'<li><a href="{E(p)}">{E(t)}</a></li>' for t, p in extra)
                + "</ul>"
            )
    parts.append(_provenance(prov, "/strategy" in pages))
    parts.append("</div>")
    return "".join(parts)


# ── validation, with the site's own probe ───────────────────────────────────────────────────────────────────────────
def validate(docs: dict[str, str], out_dir: Path) -> int:
    sys.path.insert(0, str(SITE))
    import render_validate as rv

    fonts_dir = SITE / "src" / "fonts"
    issues = 0
    for name, page in docs.items():
        page = page.replace('url("/fonts/', f'url("file://{fonts_dir}/').replace(
            'href="/fonts/', f'href="file://{fonts_dir}/'
        )
        page = page.replace("</body>", rv.PROBE + "</body>")
        variants = {
            "light": page.replace("@media (prefers-color-scheme: dark)", "@media not all"),
            "dark": page.replace("@media (prefers-color-scheme: dark)", "@media all"),
        }
        for theme, doc in variants.items():
            for width in (1280, 400):
                f = out_dir / f"{name}.{theme}-{width}.html"
                f.write_text(doc, encoding="utf-8")
                target = f
                if width < rv.MIN_WINDOW:
                    target = out_dir / f"{name}.{theme}-{width}-frame.html"
                    target.write_text(rv.framed(str(f), width), encoding="utf-8")
                base = [
                    rv.CHROME,
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--allow-file-access-from-files",
                    "--virtual-time-budget=8000",
                    f"--window-size={max(width, rv.MIN_WINDOW)},2400",
                ]
                dom = subprocess.run(
                    [*base, "--dump-dom", f"file://{target}"],
                    capture_output=True,
                    text=True,
                    timeout=240,
                ).stdout
                m = re.search(r'<pre id="lint">(.*?)</pre>', dom, re.S)
                res = json.loads(html.unescape(m.group(1))) if m else {"error": "no probe output"}
                subprocess.run(
                    [
                        *base,
                        f"--screenshot={out_dir / f'{name}.{theme}-{width}.png'}",
                        f"file://{target}",
                    ],
                    capture_output=True,
                    timeout=240,
                )
                if "error" in res:
                    issues += 1
                    print(f"!! {name} {theme}-{width}: {res['error']}")
                    continue
                not_loaded = sorted(
                    {fam.strip('"') for fam, _w, st in res["fonts"] if st != "loaded"}
                )
                bad = (
                    res["scrollW"] > res["vw"]
                    or res["vw"] != width
                    or res["node_over"]
                    or not_loaded
                )
                issues += 1 if bad else 0
                print(
                    f"{'!!' if bad else 'OK'} {name} {theme}-{width} scroll={res['scrollW']}/{res['vw']} "
                    f"node_over={len(res['node_over'])} not_loaded={not_loaded}"
                )
                for item in res["node_over"][:6]:
                    print("     node_over", item)
    return issues


def _measures(cap, pol) -> dict | None:
    """The latest output of the measure method that computes one of the capability's values, if any."""
    methods = set()
    for v in cap.value:
        try:
            methods.add(pol.measure_method(v.id).id)
        except KeyError:
            continue
    found = []
    for p in sorted((LAYER / "instrument" / "measures").glob("*.json")):
        out = json.loads(p.read_text())
        if set(out.get("provenance", {}).get("methods", {})) & methods:
            found.append(out)
    return found[-1] if found else None


def views(reg=None, pf=None, pol=None, report=None) -> dict[str, tuple[str, str, str, str]]:
    """Every view as (title, description, path, content): a page per capability and per role, the board, the costs and
    value of each capability (V-03), and the index. The files on disk by default; a test passes other inputs."""
    sys.path.insert(0, str(LAYER))
    from generator import core, drift
    from generator.policy import load_policy, load_portfolio, load_register

    pol, reg, pf = pol or load_policy(), reg or load_register(), pf or load_portfolio()
    pol = pol.for_estate(pf.policy.overrides)  # every page reads the policy as the estate runs it
    lines = []
    for cap in reg.capabilities:
        lines += drift.read_capability(cap.id, pol, reg, parameters=_parameters(pf, cap.id))
    # one report per run: a caller that has computed it (the gates' Sources) passes it in
    rep = report if report is not None else core.report(reg, pf, pol, lines)
    comp_map, pages = site_pages(pol)
    labels = {t["id"]: t["label"] for t in pol.get("planning-tiers")}
    out = {}
    for cap in reg.capabilities:
        out[f"strategy-{cap.id}"] = (
            cap.outcome,
            f"{cap.object_in_focus[:1].upper()}{cap.object_in_focus[1:]}: what it returns, what it costs once and "
            "to keep, who owns it, and where each part is taught",
            f"/strategy/{cap.id}",
            strategy_page(cap.id, rep, reg, pf, _measures(cap, pol), lines, comp_map, pages),
        )
    out[f"board-{pf.estate}"] = (
        f"Where the {pf.estate} estate invests next",
        f"The {pf.estate} portfolio's initiatives ranked by the cost of waiting, within capacity",
        "/strategy/board",
        board_page(rep, reg, labels, pages, {r.measure: r.unit for r in pf.conversion_rates}),
    )
    out[f"costs-and-value-{pf.estate}"] = (
        "What each capability returns, and what it costs once and to keep",
        "Each capability's targets and the cost of waiting, set against its one-time investment and recurring effort",
        "/strategy/costs-and-value",
        costs_page(rep, reg, pages),
    )
    for brief in core.role_briefs(
        reg
    ):  # the register alone, never the report, so no portfolio value reaches a brief
        out[f"role-{brief['role']}"] = (
            brief["name"],
            _brief_description(brief),
            f"/strategy/roles/{brief['role']}",
            role_page(brief, reg, comp_map, pages, _used(rep, "register")),
        )
    out["agents"] = (
        "Where agents enter, layer by layer",
        "The register's agent entries: each layer of the two stacks, where an agent could act, and the capabilities that "
        "carry it",
        "/strategy/agents",
        agents_page(reg, pages, _used(rep, "register")),
    )
    out["drivers"] = (
        "What each driver re-opens",
        "Each driver of the register, the capabilities it stresses and the initiatives whose guidance a trigger on it "
        "re-opens",
        "/strategy/drivers",
        drivers_page(reg, pages, _used(rep, "register")),
    )
    out["index"] = (
        "Capabilities, what they return and cost, and who holds them",
        f"{NAME}: each capability, the board, the costs and value, and the role briefs",
        "/strategy",
        index_page(_used(rep, "register"), reg, pages, review=[(v[0], v[2]) for v in out.values()]),
    )
    # a review view marks each figure whose node no approval covers as it stands (40-BREADTH.md step 2)
    from generator import served

    held = served.awaiting(pf)
    return {name: (*v[:3], served.mark_awaiting(v[3], held)) for name, v in out.items()}


def _site_vocabulary(pol) -> tuple[dict, dict]:
    """The competency map, and the site's pages by path with each strategy page the policy publishes (its title
    blank), as every view reads them."""
    comp_map = yaml.safe_load((SITE / "competency-map.yaml").read_text())
    if str(SITE) not in sys.path:
        sys.path.insert(0, str(SITE))
    import validate_routes

    pages = {
        p["path"]: p["title"]
        for p in json.loads((SITE / "src" / "pages.json").read_text())["pages"]
        if not validate_routes.strategy_entry(p)
    }
    pages.update(dict.fromkeys(pol.get("strategy-pages"), ""))
    return comp_map, pages


def _view_of(path: str, reg) -> str:
    """The view a published path serves, as served.slice_of names it."""
    if path == "/strategy":
        return "index"
    if path == "/strategy/costs-and-value":
        return "costs"
    if path == "/strategy/board":
        return "board"
    if path == "/strategy/agents":
        return "agents"
    if path == "/strategy/drivers":
        return "drivers"
    if path.startswith("/strategy/roles/"):
        return "role:" + path.removeprefix("/strategy/roles/")
    cap = path.removeprefix("/strategy/")
    if cap in {c.id for c in reg.capabilities}:
        return "capability:" + cap
    raise ValueError(f"{path} is published, and no view is rendered at it")


def _site_slice(view: str, reg, comp_map: dict, pages: dict) -> dict:
    """The site's vocabulary one served view reads: the titles of the pages it hands off to or links, each competency
    that teaches its capabilities, which job is the foundation, and every strategy page's path (blank titled)."""
    kind, _, ident = view.partition(":")
    caps = (
        [c for c in reg.capabilities if c.id == ident]
        if kind == "capability"
        else [c for c in reg.capabilities if c.accountable == ident]
        if kind == "role"
        else []
    )
    wanted = {p for p in pages if p == "/strategy" or p.startswith("/strategy/")}
    taught = {cid for c in caps for cid in c.taught_by}
    comps = [x for x in comp_map["competencies"] if x["id"] in taught]
    for c in caps:
        wanted |= set(c.links)
        wanted |= {
            p for part in [*c.establish, *c.sustain] for h in part.handoff or [] for p in h.pages
        }
    wanted |= {x.get("teaches") for x in comps}
    return {
        "pages": {p: pages[p] for p in sorted(x for x in wanted if x in pages)},
        "comp_map": {
            "competencies": [
                {k: x.get(k) for k in ("id", "teaches", "job", "status")} for x in comps
            ],
            "jobs": [{"id": j["id"], "phase": j.get("phase")} for j in comp_map.get("jobs") or []],
        },
    }


def _parameters(pf, cap_id: str) -> dict:
    """The capability's figures under its parameters in the portfolio being rendered (schema 5); none where the
    portfolio, or the projection of it, carries the capability or its parameters not."""
    pc = next((c for c in pf.capabilities if c.id == cap_id), None) if pf is not None else None
    return dict(getattr(pc, "parameters", None) or {})


def _records_slice(view: str, reg, pol, pf=None) -> dict:
    """The pinned drift lines and the measure output a capability's page reads; none for any other view. `pf` is the
    portfolio, or the projection's, whose parameters the lines read."""
    from generator import drift

    kind, _, ident = view.partition(":")
    if kind != "capability":
        return {"drift_lines": [], "measure": None}
    cap = next(c for c in reg.capabilities if c.id == ident)
    lines = drift.read_capability(cap.id, pol, reg, parameters=_parameters(pf, cap.id))
    return {"drift_lines": lines, "measure": _measures(cap, pol)}


def render_served(s, pol) -> tuple[str, str, str, str]:
    """One served page, as (title, description, path, content), rendered from its slice alone: the core function the
    view runs, on the slice; the site's vocabulary and the records, the slice's; its digest, the slice's
    (40-BREADTH.md step 2, S1)."""
    from generator import core, served

    reg, pf = s.register, s.portfolio
    pol = pol.for_estate(pf.policy.overrides)
    lines = s.records.get("drift_lines") or []
    pages, comp_map = (
        s.site.get("pages", {}),
        s.site.get("comp_map", {"competencies": [], "jobs": []}),
    )
    overrides = [
        {"entry": o.entry, "kind": o.kind, "decided_by": o.decided_by}
        for o in pf.policy.overrides
        if o.entry in pol.overrides
    ]

    def prov(used: list[tuple[str, int]]) -> dict:
        p = core.provenance(pol, used, reg, pf, lines)
        p["input_digest"] = served.slice_digest(s, pol, FORMAT)
        return p

    kind, _, ident = s.view.partition(":")
    if kind == "capability":
        m = pol.selected("adoption-method")
        rep = {
            "grades": core.run_method("adoption-method", reg, pf, pol, lines),
            "estate": pf.estate,
            "overrides": overrides,
            "view_methods": {"capability": [m.id]},
            "provenance": prov([(m.id, m.version)]),
        }
        cap = next(c for c in reg.capabilities if c.id == ident)
        return (
            cap.outcome,
            f"{cap.object_in_focus[:1].upper()}{cap.object_in_focus[1:]}: what it returns, what it costs once and "
            "to keep, who owns it, and where each part is taught",
            f"/strategy/{cap.id}",
            strategy_page(
                cap.id, rep, reg, pf, s.records.get("measure"), lines, comp_map, pages, served=s
            ),
        )
    if kind == "costs":
        rep = {
            "costs_and_value": core.costs_and_value(reg, pf, pol),
            "estate": pf.estate,
            "overrides": overrides,
            "view_methods": {"costs": []},
            "provenance": prov([]),
        }
        return (
            "What each capability returns, and what it costs once and to keep",
            "Each capability's targets and the cost of waiting, set against its one-time investment and recurring "
            "effort",
            "/strategy/costs-and-value",
            costs_page(rep, reg, pages, served=s),
        )
    if kind == "board":
        off = set(s.off_board)
        on_board_reg = reg.model_copy(
            update={"initiatives": [d for d in reg.initiatives if d.id not in off]}
        )
        on_board_pf = pf.model_copy(
            update={"initiatives": [p for p in pf.initiatives if p.id not in off]}
        )
        rep = core.report(on_board_reg, on_board_pf, pol, lines)
        rep["provenance"]["input_digest"] = served.slice_digest(s, pol, FORMAT)
        labels = {t["id"]: t["label"] for t in pol.get("planning-tiers")}
        return (
            f"Where the {pf.estate} estate invests next",
            f"The {pf.estate} portfolio's initiatives ranked by the cost of waiting, within capacity",
            "/strategy/board",
            board_page(
                rep,
                reg,
                labels,
                pages,
                {r.measure: r.unit for r in pf.conversion_rates},
                served=s,
            ),
        )
    if kind == "role":
        brief = next(b for b in core.role_briefs(reg) if b["role"] == ident)
        return (
            brief["name"],
            _brief_description(brief),
            f"/strategy/roles/{ident}",
            role_page(brief, reg, comp_map, pages, prov([])),
        )
    if kind == "agents":
        return (
            "Where agents enter, layer by layer",
            "The register's agent entries: each layer of the two stacks, where an agent could act, and the "
            "capabilities that carry it",
            "/strategy/agents",
            agents_page(reg, pages, prov([])),
        )
    if kind == "drivers":
        return (
            "What each driver re-opens",
            "Each driver of the register, the capabilities it stresses and the initiatives whose guidance a trigger "
            "on it re-opens",
            "/strategy/drivers",
            drivers_page(reg, pages, prov([])),
        )
    return (
        "Capabilities, what they return and cost, and who holds them",
        f"{NAME}: each capability, the board, the costs and value, and the role briefs",
        "/strategy",
        index_page(prov([]), reg, pages),
    )


def served_views(reg=None, pf=None, pol=None) -> dict[str, tuple[str, str, str, str]]:
    """Every page `strategy-pages` publishes, each rendered from its slice of the served projection (40-BREADTH.md
    step 2, S1 to S3), by the name `views` gives it."""
    sys.path.insert(0, str(LAYER))
    from generator import served
    from generator.policy import load_policy, load_portfolio, load_register

    pol, reg, pf = pol or load_policy(), reg or load_register(), pf or load_portfolio()
    projection = served.project(reg, pf, pol)
    comp_map, pages = _site_vocabulary(pol.for_estate(pf.policy.overrides))
    out = {}
    for path in pol.for_estate(pf.policy.overrides).get("strategy-pages"):
        view = _view_of(path, reg)
        s = served.slice_of(
            view,
            projection,
            _site_slice(view, projection.register, comp_map, pages),
            _records_slice(
                view, projection.register, pol.for_estate(pf.policy.overrides), projection.portfolio
            ),
        )
        kind, _, ident = view.partition(":")
        name = {
            "capability": f"strategy-{ident}",
            "costs": f"costs-and-value-{pf.estate}",
            "board": f"board-{pf.estate}",
            "role": f"role-{ident}",
            "index": "index",
            "agents": "agents",
            "drivers": "drivers",
        }[kind]
        out[name] = render_served(s, pol)
    return out


_READ: dict[tuple[str, int, int], str] = {}


def _read(path: Path) -> str:
    """A file's text, read once for as long as it is unchanged (its size and its modification time the key): the
    review render reads the same chapters and pages.json for every page that cites them."""
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _READ:
        _READ[key] = path.read_text(encoding="utf-8")
    return _READ[key]


_MANIFEST: dict[
    str, tuple[dict, dict]
] = {}  # pages.json parsed and its chapter index, once per text
_PLATES: dict[str, str] = {}  # a chapter reduced to the plates it declares, once per text


def _manifest(text: str, sref) -> tuple[dict, dict]:
    """The site's manifest and its chapter index, built once for every view that cites a chapter."""
    if text not in _MANIFEST:
        manifest = json.loads(text)
        _MANIFEST[text] = (manifest, sref.chapter_index(manifest["curriculum"]))
    return _MANIFEST[text]


def _plates_declared(chapter: str, sref) -> str:
    """A cited chapter as the plate check needs it: only the plate numbers it declares, in order, in the markup the
    check reads them from. The chapter's own references are its build's to hold, not this view's, and reading its whole
    text for every view that cites it was the review render's largest cost at the catalog's full size."""
    if chapter not in _PLATES:
        _PLATES[chapter] = "".join(
            f'<span class="no">{n}</span>' for n in sref._PLATE_NO.findall(chapter)
        )
    return _PLATES[chapter]


def structure_refs(content: str, path: str) -> str:
    """The site's structure references (`[[ch:slug]]`, `[[ch:slug]]'s plate NN`; D-053) rendered as the site build
    renders them, and each plate a reference names held to the plates its chapter declares, as the build holds them:
    for the review copy. The site's own copy keeps the references, which its build renders and holds."""
    if str(SITE) not in sys.path:
        sys.path.insert(0, str(SITE))
    import structure_refs as sref

    manifest, index = _manifest(_read(SITE / "src" / "pages.json"), sref)
    # the chapters the page cites, read for the plates they declare and nothing else; no other page is read
    cited = {s for m in sref.REF.finditer(content) for s in m.group(2).split(",")}
    files = {m["path"]: m["file"] for m in manifest["pages"]}
    frags = {
        index[s][2]: _plates_declared(_read(SITE / "src" / "pages" / files[index[s][2]]), sref)
        for s in cited
        if s in index and index[s][2] in files
    }
    frags[path] = content
    errors = [
        e for e in sref.check_plates(frags, manifest["curriculum"]) if e.startswith(f"{path}:")
    ]
    out, more = sref.render(content, path, manifest["curriculum"])
    if errors or more:
        raise ValueError("; ".join(errors + more))
    return out


def drift_lines(reg, pol, pf=None) -> list[dict]:
    """Every capability's drift lines, from the pinned copies of the companion records its adapter reads, with the
    capability's parameters from `pf`, the portfolio the caller renders."""
    from generator import drift

    lines = []
    for cap in reg.capabilities:
        lines += drift.read_capability(cap.id, pol, reg, parameters=_parameters(pf, cap.id))
    return lines


def docs(reg=None, pf=None, pol=None, report=None) -> dict[str, str]:
    """Every view, as the renderer emits it for review: each view's content, its structure references rendered, in
    the site's own layout."""
    out = {
        name: wrap(title, description, path, structure_refs(content, path))
        for name, (title, description, path, content) in views(reg, pf, pol, report).items()
    }
    one_page_per_path(out)
    return out


# ── the site's copies (DEC-07, 30-GATES.md step 10) ──────────────────────────────────────────────────────────────────
ROUTE_BEHIND = "{{route_behind}}"  # the marker the site build fills with the routes that own a capability's jobs


def site_file(path: str) -> str:
    """The fragment a strategy page's path is served from, under the site's src/pages/."""
    return (
        "strategy.html"
        if path == "/strategy"
        else "strategy-" + path.removeprefix("/strategy/").replace("/", "-") + ".html"
    )


def one_file_per_path(paths: list[str]) -> None:
    """Each published path served from a file of its own: two paths that name one file (`/strategy/roles/x` and a
    capability `roles-x`) would leave one copy for two entries, so the render refuses them by name."""
    files: dict[str, list[str]] = {}
    for path in paths:
        files.setdefault(site_file(path), []).append(path)
    shared = {f: ps for f, ps in files.items() if len(ps) > 1}
    if shared:
        raise ValueError(
            "policy.yaml's strategy-pages names paths served from one file: "
            + "; ".join(f"{', '.join(ps)} as {f}" for f, ps in shared.items())
            + "; rename the capability or the view so each path has a file of its own"
        )


def site(reg=None, pf=None, pol=None) -> tuple[dict[str, str], list[dict]]:
    """The strategy pages the site serves (`policy.yaml` `strategy-pages`, DEC-07), each as its body fragment for the
    site's src/pages/ and its pages.json entry. A fragment is the view's content without the review layout; a link to a
    strategy page the site does not serve is read as its text, so no served page links a page that is not served; a
    capability's page carries the one route-behind marker the site build fills from the routes that own its jobs. An
    entry is flagged `strategy`, with the view it is and, for a capability, the jobs it serves; it holds no `nav`."""
    sys.path.insert(0, str(LAYER))
    from generator.policy import load_policy, load_portfolio, load_register

    reg, pol, pf = reg or load_register(), pol or load_policy(), pf or load_portfolio()
    # the policy as the estate runs it, as every reader reads it (charter section 5.12)
    published = list(pol.for_estate(pf.policy.overrides).get("strategy-pages"))
    every = served_views(reg, pf, pol)  # each from its slice of the served projection (S1 to S3)
    by_path = {view[2]: (name, view) for name, view in every.items()}
    unknown = [p for p in published if p not in by_path]
    if unknown:
        raise ValueError(
            f"policy.yaml's strategy-pages names {', '.join(unknown)}, at which no view is rendered"
        )
    one_file_per_path(published)
    caps = {f"/strategy/{c.id}": c for c in reg.capabilities}
    frags, entries = {}, []
    for path in published:
        name, (title, description, _path, content) = by_path[path]
        content = re.sub(
            r'<a href="(/strategy[^"#]*)(#[^"]*)?">(.*?)</a>',
            lambda m: m.group(0) if m.group(1) in published else m.group(3),
            content,
            flags=re.S,
        )
        cap = caps.get(path)
        if cap:
            if content.count('<p class="prov"') != 1:
                raise ValueError(
                    f"{path}: the page has no single provenance line to set the route behind it above"
                )
            content = content.replace('<p class="prov"', ROUTE_BEHIND + '\n<p class="prov"', 1)
        file = site_file(path)
        frags[file] = content.rstrip("\n") + "\n"
        # a capability's entry carries the jobs it serves, which pair its page with the routes that own them, and,
        # for the layer's own practice, the outside model's capability it implements (GATE-2: a capability has a job
        # or a practice), so the route gate reads the declaration and never an empty list alone
        flag = (
            {
                "view": "capability",
                "capability": cap.id,
                "jobs": list(cap.jobs),
                **({"practice": cap.practice} if cap.practice else {}),
            }
            if cap
            else {"view": name.split("-")[0] if path != "/strategy" else "index"}
        )
        entries.append(
            {
                "path": path,
                "file": file,
                "title": title,
                "description": description,
                "strategy": flag,
            }
        )
    return frags, entries


def with_entries(manifest: dict, entries: list[dict]) -> dict:
    """pages.json with its strategy entries replaced by `entries`, every other entry and key as it was: an entry is the
    generator's by its flag, its path or the copy it serves (validate_routes.strategy_entry), so a re-render drops one
    written by hand that it does not emit."""
    if str(SITE) not in sys.path:
        sys.path.insert(0, str(SITE))
    import validate_routes

    out = dict(manifest)
    out["pages"] = [p for p in manifest["pages"] if not validate_routes.strategy_entry(p)] + entries
    return out


def site_pages(pol) -> tuple[dict, dict[str, str]]:
    """The competency map, and the pages a hand-off or a door may go to: the site's own pages from pages.json, and the
    strategy pages from the policy alone, so a page the policy publishes or withdraws is published or withdrawn in the
    render that writes it, never one render later."""
    comp_map = yaml.safe_load((SITE / "competency-map.yaml").read_text())
    if str(SITE) not in sys.path:
        sys.path.insert(0, str(SITE))
    import validate_routes

    pages = {
        p["path"]: p["title"]
        for p in json.loads((SITE / "src" / "pages.json").read_text())["pages"]
        if not validate_routes.strategy_entry(p)
    }
    pages.update(dict.fromkeys(pol.get("strategy-pages"), ""))
    return comp_map, pages


# ── the front door's feed (schema 6; DEC-06, 50-FRONT-DOOR.md section 9) ────────────────────────────────────────────
FRONT_DOOR = (
    SITE / "src" / "strategy-front-door.json"
)  # beside pages.json; the home renderer reads it, and only it
NOT_TAUGHT = "not taught yet"  # the empty state the role page prints, carried in the feed so the page types no literal
ROLE_WORK = (
    "writes",
    "runs",
    "measures",
)  # with `accountable_for`, the relations a role's brief shows as the role's own work


def role_chapters(reg, comp_map: dict, pages: dict[str, str]) -> dict[str, list[str]]:
    """Per role, the published chapters that teach the capabilities its brief shows as the role's work (accountable
    for, writes, runs, measures; sponsoring and reading are initiatives and watch entries, not capabilities), classed
    through the same hand-offs as the role page, so a foundation chapter the brief shows as background never reaches
    a door; in the competency map's order, each once."""
    from generator import core

    order = {c["teaches"]: i for i, c in enumerate(comp_map["competencies"]) if c.get("teaches")}
    caps = {c.id: c for c in reg.capabilities}
    out = {}
    for brief in core.role_briefs(reg):
        work = set(brief["accountable_for"]) | {
            x["capability"] for k in ROLE_WORK for x in brief[k]
        }
        paths = {
            p
            for cid in work
            for kind, p, _title in handoffs(caps[cid], comp_map, pages)
            if kind == "taught by"
        }
        out[brief["role"]] = sorted(paths, key=lambda p: (order.get(p, len(order)), p))
    return out


def front_door(reg, pol, comp_map: dict, pages: dict[str, str]) -> dict:
    """The feed the home renderer reads: each reader's door with the title, promise and paths the register types, the
    door written `roles` derived from the roles (one published brief per role, and the chapters that teach the role's
    work), the two words the page prints that the generator owns, and the provenance every served output carries.
    Lists, never counts: the renderer counts. The register's order is the feed's, and the feed refuses a door that
    opens a view the policy does not publish or pairs with a page the site does not serve (GATE-15)."""
    from generator.models import ROLES_DOOR, SCHEMA_VERSIONS, FrontDoor

    published = set(pol.get("strategy-pages"))
    chapters = role_chapters(reg, comp_map, pages)
    readers = []
    for r in reg.readers:
        door: dict = {"title": r.door.title, "promise": r.door.promise}
        if r.door.strategy == ROLES_DOOR:
            door["roles"] = [
                {
                    "id": role.id,
                    "name": role.name,
                    "brief": f"/strategy/roles/{role.id}",
                    "chapters": chapters[role.id],
                }
                for role in reg.roles
            ]
            unpublished = [x["brief"] for x in door["roles"] if x["brief"] not in published]
            unserved: list[str] = []
        else:
            door["strategy"], door["handbook"] = list(r.door.strategy), list(r.door.handbook)
            unpublished = [p for p in r.door.strategy if p not in published]
            unserved = [p for p in r.door.handbook if p.partition("#")[0] not in pages]
        if unpublished:
            raise ValueError(
                f"the {r.id}'s door opens {', '.join(unpublished)}, which the policy does not publish"
            )
        if unserved:
            raise ValueError(
                f"the {r.id}'s door pairs with {', '.join(unserved)}, which the site does not serve"
            )
        readers.append({"id": r.id, "name": r.name, "question": r.question, "door": door})
    if not readers:
        raise ValueError("the register names no reader; the front door has no door to draw")
    content = {"readers": readers, "labels": {"layer": NAME, "not_taught": NOT_TAUGHT}}
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    feed = {
        "schema": SCHEMA_VERSIONS["front_door"],
        **content,
        "provenance": {
            "policy_version": pol.model.policy_version,
            "schemas": {k: SCHEMA_VERSIONS[k] for k in ("register", "portfolio", "policy")},
            "input_digest": digest,
        },
    }
    FrontDoor.model_validate(feed)
    return feed


def front_door_text(feed: dict) -> str:
    return json.dumps(feed, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def emit_front_door(pol=None, reg=None, pf=None) -> str:
    """The feed as text from the files, as the estate runs the policy; a policy passed in is taken as the estate
    runs it (the gates' loaded view)."""
    from generator.policy import load_policy, load_portfolio, load_register

    reg, pf = reg or load_register(), pf or load_portfolio()
    pol = pol if pol is not None else load_policy().for_estate(pf.policy.overrides)
    comp_map, pages = site_pages(pol)
    return front_door_text(front_door(reg, pol, comp_map, pages))


def write_if_changed(path: Path, text: str) -> bool:
    """Write a page only when it differs from the one on disk beyond its generation stamp, so a render that changes
    nothing leaves every file, and every stamped page date, as it was."""
    if path.exists():
        have = path.read_text(encoding="utf-8")
        if stampless(have) == stampless(text) and stamp_shaped(
            have
        ):  # a stamp edited out of shape is rewritten
            return False
    path.write_text(text, encoding="utf-8")
    return True


def one_page_per_path(pages: dict[str, str]) -> None:
    """Every page at its own path: a capability whose id is a view's name (board, costs-and-value, roles) would take
    that view's path, and one of the two would never be served."""
    held: dict[str, str] = {}
    for name, page in pages.items():
        m = re.search(r'<link rel="canonical" href="(?:https?://[^/"]+)?([^"]*)"', page)
        path = m.group(1) if m else name
        if path in held:
            raise ValueError(
                f"the pages {held[path]} and {name} would both be served at {path}; rename the id that takes a "
                "view's path"
            )
        held[path] = name


def write_views(docs_: dict[str, str], out: Path) -> None:
    """Write each view the renderer emits, and remove a view directly in `out` it no longer emits (a renamed role or
    capability), so a re-render, the edit GATE-9 names for a view no generator emits, answers it."""
    out.mkdir(parents=True, exist_ok=True)
    for name, doc in docs_.items():
        write_if_changed(out / f"{name}.html", doc)
    for stale in sorted(out.glob("*.html")):
        if stale.stem not in docs_:
            stale.unlink()


def main(argv: list[str]) -> int:
    docs_ = docs()
    if (
        "--validate" not in argv
    ):  # a validation renders in memory and leaves the committed views as they are
        write_views(docs_, OUT)
        # the site's copies of the pages it serves, and their entries (DEC-07)
        frags, entries = site()
        for file, frag in frags.items():
            write_if_changed(SITE / "src" / "pages" / file, frag)
        manifest_path = SITE / "src" / "pages.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        updated = with_entries(manifest, entries)
        if updated != manifest:
            manifest_path.write_text(
                json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        # the front door's feed, the one file the home renderer reads for the doors (DEC-06)
        feed = emit_front_door()
        if not FRONT_DOOR.exists() or FRONT_DOOR.read_text(encoding="utf-8") != feed:
            FRONT_DOOR.write_text(feed, encoding="utf-8")
    if "--validate" in argv:
        out_dir = (
            Path(argv[argv.index("--validate") + 1]).resolve()
            if len(argv) > argv.index("--validate") + 1
            else Path(tempfile.gettempdir())
            / "strategy-render"  # screenshots never land in the repository
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        issues = validate(docs_, out_dir)
        print(f"TOTAL issues: {issues}; screenshots in {out_dir}")
        return 1 if issues else 0
    print(f"wrote {', '.join(sorted(docs_))} to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main(sys.argv[1:]))
