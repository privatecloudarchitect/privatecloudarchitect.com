"""adopt.py - the adopter's companion: read an estate's records and portfolio, judge them, and emit the console's views.

Use:  python -m companion.adopt --root ROOT --run RUN --portfolio PATH --records DIR --scrub-list PATH --vocabulary PATH
                               [--register PATH] [--policy PATH] [--import PATH] [--day YYYY-MM-DD]
      ROOT        the layer's folder the code and files are read from: docs/design/enterprise-strategy-layer in this
                  repository, strategy/ in the companion repository's mirror (never derived from where this file sits)
      RUN         the run folder: views/, gates.json, provenance.json and private/ (briefs, imports, the raw lines)
      --records   a folder holding pins.yaml and the record copies it names, flat (drift.read_capability's pins_dir)
      --scrub-list the estate identifiers never to reach a view: a .py holding KILL_LIST and KILLLIST_ALLOW, read as
                  data and never run, or a .yaml holding kill and allow
      --vocabulary the site vocabulary a strategy release wrote (generator/vocabulary.py)
      --import    a stand-in export of a system of record: {"supplies": {field: [address prefixes]}, "values": {...}};
                  its values land in RUN/private/imported.json, never in the portfolio (GATE-14, 14.9)
      --day       the day the date clauses judge at (default: the run's UTC date, recorded)
Exit: 0 every clause the companion covers passed and nothing refused; 1 a covered clause refused (the views still
      render); 2 a refusal before any view renders (two departments for one role in one scope; an illustrative value in
      an adopter's portfolio; an override of an entry not overridable, one-way or without its decision; a node under a
      path the run's import supplies, or an import supplying a field the portfolio does not import), the portfolio
      having been read and judged; 3 an input it could not read, or a portfolio two or more schemas behind (told which);
      5 a usage error, before anything is read. The identity companions' contract: 0 nothing to act on, 3 not read, 5
      usage; 1 and 2 keep this script's meanings above.
It holds no credential and opens no connection; it reads the paths it is passed and the root, and writes RUN alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

EXIT_FINDING, EXIT_REFUSED, EXIT_UNREAD, EXIT_USAGE = 1, 2, 3, 5


def _args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="adopt.py", allow_abbrev=False)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--portfolio", type=Path, required=True)
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--scrub-list", type=Path, required=True)
    ap.add_argument("--vocabulary", type=Path, required=True)
    ap.add_argument("--register", type=Path, default=None)
    ap.add_argument("--policy", type=Path, default=None)
    ap.add_argument("--import", dest="import_", type=Path, default=None)
    ap.add_argument("--day", default=None)
    return ap.parse_args(argv)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root_file(root: Path, name: str) -> Path:
    """The root's own copy of a layer file, or its pinned copy under companion/pinned/ where the root holds none (the
    mirror ships the pinned register and policy there, beside pins.json)."""
    own = root / name
    return own if own.exists() else root / "companion" / "pinned" / name


def _is_reference(root: Path, portfolio: Path) -> bool:
    """The reference portfolio is the file whose sha256 the pinned copies record (companion/pinned/pins.json: the
    working file's digest at the pin, and the projected copy's); any other file is an adopter's, whatever its estate
    says (3c's S2)."""
    pins = root / "companion" / "pinned" / "pins.json"
    if not pins.exists():
        return False
    try:
        recorded = json.loads(pins.read_text(encoding="utf-8")).get("portfolio") or {}
    except (OSError, ValueError):
        return False
    digest = _sha(portfolio)
    return digest in {recorded.get("source_sha256"), recorded.get("copy_sha256")} - {None}


def _illustrative(data, path=()) -> list[str]:
    """Every illustrative figure in a portfolio, by its path; the approvals, which record figures and are no figure,
    set aside."""
    out = []
    if isinstance(data, dict):
        if not path:
            data = {k: v for k, v in data.items() if k not in ("approval", "approvals")}
        if data.get("kind") == "illustrative":
            out.append("/".join(str(p) for p in path) or "the file")
        for k, v in data.items():
            out += _illustrative(v, (*path, k))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            out += _illustrative(v, (*path, i))
    return out


def main(argv: list[str]) -> int:
    try:
        a = _args(argv)
    except SystemExit:
        return EXIT_USAGE
    root = a.root.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from generator import core, drift, gates, scrublist
        from generator.gates import CLAUSES
        from generator.models import SCHEMA_VERSIONS, parse_day
        from generator.policy import load_data

        from companion import grades, sources, split, views
        from companion.layout import LAYOUT
    except ImportError as e:
        print(f"the layer's code was not found under {a.root} ({e})", file=sys.stderr)
        return EXIT_UNREAD
    from generator import check

    # the register and the policy are the root's own files (this repository's layer folder) or, where the root holds
    # none, the pinned copies under companion/pinned/ (the companion repository's mirror, step 12)
    register = a.register or _root_file(root, "register.yaml")
    policy = a.policy or _root_file(root, "policy.yaml")
    try:
        day = parse_day(a.day) if a.day else datetime.now(UTC).date()
    except ValueError:
        print("--day takes a date, YYYY-MM-DD", file=sys.stderr)
        return EXIT_USAGE
    try:
        lists = scrublist.kill_list_from(a.scrub_list)
    except (OSError, ValueError) as e:
        print(f"the scrub list could not be read: {e}", file=sys.stderr)
        return EXIT_UNREAD
    imported = None
    if a.import_ is not None:
        try:
            imported = json.loads(a.import_.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"the import could not be read: {type(e).__name__}", file=sys.stderr)
            return EXIT_UNREAD
        if not isinstance(imported, dict) or not isinstance(imported.get("supplies"), dict):
            print(
                "the import holds no `supplies` mapping (field: [address prefixes])",
                file=sys.stderr,
            )
            return EXIT_UNREAD
    # the portfolio's schema: the current and the previous are read, an older one is told so (S9-17)
    try:
        raw = load_data(a.portfolio.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"the portfolio could not be read: {type(e).__name__}", file=sys.stderr)
        return EXIT_UNREAD
    held = raw.get("schema") if isinstance(raw, dict) else None
    current = SCHEMA_VERSIONS["portfolio"]
    if not isinstance(held, int) or held < current - 1:
        print(
            f"the portfolio is at schema {held!r}; this companion reads schema {current} and {current - 1}: migrate it "
            f"with generator/migrate.py (each version in turn)",
            file=sys.stderr,
        )
        return EXIT_UNREAD
    try:
        s, vocab = sources.read(
            root,
            register,
            a.portfolio,
            policy,
            a.vocabulary,
            imported["supplies"] if imported else None,
            lists,
            frozenset(split.partition()[0]),
        )
    except sources.NotReadError as e:
        print(f"not read: {e}", file=sys.stderr)
        return EXIT_UNREAD
    # the refusals, before any view renders and before the typing (section 10 of the design): the raw-file gates judge
    # the files as written, so a fault the models also refuse is told as the refusal it is (exit 2), never as unread
    refusals: list[str] = []
    if not _is_reference(root, a.portfolio):
        for where in _illustrative(s.portfolio.data):
            refusals.append(
                f"an illustrative value in an adopter's portfolio at {where} (GATE-7, 7.4)"
            )
    results = gates.run(s, gates=split.GATES_RUN)
    for r in results:
        for f in r.findings:
            if f.clause in ("1.5", "14.8", "14.9"):
                refusals.append(  # the clause by its charter phrase, then the finding
                    f"{f.clause} ({gates.CLAUSES[f.clause][1]}): {f.what} ({f.file}:{f.line})"
                )
    if refusals:
        for why in refusals:
            print(f"refused: {gates.scrub(why, lists)}", file=sys.stderr)
        print(
            f"{len(refusals)} refusal(s): nothing rendered (exit {EXIT_REFUSED})", file=sys.stderr
        )
        return EXIT_REFUSED
    typed = s.typed()
    if typed is None:
        print(f"the files do not load through their models: {s.why_untyped()}", file=sys.stderr)
        return EXIT_UNREAD
    reg, pf, pol = typed

    # the date clauses the companion covers (13.1, 13.2), judged at --day with no run records
    date_found, date_listed = check.gate_13(s, day, [], [])
    # the drift lines over the passed records, every line guarded before it reaches a view
    lines: list[dict] = []
    for cap in reg.capabilities:
        pc = next((c for c in pf.capabilities if c.id == cap.id), None)
        parameters = dict(getattr(pc, "parameters", None) or {})
        lines += drift.read_capability(
            cap.id, pol, reg, root=root, parameters=parameters, pins_dir=a.records
        )
    lines = drift.guard_lines(lines, lists)
    report = core.report(reg, pf, pol, lines)
    gates_report = split.report(results, date_found, date_listed)

    run = a.run
    (run / "views").mkdir(parents=True, exist_ok=True)
    (run / "private" / "briefs").mkdir(parents=True, exist_ok=True)
    (run / ".gitignore").write_text("private/\n", encoding="utf-8")
    pins_digest = _sha(a.records / "pins.yaml")
    vocab_digest = hashlib.sha256(json.dumps(vocab, sort_keys=True).encode()).hexdigest()[:16]
    source = f"inputs {report['provenance']['input_digest']}; records {pins_digest[:16]}; vocabulary {vocab_digest}"
    prov = views.provenance_text(
        report["provenance"],
        day.isoformat(),
        LAYOUT,
        f" Records pinned {pins_digest[:16]}; vocabulary {vocab_digest}.",
    )

    def put(rel: str, html: str) -> None:
        (run / rel).write_text(gates.scrub(html, lists), encoding="utf-8")

    role_rows = grades.fold(report, reg, pol)
    departments = grades.departments(pf, role_rows)
    put("views/adoption.html", views.adoption(report, reg, pf, pol, lines, prov, source))
    put("views/drift.html", views.drift(lines, pf, pol, day.isoformat(), prov, source))
    put("views/board.html", views.board(report, pf, pol, prov, source))
    put("views/index.html", views.index(pf, departments, gates_report, prov, source))
    for d in departments:
        put(
            f"private/briefs/{d['department']}.html",
            views.brief(
                d["department"],
                d["roles"],
                pf,
                reg,
                report,
                lines,
                pol,
                day.isoformat(),
                prov,
                source,
            ),
        )
    (run / "gates.json").write_text(
        json.dumps(gates_report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (run / "private" / "lines.json").write_text(
        json.dumps(lines, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if imported is not None:
        (run / "private" / "imported.json").write_text(
            json.dumps(imported, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    (run / "private" / "provenance.json").write_text(
        json.dumps(
            {
                "root": str(root),
                "run": str(run.resolve()),
                "portfolio": str(a.portfolio.resolve()),
                "records": str(a.records.resolve()),
                "day": day.isoformat(),
                "reference": _is_reference(root, a.portfolio),
                "provenance": report["provenance"],
                "pins_sha256": pins_digest,
                "vocabulary_written_from": vocab["written_from"],
                "clauses": len(CLAUSES),
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"adopt.py: {len(lines)} drift lines, {len(role_rows)} role rows, {len(departments)} briefs; gates: "
        f"{gates_report['refused']} refused, {gates_report['not_covered']} not covered here, "
        f"{gates_report['not_judged']} not judged; views under {run / 'views'}"
    )
    if gates_report[
        "not_judged"
    ]:  # a covered clause whose gate could not judge: the result is not known
        print(
            f"{gates_report['not_judged']} covered clause(s) its gate could not judge, each named with the reason in "
            f"gates.json: the result is not known (exit {EXIT_UNREAD})",
            file=sys.stderr,
        )
        return EXIT_UNREAD
    return EXIT_FINDING if gates_report["refused"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
