#!/usr/bin/env python3
"""broker.py: the grant record, the broker's two gates and the scope reconciler, as a reference you can read and run.

Temporary elevation on VCF Automation is a design the platform has no primitive for; elevation.py enumerates that
absence. This is the smallest working shape of the design, as four commands:

  grant      The approval writes a grant record: who, which axis, what, until when, approved by whom and why. An action
             grant re-enables a destructive Day-2 action on the member's own deployments. A scope grant raises a
             project role, and records the role the member holds now as the baseline its revert returns to: recorded
             at approval, never at elevation, so an overlapping grant cannot record an already-raised role. A scope
             grant is refused for a non-member, for a member already at or above the role, and while another live
             scope grant covers the same member in the same project. The record is a local JSON file; nothing on the
             platform changes.
  check      The broker's decision, in the order that is the design. First ownership, which is absolute: the caller
             is resolved from the caller's own sign-in, the deployment's owner is read by the broker's service
             identity, and a caller who does not own the deployment is refused whatever grants they hold, so an
             elevation can never reach somebody else's resource. Then, for a destructive action only, a grant that is
             live now and names the caller and the action. It prints the verdict and executes nothing: your executor
             runs the action as the service identity only after this says ALLOW.
  reconcile  For scope grants: compare each binding's role with what its grant says it should be (the granted role
             while the window is open, the recorded baseline once it has closed or been revoked) and print the plan.
             With --apply, write each difference in place with one server-side apply, read the object back, and write
             a heartbeat. A failed write leaves the grant as it was, so the next pass tries again.
  heartbeat  Exits 1 when the last applied reconcile pass is older than --max-age-minutes, or failed. This is the
             alert worth having: every other failure in this design is safe, and a reconciler that stopped is not.

The grants file is the broker's authority, so a file anyone else can write is refused, as is a secret file open to
group or other. No dry-run flag is ever sent: on this plane a server-side dry run applies the change.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<service-identity> VCFA_PASSWORD_FILE=~/.secrets/broker       # mode 0600; the broker's identity
  export CALLER_USER=<member> CALLER_PASSWORD_FILE=~/.secrets/member             # mode 0600; check only: who asks
  export GRANTS_FILE=~/.elevation/grants.json HEARTBEAT_FILE=~/.elevation/heartbeat.json
  export TLS_VERIFY=false                                                        # only on a self-signed lab CA
  python3 broker.py grant --principal <member> --action Deployment.Delete --hours 4 --approver <you> --reason "<why>"
  python3 broker.py grant --principal <member> --scope --project <project> --role edit_adv --hours 2 \\
          --approver <you> --reason "<why>"                   # add --group when the principal is a group
  python3 broker.py revoke --id <grant id> --by <you>
  python3 broker.py check --deployment <deployment id> --action Deployment.Delete
  python3 broker.py reconcile                                 # the plan; add --apply to write
  python3 broker.py heartbeat --max-age-minutes 10
Exit: 0 written, allowed, nothing due, or a fresh heartbeat · 1 refused (grant), denied (check), a revert due or a write
      failed (reconcile), stale or failed (heartbeat) · 2 a setting or argument is missing, or a file's mode is refused
      · 3 a sign-in or a read failed
"""
import base64
import datetime as dt
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

AUTHZ = "authorization.cci.vmware.com/v1alpha1"
# The reviewable allow-list of destructive Day-2 actions. Any other action on the caller's own deployment needs no
# grant; these need a live one. Extend it in review, never per deployment.
DESTRUCTIVE = frozenset({"Deployment.Delete", "Deployment.PowerOff"})
ROLE_LADDER = ("view", "edit", "edit_adv", "admin")
MAX_HOURS = float(os.environ.get("ELEVATION_MAX_HOURS", "8"))


class ReadFailed(Exception):
    """A sign-in or a read the decision depends on did not succeed."""


class Refused(Exception):
    """A grant the approval must not write, with the reason."""


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def read_secret(var):
    """The secret in the file VAR names. A file open to group or other is refused before it is read; the refusal
    names the variable and the fix, never the file's content."""
    with open(os.environ[var], encoding="utf-8") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"{var} names a file of mode {mode:04o}, open to group or other: "
                                  f'run chmod 600 "${var}" and try again (the file was not read)')
        return f.read().strip()


class Session:
    """A session login to VCF Automation as USER@ORG; requests go out with its bearer."""

    def __init__(self, user_var, password_var):
        self.host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
        user, password = os.environ[user_var], read_secret(password_var)
        basic = base64.b64encode(f"{user}@{org}:{password}".encode()).decode()
        rq = urllib.request.Request(f"https://{self.host}/cloudapi/1.0.0/sessions", method="POST",
                                    headers={"Authorization": f"Basic {basic}",
                                             "Accept": "application/json;version=9.1.0"})
        try:
            with urllib.request.urlopen(rq, context=ctx(), timeout=30) as r:
                self.bearer = next(v for k, v in r.headers.items() if k.lower() == "x-vmware-vcloud-access-token")
        except urllib.error.HTTPError as e:
            raise ReadFailed(f"the sign-in as {user_var} answered HTTP {e.code}") from None

    def request(self, method, path, body=None, ctype="application/json", accept="application/json"):
        """(status, parsed body or None). A transport failure raises ReadFailed."""
        rq = urllib.request.Request(f"https://{self.host}{path}", method=method,
                                    data=json.dumps(body).encode() if body is not None else None,
                                    headers={"Authorization": f"Bearer {self.bearer}", "Accept": accept,
                                             **({"Content-Type": ctype} if body is not None else {})})
        try:
            with urllib.request.urlopen(rq, context=ctx(), timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, None
        except (urllib.error.URLError, OSError) as e:
            raise ReadFailed(f"{method} {path.split('?')[0]}: {e}") from None


# ---------------------------------------------------------------- the grants file
def grants_path():
    return os.environ["GRANTS_FILE"]


def load_grants():
    """The grants, or [] when the file does not exist yet. A file others can write is refused: whoever can write it
    can mint a grant, and the approval is the only thing that may."""
    path = grants_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        if mode & 0o022 and os.name != "nt":
            raise PermissionError(f"GRANTS_FILE is mode {mode:04o}, writable by group or other: whoever can write it "
                                  f'can mint a grant. Run chmod 600 "$GRANTS_FILE"')
        return json.load(f)


def save_grants(grants):
    """Write atomically, mode 0600."""
    path = grants_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(grants, f, indent=1)
    os.replace(tmp, path)


def is_live(g, now):
    return g["state"] == "ACTIVE" and now < parse(g["expiresAt"])


# ---------------------------------------------------------------- bindings (the scope axis)
def binding_name(kind, subject):
    return f"cci:{kind.lower()}:{subject}"


def binding_path(project, kind, subject):
    return (f"/cci/kubernetes/apis/{AUTHZ}/namespaces/{urllib.parse.quote(project, safe='')}/projectrolebindings/"
            f"{urllib.parse.quote(binding_name(kind, subject), safe='')}")


def binding_role(svc, project, kind, subject):
    """The subject's role in the project, None when it has no binding. Read directly: a listing was seen stale."""
    st, b = svc.request("GET", binding_path(project, kind, subject))
    if st == 404:
        return None
    if st != 200:
        raise ReadFailed(f"the binding read answered HTTP {st}")
    return (b.get("roleRef") or {}).get("name")


def set_binding_role(svc, project, kind, subject, role):
    """One server-side apply in place, then a direct read. Returns the role read back."""
    body = {"apiVersion": AUTHZ, "kind": "ProjectRoleBinding",
            "metadata": {"name": binding_name(kind, subject), "namespace": project},
            "roleRef": {"apiGroup": "authorization.cci.vmware.com", "kind": "ProjectRole", "name": role},
            "subjects": [{"kind": kind, "name": f"{subject}@" if kind == "Group" else subject}]}
    st, _ = svc.request("PATCH", binding_path(project, kind, subject) + "?fieldManager=elevation-broker&force=true",
                        body, ctype="application/apply-patch+yaml")
    if st not in (200, 201):
        raise ReadFailed(f"the role write answered HTTP {st}")
    return binding_role(svc, project, kind, subject)


# ---------------------------------------------------------------- the commands
def cmd_grant(a, svc_factory, now):
    if not a.get("--reason", "").strip():
        raise KeyError("--reason is required: a grant with no reason is not an approval")
    for flag in ("--principal", "--approver", "--hours"):
        if not a.get(flag):
            raise KeyError(f"{flag} is required")
    hours = float(a["--hours"])
    if not 0 < hours <= MAX_HOURS:
        raise Refused(f"--hours must be above 0 and at most {MAX_HOURS:g} (ELEVATION_MAX_HOURS)")
    grants = load_grants()
    g = {"id": uuid.uuid4().hex[:12], "principal": a["--principal"], "approver": a["--approver"],
         "reason": a["--reason"].strip(), "grantedAt": iso(now), "expiresAt": iso(now + dt.timedelta(hours=hours)),
         "state": "ACTIVE"}
    if "--scope" in a:
        for flag in ("--project", "--role"):
            if not a.get(flag):
                raise KeyError(f"a scope grant needs {flag}")
        kind = "Group" if "--group" in a else "User"
        role = a["--role"]
        if role not in ROLE_LADDER:
            raise KeyError(f"--role must be one of {', '.join(ROLE_LADDER)}")
        if any(x.get("axis") == "scope" and x["project"] == a["--project"] and x["principal"] == g["principal"]
               and x.get("subjectKind") == kind and (is_live(x, now) or not x.get("reverted", True)) for x in grants):
            raise Refused("another scope grant for this member in this project is live or not yet reverted: its "
                          "baseline would be overwritten by an already-raised role")
        baseline = binding_role(svc_factory(), a["--project"], kind, g["principal"])
        if baseline is None:
            raise Refused("the member has no binding in this project, so there is nothing to raise and no baseline")
        if baseline not in ROLE_LADDER or ROLE_LADDER.index(baseline) >= ROLE_LADDER.index(role):
            raise Refused(f"the member already holds {baseline!r}, which is not below {role!r}")
        g.update(axis="scope", project=a["--project"], subjectKind=kind, role=role, baselineRole=baseline,
                 reverted=False)
    else:
        actions = [x for x in (a.get("--action") or "").split(",") if x]
        if not actions:
            raise KeyError("an action grant needs --action (comma-separated, e.g. Deployment.Delete)")
        unknown = [x for x in actions if x not in DESTRUCTIVE]
        if unknown:
            raise Refused(f"{unknown} are not on the destructive allow-list, so they need no grant")
        g.update(axis="action", actions=actions)
    grants.append(g)
    save_grants(grants)
    what = (f"{g['role']} in {g['project']}, baseline {g['baselineRole']}" if g["axis"] == "scope"
            else ", ".join(g["actions"]) + " on their own deployments")
    print(f"GRANTED {g['id']}: {g['principal']}, {what}, until {g['expiresAt']}; approved by {g['approver']}")
    return 0


def cmd_revoke(a, now):
    if not (a.get("--id") and a.get("--by")):
        raise KeyError("revoke needs --id and --by")
    grants = load_grants()
    g = next((x for x in grants if x["id"] == a["--id"]), None)
    if g is None:
        raise KeyError(f"no grant {a['--id']}")
    g.update(state="REVOKED", revokedAt=iso(now), revokedBy=a["--by"])
    save_grants(grants)
    tail = "; the next reconcile reverts its binding" if g.get("axis") == "scope" else ""
    print(f"REVOKED {g['id']}{tail}")
    return 0


def cmd_check(a, svc_factory, caller_factory, now):
    if not (a.get("--deployment") and a.get("--action")):
        raise KeyError("check needs --deployment and --action")
    caller_session = caller_factory()
    st, cur = caller_session.request("GET", "/cloudapi/1.0.0/sessions/current",
                                     accept="application/json;version=9.1.0")
    caller = ((cur or {}).get("user") or {}).get("name") if st == 200 else None
    if not caller:
        raise ReadFailed(f"the caller's own session did not say who it is (HTTP {st})")
    st, dep = svc_factory().request("GET", f"/deployment/api/deployments/{urllib.parse.quote(a['--deployment'])}")
    if st == 404:
        print(f"DENY: no deployment {a['--deployment']} is visible to the broker")
        return 1
    if st != 200:
        raise ReadFailed(f"the deployment read answered HTTP {st}")
    owner, action = (dep or {}).get("ownedBy"), a["--action"]
    if owner != caller:
        print(f"DENY: {caller} does not own this deployment; ownership comes before any grant")
        return 1
    if action not in DESTRUCTIVE:
        print(f"ALLOW: {caller} owns the deployment, and {action} is not on the destructive list, so no grant is needed")
        return 0
    live = [g for g in load_grants() if g.get("axis") == "action" and is_live(g, now) and g["principal"] == caller
            and action in g["actions"]]
    if not live:
        print(f"DENY: {caller} owns the deployment, and no live grant covers {action}")
        return 1
    g = max(live, key=lambda x: x["expiresAt"])
    print(f"ALLOW: {caller} owns the deployment, and grant {g['id']} covers {action} until {g['expiresAt']}")
    return 0


def cmd_reconcile(a, svc_factory, now):
    apply = "--apply" in a
    grants = load_grants()
    scope = [g for g in grants if g.get("axis") == "scope" and not g.get("reverted")]
    svc = svc_factory() if scope else None
    due = failed = changed = 0
    for g in scope:
        live = is_live(g, now)
        want = g["role"] if live else g["baselineRole"]
        try:
            have = binding_role(svc, g["project"], g["subjectKind"], g["principal"])
        except ReadFailed as e:
            print(f"  {g['id']}  read failed: {e}")
            failed += 1
            continue
        label = f"{g['id']}  {g['principal']} in {g['project']}: {have} -> {want}"
        if have is None:
            # The binding has gone since the grant was written. Writing would create access the member no longer
            # has, so nothing is written, and an expired grant counts as reverted.
            if not live:
                g.update(reverted=True, state="EXPIRED" if g["state"] == "ACTIVE" else g["state"])
            print(f"  {g['id']}  {g['principal']} in {g['project']}: no binding any more; nothing written")
            continue
        if have == want:
            if not live:
                g.update(reverted=True, state="EXPIRED" if g["state"] == "ACTIVE" else g["state"])
            print(f"  {g['id']}  {g['principal']} in {g['project']}: at {have}, "
                  f"{'in step' if live else 'reverted'}")
            continue
        if not live:
            due += 1
        if not apply:
            print(f"  {label}  ({'REVERT DUE' if not live else 'raise pending'}; plan only)")
            continue
        try:
            got = set_binding_role(svc, g["project"], g["subjectKind"], g["principal"], want)
        except ReadFailed as e:
            print(f"  {label}  WRITE FAILED: {e}; left for the next pass")
            failed += 1
            continue
        if got != want:
            print(f"  {label}  READ BACK {got!r}; left for the next pass")
            failed += 1
            continue
        changed += 1
        if not live:
            due -= 1
            g.update(reverted=True, state="EXPIRED" if g["state"] == "ACTIVE" else g["state"])
        print(f"  {label}  written, read back")
    if apply:
        save_grants(grants)
        hb = {"completedUtc": iso(now), "ok": failed == 0, "written": changed, "failed": failed}
        path = os.environ["HEARTBEAT_FILE"]
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(hb, f)
    print(f"reconcile: {len(scope)} scope grant(s) open, {changed} written, {due} revert(s) due, {failed} failed"
          + ("" if apply else "; plan only, nothing written"))
    return 1 if (failed or due) else 0


def cmd_heartbeat(a, now):
    limit = float(a.get("--max-age-minutes") or 10)
    path = os.environ["HEARTBEAT_FILE"]
    if not os.path.exists(path):
        print("STALE: no applied reconcile pass has been recorded")
        return 1
    hb = json.load(open(path, encoding="utf-8"))
    age = (now - parse(hb["completedUtc"])).total_seconds() / 60
    if not hb.get("ok"):
        print(f"FAILED: the last pass, {age:.0f} min ago, had {hb.get('failed')} failure(s)")
        return 1
    if age > limit:
        print(f"STALE: the last pass completed {age:.0f} min ago, beyond {limit:g}")
        return 1
    print(f"FRESH: the last pass completed {age:.0f} min ago, within {limit:g}")
    return 0


COMMANDS = {"grant": {"--principal", "--action", "--scope", "--project", "--role", "--group", "--hours",
                      "--approver", "--reason"},
            "revoke": {"--id", "--by"}, "check": {"--deployment", "--action"}, "reconcile": {"--apply"},
            "heartbeat": {"--max-age-minutes"}}
SWITCHES = {"--scope", "--group", "--apply"}


def parse_args(argv):
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        print(__doc__)
        raise SystemExit(0 if argv and argv[0] in ("-h", "--help") else 2)
    cmd, rest, out, i = argv[0], argv[1:], {}, 0
    while i < len(rest):
        k = rest[i]
        if k not in COMMANDS[cmd]:
            raise KeyError(f"{cmd} does not take {k}")
        if k in SWITCHES:
            out[k] = True
            i += 1
            continue
        if i + 1 >= len(rest):
            raise KeyError(f"{k} needs a value")
        out[k] = rest[i + 1]
        i += 2
    return cmd, out


def main(argv=None, svc_factory=None, caller_factory=None, now=None):
    cmd, a = parse_args(sys.argv[1:] if argv is None else argv)
    now = now or now_utc()
    svc_factory = svc_factory or (lambda: Session("VCFA_USER", "VCFA_PASSWORD_FILE"))
    caller_factory = caller_factory or (lambda: Session("CALLER_USER", "CALLER_PASSWORD_FILE"))
    if cmd == "grant":
        return cmd_grant(a, svc_factory, now)
    if cmd == "revoke":
        return cmd_revoke(a, now)
    if cmd == "check":
        return cmd_check(a, svc_factory, caller_factory, now)
    if cmd == "reconcile":
        return cmd_reconcile(a, svc_factory, now)
    return cmd_heartbeat(a, now)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refused as e:
        print(f"REFUSED: {e}")
        sys.exit(1)
    except (KeyError, PermissionError, ValueError) as e:
        print(f"broker.py: {e}", file=sys.stderr)
        sys.exit(2)
    except (ReadFailed, urllib.error.URLError, OSError) as e:
        print(f"READ FAILED: {e}", file=sys.stderr)
        sys.exit(3)
