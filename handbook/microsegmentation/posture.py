#!/usr/bin/env python3
"""posture.py: what security posture does this org actually have, and what can it enforce?

The chapter teaches a chain: strategies bundled into profiles, attached per VPC, with sections and
groups underneath. Every link of that chain reads perfectly on an org that cannot enforce any of it,
which is the thing this script exists to tell you before you design against it.

It asks four questions, in the order that saves the most time:

  1. WHAT IS ENTITLED. `regionnetworkingcapabilities/<region>` carries a capability list with a state
     and, where the state is false, the platform's own reason and the licence it wants. This is the
     PRE-WRITE read. The chapter's "Realized" check is a post-write verification and it cannot tell
     you that a write was never going to be accepted.

     One shape trap, and it is not the one you would guess. The capability list sits at the TOP
     LEVEL of the object, beside `metadata`, and not under `spec` or `status` where a Kubernetes
     reader looks first. Read the wrong key and the object comes back looking empty, which reads as
     "this region reports no capabilities" rather than as "you looked in the wrong place". The list
     view carries it too, so this is about where you look, not which call you make.

     Step 4 has the trap that IS about which call you make.

  2. THE STRATEGY LADDER. Not one strategy but several, and the differences between them are the
     design decision. Printed with each one's own description, verbatim, because a paraphrase of a
     security posture is how a reader ends up enforcing a different one than they read about.

  3. THE POSTURE, PER VPC. Which profile each VPC is attached to, which strategies that profile
     carries, and whether its north-south dial is on. Listing attachments is auditing posture, and
     an unattached profile is a posture nobody is running.

  4. THE FLOOR. The default section's rules, with the disabled flag on each. What the default
     section allows is the floor under every posture above it, and a rule that ships disabled
     enforces nothing whatever its action says.

     Here the LIST genuinely trims: a firewall policy comes back from the collection with no
     `rules` key at all, and the rules appear only on the single-object read. A floor read from the
     list looks like a section with no rules in it, which is the most reassuring possible wrong
     answer, so this script reads every section by name.

Read-only throughout. It creates nothing, attaches nothing and enables nothing.

Run:
  export VCFA_HOST=...            # the org gateway FQDN
  export VCFA_TOKEN=...           # a bearer for /cci/kubernetes (see README)
  export VCFA_REGION=...          # optional; discovered from the VPC list when omitted
  export VCFA_TLS_VERIFY=false    # only on a self-signed lab CA
  python3 posture.py
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

GV = "/apis/vpc.nsx.vmware.com/v1alpha1"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _ctx():
    verify = os.environ.get("VCFA_TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def cci(path):
    """One read against the org gateway. Returns (status, parsed-or-None)."""
    host = os.environ["VCFA_HOST"]
    req = urllib.request.Request(f"https://{host}/cci/kubernetes{path}", headers={
        "Authorization": f"Bearer {os.environ['VCFA_TOKEN']}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode(errors="replace")[:300]}


def items(path):
    st, body = cci(path)
    return ((body or {}).get("items") or []) if st == 200 else []


def main():
    out_dir = os.environ.get("OUT_DIR", os.path.dirname(os.path.abspath(__file__)))
    print("posture.py: what is attached, and what can this org actually enforce?\n")

    vpcs = items(f"{GV}/vpcs")
    region = os.environ.get("VCFA_REGION") or (
        (vpcs[0].get("spec", {}) or {}).get("regionName") if vpcs else None)
    if not region:
        raise SystemExit("no region found; set VCFA_REGION")

    # ---- 1. entitlement, before anything else
    st, cap_obj = cci(f"{GV}/regionnetworkingcapabilities/{region}")
    caps = (cap_obj or {}).get("capabilities") or []
    st_list, listed = cci(f"{GV}/regionnetworkingcapabilities")
    listed_has = any((i.get("capabilities") or []) for i in ((listed or {}).get("items") or []))
    on = [c for c in caps if c.get("state")]
    off = [c for c in caps if not c.get("state")]
    fw_off = [c for c in off if str(c.get("type", "")).startswith("Firewall.")]
    print(f"  1. ENTITLEMENT: {len(caps)} capability(ies) on this region, {len(on)} enabled, {len(off)} not")
    for c in off:
        print(f"     OFF  {c.get('type'):<38} {c.get('reason')}: {c.get('message')}")
    if fw_off:
        print(f"     {len(fw_off)} of the {len(off)} disabled capability(ies) are firewall capabilities. "
              f"Everything below still READS.")
    if caps and not listed_has:
        print(f"     note: this list is on the SINGLE-OBJECT read only. Listing the kind returns the "
              f"object without it, so an operator who lists sees nothing.")

    # ---- 2. the strategy ladder, in the platform's own words
    strategies = items(f"{GV}/securitystrategies")
    print(f"\n  2. THE STRATEGY LADDER: {len(strategies)} strategy(ies), each with its own description")
    strat_rows = []
    for s in sorted(strategies, key=lambda x: x["metadata"]["name"]):
        sp = s.get("spec") or {}
        desc = (sp.get("description") or "").strip()
        tmpl = [t.get("name") for t in (sp.get("ruleTemplates") or [])]
        strat_rows.append({"name": s["metadata"]["name"], "description": desc,
                           "ruleTemplates": tmpl,
                           "displayNameSet": bool(sp.get("displayName"))})
        print(f"     {s['metadata']['name']}")
        print(f"       \"{desc}\"")
        if tmpl:
            print(f"       rule templates: {', '.join(tmpl)}")

    # ---- 3. posture per VPC
    profiles = {p["metadata"]["name"]: (p.get("spec") or {}) for p in items(f"{GV}/securityprofiles")}
    attachments = items(f"{GV}/securityprofileattachments")
    print(f"\n  3. POSTURE: {len(vpcs)} VPC(s), {len(profiles)} profile(s), {len(attachments)} attachment(s)")
    attached_names = set()
    posture_rows = []
    for a in attachments:
        sp = a.get("spec") or {}
        pname = sp.get("securityProfileName")
        attached_names.add(pname)
        prof = profiles.get(pname, {})
        ew = ((prof.get("eastWestFirewall") or {}).get("securityStrategies")) or []
        ns = (prof.get("northSouthFirewall") or {}).get("enabled")
        conds = [c.get("type") for c in ((a.get("status") or {}).get("conditions") or [])]
        posture_rows.append({"strategies": ew, "northSouth": bool(ns),
                             "attachmentConditions": conds})
        print(f"     a VPC is attached to a profile carrying strategies {ew or ['(none)']}, "
              f"north-south firewall {'on' if ns else 'off'}")
        if not conds:
            print(f"       the attachment carries NO status conditions, so there is nothing to verify "
                  f"it against: 'Realized' is not available on this kind")
    unattached = [n for n in profiles if n not in attached_names]
    print(f"     {len(unattached)} profile(s) defined and attached to nothing")
    ns_any = [n for n, p in profiles.items() if (p.get("northSouthFirewall") or {}).get("enabled")]
    print(f"     {len(ns_any)} of {len(profiles)} profile(s) have the north-south firewall enabled")

    # ---- 4. the floor
    # The list view TRIMS rules[], the same way it drops the capability list in step 1. Read each
    # section by name or the floor reads as empty, which is the most reassuring possible wrong answer.
    listed_sections = items(f"{GV}/firewallpolicies")
    sections = []
    trimmed = 0
    for s in listed_sections:
        if not ((s.get("spec") or {}).get("rules")):
            trimmed += 1
        st_one, one = cci(f"{GV}/firewallpolicies/{s['metadata']['name']}")
        sections.append(one if st_one == 200 else s)
    print(f"\n  4. THE FLOOR: {len(sections)} firewall section(s)")
    if trimmed:
        print(f"     {trimmed} of them came back from the LIST with no rules at all; the rules are on "
              f"the single-object read, the same shape trap as the capability list in step 1")
    floor = []
    for s in sections:
        sp = s.get("spec") or {}
        rules = sp.get("rules") or []
        disabled = [r for r in rules if r.get("disabled")]
        conds = {c.get("type"): c.get("status")
                 for c in ((s.get("status") or {}).get("conditions") or [])}
        floor.append({"priority": sp.get("priority"), "rules": len(rules),
                      "disabledRules": len(disabled), "realized": conds.get("Realized"),
                      "ruleNames": [r.get("name") for r in rules],
                      "ipProtocols": sorted({r.get("ipProtocol") for r in rules if r.get("ipProtocol")})})
        print(f"     a section at priority {sp.get('priority')}, Realized={conds.get('Realized')}, "
              f"{len(disabled)} of {len(rules)} rule(s) disabled")
        for r in rules:
            print(f"       {str(r.get('name')):<32} {str(r.get('action')):<6} "
                  f"disabled={r.get('disabled')} ipProtocol={r.get('ipProtocol')}")
        if rules and len(disabled) == len(rules):
            print(f"       every rule in this section is disabled, so the floor enforces nothing "
                  f"whatever the actions say")

    # ---- the verdict
    enforceable = not fw_off
    print(f"\n  VERDICT: the posture chain {'reads AND enforces' if enforceable else 'READS but cannot enforce'}"
          f" on this org.")
    if not enforceable:
        print(f"     Every object above is present, listable and well formed. The firewall "
              f"capabilities are not entitled, so a write is refused at the gateway, and no read of "
              f"the objects themselves says so.")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "capabilities": {"total": len(caps), "enabled": len(on), "disabled": len(off),
                                "disabledList": [{"type": c.get("type"), "reason": c.get("reason"),
                                                  "message": c.get("message")} for c in off],
                                "enabledList": sorted(str(c.get("type")) for c in on),
                                "onSingleObjectReadOnly": bool(caps) and not listed_has},
               "strategies": strat_rows,
               "vpcs": len(vpcs), "profiles": len(profiles), "attachments": len(attachments),
               "unattachedProfiles": len(unattached), "profilesWithNorthSouth": len(ns_any),
               "posture": posture_rows, "sections": floor,
               "listTrimsRules": trimmed,
               "enforceable": enforceable}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    # The region name is the operator's, not ours: it is never written to the record, and no VPC,
    # profile or group name is either. What ships is the shape and the platform's own wording.
    if region:
        text = text.replace(region, "{{region}}")
    for var in ("VCFA_HOST", "VCFA_TOKEN"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "posture.json"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\nwrote posture.json; no VPC, profile, group or region name is recorded")
    return 0 if enforceable else 1


if __name__ == "__main__":
    sys.exit(main())
