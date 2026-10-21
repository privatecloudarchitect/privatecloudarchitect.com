#!/usr/bin/env python3
"""validate_content.py - check Orchestrator workflows and actions on your machine, before any import.

An import that fails on the appliance costs a round trip and says little. These rules run locally, on every
workflow and action under the paths you give, and print each finding as `file:line: rule level: message`:

  workflows (a .workflow package, or its workflow-content as a .xml file)
    R1 error    display names, descriptions, scripts and values wrapped in character data, not written as text
    R2 error    a decision item names both an onward and an alternative onward item, has a script, and has an
                output binding element even when it binds nothing (a script with no return is a warning)
    R3 error    every canvas position is decimal on both coordinates (60.0, not 60)
    R4 warning  an input binding names a variable the workflow declares (a workflow-scoped one is not visible
                to this check, so it warns rather than fails)
    R5 error    a SecureString attribute carries no value element
    R6 error    the document parses
  actions (a .action package, or its action-content as a .xml file)
    R6 error    the document parses
    R10 error   the action name starts with a letter and holds only letters, digits and underscores
    R11 warning every parameter carries a description, and the module declares a result type
  both, packaged
    R7 warning  script text is ASCII; non-ASCII characters in a script are the case the VCF Operations 9.1.1.0
                release notes warn becomes a hex-encoded string on export and import
    R8 error    the info member's declared charset agrees with what the content member actually is: UTF-16 with a
                byte-order mark (FF FE or FE FF) or, with no mark, UTF-8
    R9 note     the info member's creator; with --creator NAME, a different creator is a warning
  action metadata (metadata.json beside an action's script, the interface written before the code)
    R12 error   a name that passes R10, and every input and output named, typed and described

The six workflow rules are this validator's rules, each earned by an import that was refused while building
the reference estate's content; they are not a statement of everything the appliance checks. Stdlib only, no
network, no credentials.

Usage:  python3 validate_content.py PATH [PATH ...] [--creator NAME] [--record findings.json]
        python3 validate_content.py --self-test      the shipped fixtures, compared with their expected findings
Exit:   0 no error (warnings and notes allowed) · 1 at least one error · 2 a path unreadable or a usage error
"""

import json
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
DEFAULT_CREATOR = "www.dunes.ch"


class Findings:
    def __init__(self):
        self.items = []

    def add(self, path, line, rule, level, msg):
        self.items.append({"path": str(path), "line": line, "rule": rule, "level": level, "message": msg})


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def decode(raw):
    """(text, encoding): UTF-16 when the bytes open with a byte-order mark, else UTF-8."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16"), "UTF-16"
    return raw.decode("utf-8"), "UTF-8"


# ---------------------------------------------------------------- workflows: R1 to R6
def check_workflow(text, path, f):
    for tag in ("display-name", "description"):
        for m in re.finditer(rf"<{tag}>(?!<!\[CDATA\[)([^<]+)</{tag}>", text):
            f.add(path, line_of(text, m.start()), "R1", "error", f"{tag} written as text, not in character data")
    for m in re.finditer(r"<script[^>]*>(?!<!\[CDATA\[)([^<]+)</script>", text):
        f.add(path, line_of(text, m.start()), "R1", "error", "script written as text, not in character data")
    for m in re.finditer(r'<value encoded="n">(?!<!\[CDATA\[)([^<]+)</value>', text):
        f.add(path, line_of(text, m.start()), "R1", "error", "value written as text, not in character data")

    for m in re.finditer(r'<workflow-item\b([^>]*)type="custom-condition"([^>]*)>(.*?)</workflow-item>', text, re.S):
        tag, body, at = m.group(1) + m.group(2), m.group(3), line_of(text, m.start())
        name = (re.search(r'name="([^"]+)"', tag) or [None, "?"])[1]
        if not re.search(r'(?<![\w-])out-name="', tag):
            f.add(path, at, "R2", "error", f"decision {name} names no onward item (out-name)")
        if "alt-out-name=" not in tag:
            f.add(path, at, "R2", "error", f"decision {name} names no alternative onward item (alt-out-name)")
        if "<script" not in body:
            f.add(path, at, "R2", "error", f"decision {name} has no script")
        elif "return" not in body:
            f.add(path, at, "R2", "warning", f"decision {name}: its script returns nothing")
        if "<out-binding" not in body:
            f.add(path, at, "R2", "error", f"decision {name} has no output binding element")

    for m in re.finditer(r'<position\b[^>]*>', text):
        for axis in ("x", "y"):
            v = re.search(rf'\b{axis}="([^"]+)"', m.group(0))
            if v and "." not in v.group(1):
                f.add(path, line_of(text, m.start()), "R3", "error", f'position {axis}="{v.group(1)}" is not decimal ({v.group(1)}.0)')

    declared = set(re.findall(r'<attrib name="([^"]+)"', text)) | set(re.findall(r'<param name="([^"]+)"', text)) \
        | set(re.findall(r'<out-binding>.*?export-name="([^"]+)"', text, re.S)) | {"actionResult"}
    for blk in re.finditer(r"<in-binding>(.*?)</in-binding>", text, re.S):
        for b in re.finditer(r'export-name="([^"]+)"', blk.group(1)):
            if b.group(1) not in declared:
                f.add(path, line_of(text, blk.start(1) + b.start()), "R4", "warning",
                      f"input binding names {b.group(1)}, which the workflow does not declare")

    for m in re.finditer(r'<attrib\b[^>]*type="SecureString"[^>]*>\s*<value', text):
        f.add(path, line_of(text, m.start()), "R5", "error", "a SecureString attribute carries a value element; make it self-closing")


# ---------------------------------------------------------------- actions: R10, R11
def check_action(text, root, path, f):
    name = root.get("name") or ""
    if not NAME_RE.match(name):
        f.add(path, 1, "R10", "error", f"action name {name!r} must start with a letter and hold only letters, digits and underscores")
    if not root.get("result-type"):
        f.add(path, 1, "R11", "warning", "the module declares no result type")
    for m in re.finditer(r'<param\b([^>]*?)(/>|>(.*?)</param>)', text, re.S):
        body = m.group(3) or ""
        described = re.sub(r"<!\[CDATA\[|\]\]>|<description>|</description>", "", body).strip()
        if not described:
            pn = (re.search(r'\bn="([^"]+)"', m.group(1)) or [None, "?"])[1]
            f.add(path, line_of(text, m.start()), "R11", "warning", f"parameter {pn} carries no description")


# ---------------------------------------------------------------- both: R6, R7
def check_document(text, path, f, kind_hint=None):
    """Parse, then route to the workflow or the action rules by the root element. Returns the kind found."""
    try:
        # The text is already decoded, so the declaration's encoding no longer applies; drop it, keeping its line.
        root = ET.fromstring(re.sub(r"^\ufeff?\s*<\?xml[^>]*\?>", "", text, count=1))
    except ET.ParseError as e:
        hint = "; it holds JSON, perhaps an API response saved as content" if text.lstrip().startswith(("{", "[")) else ""
        f.add(path, getattr(e, "position", (1, 0))[0], "R6", "error", f"the document does not parse: {e}{hint}")
        return kind_hint or "unparsed"
    tag = root.tag.split("}")[-1]
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", text, re.S):
        bad = re.search(r"[^\x00-\x7f]", m.group(1))
        if bad:
            f.add(path, line_of(text, m.start(1) + bad.start()), "R7", "warning",
                  f"script text holds a non-ASCII character (U+{ord(bad.group(0)):04X}); it may not survive export and import")
    if tag == "workflow":
        check_workflow(text, path, f)
        return "workflow"
    if tag == "dunes-script-module":
        check_action(text, root, path, f)
        return "action"
    f.add(path, 1, "R6", "error", f"the root element <{tag}> is neither a workflow nor an action")
    return "other"


# ---------------------------------------------------------------- packages: R8, R9
def check_package(path, f, creator):
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        head = Path(path).read_bytes()[:1].decode("latin-1")
        hint = "; it holds JSON, perhaps an API response saved as a package" if head in ("{", "[") else ""
        f.add(path, 1, "R6", "error", f"not a package: the file is not a zip archive{hint}")
        return "unparsed", None
    names = z.namelist()
    content = next((n for n in names if n in ("workflow-content", "action-content")), None)
    info = next((n for n in names if n in ("workflow-info", "action-info")), None)
    if not content:
        f.add(path, 1, "R6", "error", "the package holds no workflow-content or action-content member")
        return "unparsed", None
    text, enc = decode(z.read(content))
    kind = check_document(text, f"{path}!{content}", f)
    found_creator = None
    if info:
        props = dict(l.split("=", 1) for l in z.read(info).decode("latin-1").splitlines() if "=" in l and not l.startswith("#"))
        declared = (props.get("charset") or "").upper()
        if declared and declared.replace("-", "") != enc.replace("-", ""):
            f.add(path, 1, "R8", "error", f"the info member declares charset {declared}, but the content member is {enc}")
        found_creator = props.get("creator") or ""
        if creator and found_creator != creator:
            f.add(path, 1, "R9", "warning", f"creator is {found_creator!r}, not {creator!r}")
        else:
            f.add(path, 1, "R9", "note", f"creator {found_creator!r}" + (" (the platform's default)" if found_creator == DEFAULT_CREATOR else ""))
    return kind, found_creator


# ---------------------------------------------------------------- action metadata: R12
def check_metadata(path, f):
    try:
        meta = json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        f.add(path, 1, "R12", "error", f"metadata.json does not read as JSON: {e}")
        return
    if not NAME_RE.match(str(meta.get("name") or "")):
        f.add(path, 1, "R12", "error", f"name {meta.get('name')!r} does not pass the action name rule")
    for side in ("inputs", "outputs"):
        for i, item in enumerate(meta.get(side) or []):
            missing = [k for k in ("name", "type", "description") if not str(item.get(k) or "").strip()]
            if missing:
                f.add(path, 1, "R12", "error", f"{side}[{i}] has no {', '.join(missing)}")


def scan(paths, creator=None):
    f, kinds, creators = Findings(), Counter(), Counter()
    unreadable = False
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(x for x in p.rglob("*") if x.is_file())
        elif p.is_file():
            files.append(p)
        else:
            print(f"validate_content.py: {p} does not exist", file=sys.stderr)
            unreadable = True
    for x in files:
        name = x.name
        try:
            if name.endswith((".workflow", ".action")):
                kind, cr = check_package(x, f, creator)
                kinds[f"{kind} package"] += 1
                if cr is not None:
                    creators["the platform's default" if cr == DEFAULT_CREATOR else "another"] += 1
            elif name == "metadata.json":
                check_metadata(x, f)
                kinds["action metadata"] += 1
            elif name.endswith(".xml"):
                text, _ = decode(x.read_bytes())
                kinds[f"{check_document(text, x, f)} document"] += 1
        except (OSError, UnicodeDecodeError) as e:
            f.add(x, 1, "R6", "error", f"unreadable: {type(e).__name__}")
    return f, kinds, creators, unreadable


def report(f, kinds, creators):
    for it in f.items:
        print(f"{it['path']}:{it['line']}: {it['rule']} {it['level']}: {it['message']}")
    by = Counter((it["rule"], it["level"]) for it in f.items)
    print(f"\nscanned: {dict(sorted(kinds.items()))}")
    print(f"findings: {', '.join(f'{r} {lv} {n}' for (r, lv), n in sorted(by.items())) or 'none'}")
    if creators:
        print(f"creators: {dict(sorted(creators.items()))}")


def record(path, f, kinds, creators):
    rec = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "scanned": dict(sorted(kinds.items())),
           "findings": {f"{r} {lv}": n for (r, lv), n in sorted(Counter((it["rule"], it["level"]) for it in f.items).items())},
           "creators": dict(sorted(creators.items()))}
    Path(path).write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path}: counts by kind and rule, no file name, no content")


def build_packages(dst):
    """The packaged fixtures ship as text members, so the repository holds no binary; zip them here, each
    content member in UTF-16 with a byte-order mark and each info member in Latin-1, as the appliance writes them."""
    for d in sorted((HERE / "fixtures" / "packages").iterdir()):
        if d.is_dir() and d.suffix in (".action", ".workflow"):
            with zipfile.ZipFile(dst / d.name, "w") as z:
                for m in sorted(d.iterdir()):
                    text = m.read_text(encoding="utf-8")
                    z.writestr(m.name, text.encode("utf-16") if m.name.endswith("-content") else text.encode("latin-1"))


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        build_packages(Path(tmp))
        f, kinds, creators, _ = scan([HERE / "fixtures", tmp])
    got = sorted((Path(it["path"].split("!")[0]).name, it["line"], it["rule"], it["level"]) for it in f.items)
    want = sorted(tuple(x) for x in json.loads((HERE / "fixtures" / "expected.json").read_text(encoding="utf-8")))
    if got == want:
        errs = sum(1 for it in f.items if it["level"] == "error")
        print(f"self-test OK: {sum(kinds.values())} fixture files reproduce the {len(want)} expected findings exactly "
              f"({errs} errors), offline")
        return 0
    print("self-test FAILED: the findings differ from fixtures/expected.json")
    for x in sorted(set(got) ^ set(want)):
        print(("  unexpected " if x in got else "  missing    ") + ":".join(map(str, x)))
    return 1


def main(argv):
    if argv == ["--self-test"]:
        return self_test()
    creator = out = None
    paths = []
    it = iter(argv)
    for a in it:
        if a == "--creator":
            creator = next(it, None)
        elif a == "--record":
            out = next(it, None)
        elif a.startswith("--"):
            print(f"validate_content.py: unknown option {a}", file=sys.stderr)
            return 2
        else:
            paths.append(a)
    if not paths or (("--creator" in argv) and not creator) or (("--record" in argv) and not out):
        print(__doc__.split("Usage:")[1].split("Exit:")[0].strip(), file=sys.stderr)
        return 2
    f, kinds, creators, unreadable = scan(paths, creator)
    report(f, kinds, creators)
    if out:
        record(out, f, kinds, creators)
    if unreadable:
        return 2
    return 1 if any(it["level"] == "error" for it in f.items) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
