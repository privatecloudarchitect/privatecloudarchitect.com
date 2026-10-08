"""naming.py: does a content name hold its class's grammar by meaning, not just by its separators?

One function, used by content.py's census and by any tool that proposes a name, so the audit and the author
test the same thing. Standard library only, no network, no estate values: the owner prefix, the registered
bundles, the kind vocabulary and the environment's scope values all arrive as input (see naming.example.json).

The grammar, one per class (a field never contains the separator " - "):

  super metric            <Owner> - <Bundle> - <Kind> - <Measure (unit)>
  symptom definition      <Owner> - <Bundle> - <Kind> - <Condition>
  alert definition        <Owner> - <Bundle> - <Kind> - <Condition>
  custom group            <Owner> - <Bundle> - <Scope> (<member kinds>)
  policy                  <Owner> - <Bundle> - <Scope>
  view, report definition <Owner> - <Bundle> - <Subject>
  dashboard               <Owner> - <Bundle> - <Question or audience>
  notification rule       <Owner> - <Bundle> - <Route>

Parentheses carry a unit or a group's member kinds; a measure that ends in a unit carries it in parentheses
("Recoverable Cold DRAM (GB)", never "Recoverable Cold DRAM GB"). Square brackets carry one scope qualifier, at the very end,
on a per-scope copy of a definition, view or dashboard. An environment value (a posture, a tier, any name your
estate gives a scope) may appear only as a group's or policy's own scope field, or inside that qualifier.

Run:  python3 naming.py --vocabulary naming.example.json "PCA - Example - VM - CPU Ready (%)" "super metric"
"""

import json
import re
import sys

SEP = " - "

GRAMMAR = {
    "super metric": ("owner", "bundle", "kind", "measure"),
    "symptom definition": ("owner", "bundle", "kind", "condition"),
    "alert definition": ("owner", "bundle", "kind", "condition"),
    "custom group": ("owner", "bundle", "scope"),
    "policy": ("owner", "bundle", "scope"),
    "view": ("owner", "bundle", "subject"),
    "report definition": ("owner", "bundle", "subject"),
    "report": ("owner", "bundle", "subject"),
    "dashboard": ("owner", "bundle", "question"),
    "notification rule": ("owner", "bundle", "route"),
}

# content.py counts classes under plural labels; map them to the grammar's names.
CLASS_OF_LABEL = {
    "custom groups": "custom group", "super metrics": "super metric", "alert definitions": "alert definition",
    "symptom definitions": "symptom definition", "policies": "policy", "report definitions": "report definition",
    "reports": "report", "notification rules": "notification rule",
}

QUALIFIED = {"super metric", "symptom definition", "alert definition", "view", "report definition", "report",
             "dashboard"}
SCOPED = {"custom group", "policy"}
QUALIFIER = re.compile(r" \[([^\[\]]+)\]$")
# Units a measure may end in. A vocabulary's "units" list replaces this one.
DEFAULT_UNITS = ("%", "B", "KB", "KiB", "MB", "MiB", "GB", "GiB", "TB", "TiB", "Hz", "MHz", "GHz", "W", "kW",
                 "ms", "s", "IOPS", "Mbps", "Gbps", "KBps", "MBps", "USD", "EUR", "count", "pct")


def load_vocabulary(path):
    """{owner, bundles: {short name: directory}, kinds: {short: {plural, keys}}, scopes: [...],
    environmentValues: [...], units: [...]} from a JSON file. Every key is optional except owner."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _token(value):
    return re.compile(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])")


def check(name, cls, vocab, kind_key=None):
    """The reasons `name` does not hold `cls`'s grammar; an empty list means it conforms by meaning.

    `kind_key` is the object's own resource kind key, when the caller has it (a symptom or alert definition
    carries one); the kind field must then name that kind.
    """
    cls = CLASS_OF_LABEL.get(cls, cls)
    if cls not in GRAMMAR:
        return [f"unknown class {cls!r}"]
    owner = vocab.get("owner", "")
    reasons = []
    if not name.startswith(owner + SEP):
        return ["not the owner's: the prefix must be the owner followed by the separator"]
    shape = GRAMMAR[cls]
    fields = name.split(SEP)
    if len(fields) != len(shape):
        reasons.append(f"field count: {len(fields)} where {cls} takes {len(shape)} "
                       f"({' - '.join('<' + s + '>' for s in shape)}); a field may not contain ' - '")
        return reasons
    if any(not f.strip() for f in fields):
        reasons.append("an empty field")
    bundles = vocab.get("bundles")
    if bundles is not None and fields[1] not in bundles:
        reasons.append(f"bundle {fields[1]!r} is not registered")
    kinds = vocab.get("kinds")
    if "kind" in shape and kinds is not None:
        k = fields[shape.index("kind")]
        if k not in kinds:
            reasons.append(f"kind {k!r} is not in the kind vocabulary")
        elif kind_key and kind_key not in (kinds[k].get("keys") or []):
            reasons.append(f"kind {k!r} does not name the object's own kind {kind_key!r}")
    last = fields[-1]
    q = QUALIFIER.search(last)
    if "[" in name or "]" in name:
        if cls not in QUALIFIED:
            reasons.append(f"qualifier form: a {cls} names its scope in its scope field, not in brackets")
        elif not q or name.count("[") != 1 or name.count("]") != 1:
            reasons.append("qualifier form: one ' [<scope>]' at the very end, and no other brackets")
        elif vocab.get("scopes") is not None and q.group(1) not in vocab["scopes"]:
            reasons.append(f"qualifier {q.group(1)!r} is not a declared scope")
    if "measure" in shape:
        measure = last[: -len(q.group(0))] if q else last
        if not measure.endswith(")"):
            tail = measure.split()[-1] if measure.split() else ""
            if tail in (vocab.get("units") or DEFAULT_UNITS):
                reasons.append(f"unit {tail!r} outside parentheses: a measure carries its unit as ' (<unit>)'")
    if cls == "custom group":
        m = re.search(r"\(([^()]+)\)$", last)
        plural = {v.get("plural") for v in (kinds or {}).values()}
        if not m:
            reasons.append("a custom group's scope field ends with its member kinds in parentheses")
        elif kinds is not None:
            unknown = [p.strip() for p in m.group(1).split(",") if p.strip() not in plural]
            if unknown:
                reasons.append(f"member kinds {unknown} are not in the kind vocabulary")
    # An environment value may sit only in a group's or policy's scope field, or inside the qualifier.
    inspect = list(fields[1:])
    if cls in SCOPED:
        inspect = [fields[1]]
    elif q:
        inspect[-1] = inspect[-1][: -len(q.group(0))]
    text = SEP.join(inspect)
    for value in vocab.get("environmentValues") or []:
        if _token(value).search(text):
            reasons.append(f"environment value {value!r} outside a scope field or qualifier")
    return reasons


def conforms(name, cls, vocab, kind_key=None):
    return not check(name, cls, vocab, kind_key)


def main(argv):
    if len(argv) < 4 or argv[0] != "--vocabulary":
        print(__doc__.split("Run:")[1].strip())
        return 2
    vocab = load_vocabulary(argv[1])
    reasons = check(argv[2], argv[3], vocab)
    print("conforms" if not reasons else "\n".join(reasons))
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
