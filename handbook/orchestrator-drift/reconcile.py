#!/usr/bin/env python3
"""reconcile.py - keep a committed copy of a workflow in step with the one Orchestrator is running.

The running definition is the authority: it is what executes. This keeps a version-controlled copy of it, in a
normalized form (keys sorted, indented) so an unchanged workflow fetched twice leaves no diff, and tells you the
day the two stop agreeing:

  --fetch           the running definition -> <dir>/<name>.json        (reads; seeds or refreshes the copy)
  --diff            the copy against the running definition             (reads; exit 1 when they differ)
  --deploy          the copy -> the running definition, as a plan        (reads; shows what would be sent)
  --deploy --apply  sends it: references and in-flight executions checked first, then PUT /content, then read back

WORKFLOW is the workflow's id or its exact name. Each operation is one appliance call or two: fetch and diff read
GET /workflows/{id}/content. The deploy first checks that every action the copy's scripts call
(System.getModule("<module>").<name>) is in GET /actions and that every configuration element its attributes read
answers GET /configurations/{id} with the key named; then it counts executions (GET /workflows/{id}/executions), and
an execution in any state but completed, failed or canceled counts as in flight. A nested workflow call is not
checked.
Stdlib only.

Env:   VRO_HOST; VRO_TOKEN_FILE, a bearer this appliance accepts in a file of mode 0600 (VRO_TOKEN, the value itself,
       is still read when no file is named); the embedded Orchestrator and a standalone one each take their own
       bearer, so mint it where that appliance expects
Usage: python3 reconcile.py WORKFLOW --fetch|--diff|--deploy [--apply [--allow-inflight]] [--dir canonical]
                            [--record drift.json]
       python3 reconcile.py --self-test       the normalization and the diff, on the shipped fixtures, offline
Exit:  0 in agreement, or the operation done · 1 drift found · 2 usage error · 3 a call failed or a deploy did not
       read back as sent · 4 a pre-flight check refused the deploy (nothing sent): the copy names an action or
       configuration element the appliance lacks, or an execution has not ended and --allow-inflight was not given
"""

import difflib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = "/vco/api"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# The executions list answers states in lower case (completed, failed). Any state that is not one of these ends counts
# as in flight, so a state this script has never seen errs toward caution.
TERMINAL = ("completed", "failed", "canceled", "cancelled")
SHOW = 60  # diff lines printed; the record counts every line


def secret(name):
    """A secret from NAME_FILE (a file, mode 0600, its value stripped) or else NAME itself; None when neither is set.
    A file open to group or other is refused before it is read; the refusal names the variable and the fix."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            mode = os.fstat(f.fileno()).st_mode & 0o777
            # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
            if mode & 0o077 and os.name != "nt":
                raise PermissionError(f"{name}_FILE names a file of mode {mode:04o}, open to group or other: "
                                      f'run chmod 600 "${name}_FILE" and try again (the file was not read)')
            return f.read().strip()
    return os.environ.get(name) or None


def normalize(obj):
    """The committed form: keys sorted and indented, so key order in the appliance's answer, which carries no meaning,
    never shows up as a change."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


def drift_lines(committed, running, limit=None):
    """The unified diff between the committed text and the running definition's normalized text, every line or at
    most `limit`; empty when they agree."""
    if committed == running:
        return []
    return list(difflib.unified_diff(committed.splitlines(), running.splitlines(),
                                     fromfile="committed", tofile="running", lineterm=""))[:limit]


CALL = re.compile(r'System\.getModule\("([^"]+)"\)\.([A-Za-z_][A-Za-z0-9_]*)')


def strings(obj):
    """Every string inside a decoded JSON document."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def references(doc):
    """(actions, configuration references) a workflow definition depends on: the module/name of every action its
    scripts call, and (config-id, config-key) for every attribute that reads a configuration element."""
    calls = sorted({f"{m}/{n}" for text in strings(doc.get("workflow-item")) for m, n in CALL.findall(text)})
    confs = sorted({(r.get("config-id"), r.get("config-key")) for a in doc.get("attrib") or []
                    for r in [(a.get("value") or {}).get("attribute-reference")] if r})
    return calls, confs


def link_attrs(answer):
    """The attribute maps of a link list, whichever of its two wrappings the answer uses."""
    rel = (answer or {}).get("relations")
    links = rel.get("link", []) if isinstance(rel, dict) else (answer or {}).get("link", [])
    return [{a.get("name"): a.get("value") for a in lk.get("attributes", [])} for lk in (links or [])]


def inflight(answer):
    """How many executions in a GET /workflows/{id}/executions answer have not ended."""
    return sum(1 for m in link_attrs(answer) if m.get("state") and m["state"].lower() not in TERMINAL)


class Vro:
    def __init__(self, host, token):
        self.host, self.token = host, token
        self.ctx = ssl.create_default_context()
        if os.environ.get("TLS_VERIFY", "true").strip().lower() in ("0", "false", "no", "off"):
            self.ctx.check_hostname, self.ctx.verify_mode = False, ssl.CERT_NONE

    def call(self, method, path, body=None):
        h = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        data = None
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        req = urllib.request.Request(f"https://{self.host}{BASE}{path}", data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=120) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, None

    def resolve(self, workflow):
        """(id, name) for an id or an exact name."""
        if UUID.match(workflow):
            st, c = self.call("GET", f"/workflows/{workflow}/content")
            if st != 200:
                raise RuntimeError(f"the workflow did not answer (HTTP {st})")
            return workflow, c.get("display-name") or workflow
        q = urllib.parse.quote(f"name~{workflow}")
        st, j = self.call("GET", f"/workflows?conditions={q}&maxResult=100")
        if st != 200:
            raise RuntimeError(f"the workflow list answered HTTP {st}")
        rows = [{a["name"]: a.get("value") for a in li.get("attributes", [])} for li in (j or {}).get("link", [])]
        hits = [r for r in rows if r.get("name") == workflow]
        if len(hits) != 1:
            raise LookupError(f"{len(hits)} workflows carry that exact name; pass the id instead")
        return hits[0]["id"], workflow


def shape(doc):
    """What the record keeps of a definition: its version and how many items and attributes it holds."""
    return {"version": doc.get("version"), "items": len(doc.get("workflow-item") or []),
            "attributes": len(doc.get("attrib") or [])}


def safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "workflow"


def run(args):
    host, token = os.environ.get("VRO_HOST"), secret("VRO_TOKEN")
    if not host or not token:
        print("reconcile.py: set VRO_HOST and VRO_TOKEN_FILE (or VRO_TOKEN)", file=sys.stderr)
        return 2
    v = Vro(host, token)
    wid, name = v.resolve(args["workflow"])
    copy = Path(args["dir"]) / f"{safe(name)}.json"
    rec = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "operation": args["op"]}

    st, live = v.call("GET", f"/workflows/{wid}/content")
    if st != 200:
        raise RuntimeError(f"GET /content answered HTTP {st}")
    running = normalize(live)
    rec["items"] = len(live.get("workflow-item") or [])

    if args["op"] == "fetch":
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(running + "\n", encoding="utf-8")
        print(f"fetched the running definition -> {copy}  (version {live.get('version')}, {rec['items']} items)")
        rc = 0
    elif args["op"] == "diff":
        if not copy.exists():
            print(f"no committed copy at {copy}: run --fetch first")
            return 1
        text = copy.read_text(encoding="utf-8").rstrip("\n")
        lines = drift_lines(text, running)
        shown = lines[:SHOW]
        mine = json.loads(text)
        rec.update({"drift": bool(lines), "diffLines": len(lines), "diffLinesShown": len(shown),
                    "committed": shape(mine), "running": shape(live)})
        if lines:
            print(f"DRIFT: the committed copy (version {mine.get('version')}, {rec['committed']['items']} items) and the "
                  f"running definition (version {live.get('version')}, {rec['running']['items']} items) differ")
            for ln in shown:
                print("  " + ln)
            if len(lines) > len(shown):
                print(f"  ... {len(lines) - len(shown)} more diff line(s)")
        else:
            print(f"IN AGREEMENT: the committed copy is the running definition (version {live.get('version')})")
        rc = 1 if lines else 0
    else:
        if not copy.exists():
            print(f"no committed copy at {copy}: nothing to deploy")
            return 2
        payload = json.loads(copy.read_text(encoding="utf-8"))
        if payload.get("id") != wid:
            print("reconcile.py: the committed copy names a different workflow id; refusing to deploy it here", file=sys.stderr)
            return 2
        calls, confs = references(payload)
        st_a, acts = v.call("GET", "/actions")
        if st_a != 200:
            raise RuntimeError(f"GET /actions answered HTTP {st_a}")
        have = {m.get("fqn") for m in link_attrs(acts)}
        missing_a = [c for c in calls if c not in have]
        missing_c = 0
        for cid, key in confs:
            st_c, conf = v.call("GET", f"/configurations/{urllib.parse.quote(str(cid))}")
            if st_c != 200 or key not in {a.get("name") for a in (conf or {}).get("attributes") or []}:
                missing_c += 1
        rec["references"] = {"actions": len(calls), "actionsMissing": len(missing_a),
                             "configurationReads": len(confs), "configurationReadsMissing": missing_c}
        print(f"references: {len(calls) - len(missing_a)} of {len(calls)} action(s) present; "
              f"{len(confs) - missing_c} of {len(confs)} configuration read(s) resolve")
        for c in missing_a:
            print(f"  missing action {c}")
        if missing_a or missing_c:
            print("REFUSED: the copy depends on content this appliance lacks; create it first (nothing was sent)")
            if args["record"]:
                Path(args["record"]).write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
            return 4
        st_e, ex = v.call("GET", f"/workflows/{wid}/executions")
        rec["inflight"] = inflight(ex) if st_e == 200 else f"HTTP {st_e}"
        lines = drift_lines(running, normalize(payload))
        rec["changedLines"] = len(lines)
        print(f"pre-flight: {rec['inflight']} execution(s) not ended; {len(lines)} diff line(s) to send")
        if not lines:
            print(f"NOTHING TO SEND: the running definition already is the committed copy (version {live.get('version')})")
            rc = 0
        elif args["apply"] and rec["inflight"] != 0 and not args["allow_inflight"]:
            print("REFUSED: an execution has not ended, or the executions list did not answer; let it finish, or "
                  "pass --allow-inflight to send anyway (nothing was sent)")
            rc = 4
        elif not args["apply"]:
            print(f"PLAN: would PUT the committed copy (version {payload.get('version')}) as the running definition; "
                  f"re-run with --apply to send it")
            rc = 0
        else:
            st_p, _ = v.call("PUT", f"/workflows/{wid}/content", payload)
            st_r, back = v.call("GET", f"/workflows/{wid}/content")
            same = st_r == 200 and normalize(back) == normalize(payload)
            rec.update({"putStatus": st_p, "readBackMatches": same})
            print(f"PUT /content -> HTTP {st_p}; read back {'matches the copy' if same else 'DOES NOT match the copy'}")
            rc = 0 if st_p in (200, 202, 204) and same else 3
    if args["record"]:
        Path(args["record"]).write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {args['record']}: the operation and its counts, no name and no id")
    return rc


def self_test():
    fx = HERE / "fixtures"
    committed = normalize(json.loads((fx / "committed.json").read_text(encoding="utf-8")))
    reordered = normalize(json.loads((fx / "running-reordered.json").read_text(encoding="utf-8")))
    edited = normalize(json.loads((fx / "running-edited.json").read_text(encoding="utf-8")))
    a, b = drift_lines(committed, reordered), drift_lines(committed, edited)
    runs = inflight(json.loads((fx / "executions.json").read_text(encoding="utf-8")))
    calls, confs = references(json.loads((fx / "committed.json").read_text(encoding="utf-8")))
    ok = not a and b and any(ln.startswith("+") and "50.0" in ln for ln in b) and \
        any(ln.startswith("-") and "30.0" in ln for ln in b) and runs == 2 and \
        calls == ["com.example.platform.util/clamp"] and confs == [("11111111-2222-3333-4444-555555555555", "threshold")]
    if ok:
        print(f"self-test OK: a definition with its keys reordered normalizes to the committed copy (no diff), one "
              f"edited value shows as a {len(b)}-line diff, of five listed executions the {runs} not ended count as in "
              f"flight, and the {len(calls)} action call and {len(confs)} configuration read the deploy checks are "
              f"found, offline")
        return 0
    print(f"self-test FAILED: normalization, the diff or the in-flight count ({runs}, expected 2) did not behave as "
          f"the fixtures expect")
    return 1


def main(argv):
    if argv == ["--self-test"]:
        return self_test()
    args = {"workflow": None, "op": None, "apply": False, "allow_inflight": False, "dir": "canonical", "record": None}
    it = iter(argv)
    for a in it:
        if a in ("--fetch", "--diff", "--deploy"):
            if args["op"]:
                print("reconcile.py: one operation at a time", file=sys.stderr)
                return 2
            args["op"] = a[2:]
        elif a == "--apply":
            args["apply"] = True
        elif a == "--allow-inflight":
            args["allow_inflight"] = True
        elif a in ("--dir", "--record"):
            val = next(it, None)
            if not val:
                print(f"reconcile.py: {a} needs a value", file=sys.stderr)
                return 2
            args[a[2:]] = val
        elif a.startswith("--"):
            print(f"reconcile.py: unknown option {a}", file=sys.stderr)
            return 2
        elif args["workflow"] is None:
            args["workflow"] = a
        else:
            print("reconcile.py: one workflow at a time", file=sys.stderr)
            return 2
    if not args["workflow"] or not args["op"] or (args["apply"] and args["op"] != "deploy") or \
            (args["allow_inflight"] and not args["apply"]):
        print(__doc__.split("Usage:")[1].split("Exit:")[0].strip(), file=sys.stderr)
        return 2
    try:
        return run(args)
    except (PermissionError, FileNotFoundError) as e:
        print(f"reconcile.py: {e}", file=sys.stderr)
        return 2
    except (RuntimeError, LookupError, urllib.error.URLError, OSError) as e:
        print(f"reconcile.py: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
