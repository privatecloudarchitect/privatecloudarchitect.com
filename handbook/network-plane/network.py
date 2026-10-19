#!/usr/bin/env python3
"""network.py: the network plane of a VCF Automation organization, read from the platform itself.

Read-only. The networking group is by far the largest the Cloud Consumption Interface declares, and almost all
of it is provider publication rather than anything a tenant creates. Rather than describe that, this asks:

  1. the NETWORKING GROUPS the build declares, and for each kind its scope, its verbs and how many the
     organization can see, which separates the handful of kinds you use from the long tail you never touch;
  2. the CHAIN, object by object: the IP blocks and what each one's visibility is, the connectivity profile
     that names which block serves which purpose, the VPC, the attachment that joins it to a transit gateway,
     and the gateway connection that decides what is advertised outward;
  3. the SUBNETS and the access mode each declares, which is the one field that chooses both the address plane
     a subnet draws from and how far it can be reached;
  4. the SECURITY STRATEGIES the platform ships, the rule templates each expands into, the strategies each
     attached profile actually carries (read from the profile, not inferred), and whether the region is entitled
     to apply a security profile at all, because those are the questions an estate usually cannot answer;
  5. the EGRESS path as objects: the address the VPC translates to, and the switches on the gateway;
  6. the WALK: the chain printed outward from the subnets, link by link, so the first missing object is the
     first line that names it.

Every organization-specific name is replaced by a stable placeholder and the script refuses to write a record
in which one survived. Access modes, strategy names, visibilities and rule actions are the product's own
vocabulary and are kept verbatim.

Addresses are neither. An estate's ranges are its own, so every distinct network is discovered as it is read and
swapped for one reserved for documentation, at the same prefix length, before anything is written. This script
names no address of its own, which is what lets it be published alongside the records. The structure is the lesson (which range carries
which visibility, which one the profile assigns to which purpose, what the translation maps onto) and the
particular numbers are one estate's arbitrary choices. Running this against your own estate shows you your own
ranges on screen; only the written record is substituted.

Sign-in, one of:
  VCFA_REFRESH_TOKEN_FILE   a file holding a refresh token minted for the organization, mode 0600
  VCFA_USER and VCFA_PASSWORD_FILE   a session login as user@org (the password from a file of mode 0600, or
                            VCFA_PASSWORD, the value itself, which lands in the shell's history)
A file open to group or other is refused before it is read.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password    # or VCFA_REFRESH_TOKEN_FILE
  export TLS_VERIFY=false                                               # only on a self-signed lab CA
  python3 network.py
  python3 network.py --publishable   # prints documentation ranges in place of yours, as the records carry them

Exit: 0 read; 2 a call failed or the sign-in was refused; 5 an unknown argument.
"""
import base64
import http.client
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

http.client._MAXHEADERS = 1000
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Addresses are swapped before anything is written, and this file names none of them. Every distinct network
# the estate uses is discovered as it is read and assigned, in sorted order so runs are reproducible, the next
# network from a pool reserved for documentation and benchmarking. The original prefix length is kept, so a
# large block still reads as large. A reader can tell at a glance that these are examples, and this script
# stays publishable because it carries no estate value of its own.
# RFC 5737 documentation ranges and RFC 2544 benchmarking ranges. Nothing here routes on the internet and
# nothing here is anybody's production plan, which is the property that makes them safe stand-ins.
DOC_NETS = ("198.18.0.0", "198.19.0.0", "192.0.2.0", "198.51.100.0", "203.0.113.0", "233.252.0.0")
CIDR_RX = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})\b")
IPV4_RX = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


class Addresses:
    """Map every real network onto a documentation one, the same way every run."""

    def __init__(self):
        self.map = {}

    def learn(self, blob):
        """Collect the networks a structure mentions. Call before scrubbing anything."""
        for net, _bits in CIDR_RX.findall(json.dumps(blob)):
            self.map.setdefault(net, None)

    def freeze(self):
        for i, net in enumerate(sorted(self.map)):
            if i >= len(DOC_NETS):
                raise SystemExit(f"more distinct networks ({len(self.map)}) than documentation ranges to stand in "
                                 f"for them ({len(DOC_NETS)}); widen DOC_NETS")
            self.map[net] = DOC_NETS[i]

    def apply(self, text):
        for real, example in sorted(self.map.items(), key=lambda kv: -len(kv[0])):
            if example:
                text = text.replace(real, example)
        # Anything still shaped like an address was never learned, which means a code path skipped learn().
        leftover = [m for m in IPV4_RX.findall(text) if m not in DOC_NETS and not m.startswith("0.")]
        if leftover:
            raise SystemExit(f"an address survived substitution: {sorted(set(leftover))[:3]}; a structure was "
                             "written without being learned first")
        return text


CCI = "/cci/kubernetes"
VPC_GROUP = "vpc.nsx.vmware.com/v1alpha1"
# The families the VPC group's kinds fall into. A kind not matched here lands in "other", which is the signal to
# re-read the catalog: the product added something this grouping does not know about.
FAMILIES = (
    ("the chain", ("VPC", "Subnet", "TransitGateway", "TGWAttachment", "VPCAttachment", "GatewayConnection",
                   "DistributedVLANConnection", "DistributedVXLANConnection", "VPCConnectivityProfile")),
    ("addressing", ("IPBlock", "IPBlockAllocationState", "IPBlockUsage", "IPAddressAllocation",
                    "VPCIPAddressAllocation", "VPCIPAddressUsage")),
    ("security", ("FirewallPolicy", "VPCGatewayFirewallPolicy", "TGWFirewallPolicy", "NetworkSecurityGroup",
                  "VPCNetworkSecurityGroup", "SecurityProfile", "SecurityProfileAttachment", "SecurityStrategy")),
    ("routing and translation", ("VPCNATRule", "TGWNATRule", "TGWStaticRoute", "TGWCentralizedConfig")),
    ("site to site", ("IPSecVPN", "IPSecVPNSession", "IPSecVPNLocalEndpoint", "IPSecVPNIKEProfile",
                      "IPSecVPNTunnelProfile", "IPSecVPNDPDProfile")),
    ("limits and capability", ("Limit", "LimitState", "VPCLimitState", "RegionNetworkingCapabilities")),
    ("services", ("NetworkService", "VPCServiceProfile", "LoadBalancer")),
    ("bound under a project", ("VPCBinding", "SubnetBinding", "VPCConnectivityProfileBinding")),
    ("the write surface", ("VPCRead", "VPCWrite", "PolicyRead", "PolicyWrite")),
)


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    # The product's own vocabulary is never an estate name. A principal can be called exactly what a platform
    # object is called (this estate has a user named "admin" and a project role named "admin"), and registering
    # one teaches the scrubber to blank the other. A name in RESERVED identifies no estate and is left alone.
    RESERVED = {"admin", "view", "edit", "user", "users", "group", "groups", "owner", "auditor", "auditors",
                "administrator", "administrators", "default", "system", "none", "all"}

    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        if str(name) in self.RESERVED:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def scrub(self, text):
        """One pass, longest name first: a subnet name contains its VPC name, which contains the region."""
        if not isinstance(text, str):
            return text
        known = [(real, label) for m in self.maps.values() for real, label in m.items()]
        # Longest first so a contained name cannot corrupt a longer one, and on a WORD BOUNDARY so a short
        # name is not replaced inside an unrelated word. A principal really can be called "admin", and a naive
        # replace turns the field name "administrators" into "{{user-3}}istrators". The leak check below uses
        # the same boundary, so what the scrub replaces and what the check looks for are one rule.
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])",
                          "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)

    def deep(self, value):
        """Scrub every string anywhere inside a structure.

        An object's own name is not the only place its name appears: a connectivity profile names its IP blocks
        and a gateway connection names the blocks it advertises, both as values nested inside spec. Scrubbing
        only the metadata name leaves those behind, which is what the leak gate caught the first time this ran.
        """
        if isinstance(value, str):
            return self.scrub(value)
        if isinstance(value, list):
            return [self.deep(v) for v in value]
        if isinstance(value, dict):
            return {k: self.deep(v) for k, v in value.items()}
        return value


def secret(name):
    """A secret from NAME_FILE (a file, mode 0600, its value stripped) or else NAME itself; None when neither is set.
    The file keeps a tier-0 token out of the shell's history and the process list. A file open to group or other is
    refused before it is read; the refusal names the variable and the fix, never the file's content."""
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


class Cci:
    def __init__(self, host, org, refresh_token=None, user=None, password=None):
        """A tenant bearer, from the organization's refresh token or from a session login as user@org. A refused
        mint ends the run with the server's own answer: "invalid_grant" means the refresh token is dead, a 401 at
        the session means the login is."""
        self.host = host
        if refresh_token:
            self.kind = "refresh token"
            body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
            req = urllib.request.Request(
                f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        else:
            self.kind = "session login"
            basic = base64.b64encode(f"{user.split('@')[0]}@{org}:{password}".encode()).decode()
            req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions", method="POST",
                                         headers={"Authorization": f"Basic {basic}", "Accept": "application/json;version=40.0"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
                self.bearer = (json.loads(r.read())["access_token"] if refresh_token
                               else r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN"))
        except urllib.error.HTTPError as e:
            print(f"FATAL: the {self.kind} answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
            sys.exit(2)
        except (urllib.error.URLError, OSError) as e:
            print(f"FATAL: the {self.kind} did not answer: {e}")
            sys.exit(2)
        if not self.bearer:
            print(f"FATAL: the {self.kind} answered without a bearer")
            sys.exit(2)

    def get(self, path):
        req = urllib.request.Request(f"https://{self.host}{CCI}{path}",
                                     headers={"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=90) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:200]
        except (urllib.error.URLError, OSError) as e:
            return None, str(e)

    def items(self, resource, group=VPC_GROUP):
        """Every item of a list, following the continue token a Kubernetes-style list hands back when it pages. A
        list that fails ends the run: a refused list read as empty would print a chain with a hole that is not there."""
        out, token = [], None
        while True:
            st, body = self.get(f"/apis/{group}/{resource}" + (f"?continue={urllib.parse.quote(token)}" if token else ""))
            if st != 200 or not isinstance(body, dict):
                print(f"FATAL: GET {CCI}/apis/{group}/{resource} answered {st if st else 'nothing'}")
                sys.exit(2)
            out += body.get("items") or []
            token = (body.get("metadata") or {}).get("continue")
            if not token:
                return out


def refuse_unknown_args(known):
    """Refuse any argument this script does not recognise, before a client opens. --help prints the usage above."""
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    unknown = [a for a in args if a not in known]
    if unknown:
        print(f"unknown argument(s) {unknown}: this script takes {', '.join(sorted(known))} (see --help)", file=sys.stderr)
        sys.exit(5)


def family_of(kind):
    for name, kinds in FAMILIES:
        if kind in kinds:
            return name
    return "other"


def main():
    refuse_unknown_args({"--publishable"})
    publishable = "--publishable" in sys.argv
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    try:
        refresh, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
    except OSError as e:   # a secret file that is missing, unreadable or open to group or other
        print(f"FATAL: {e}")
        sys.exit(2)
    user = os.environ.get("VCFA_USER")
    if not refresh and not (user and password):
        print("FATAL: set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE (see --help)")
        sys.exit(2)
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Cci(host, org, refresh, None if refresh else user, None if refresh else password)
    L = Labels()
    # Your own ranges print on screen by default. With --publishable every line is held until the records'
    # substitution is known and printed with the documentation ranges the records carry, the form a transcript
    # can be published in.
    held_lines = []

    def say(line=""):
        if publishable:
            held_lines.append(line)
        else:
            print(line)

    say("network.py: the network plane, read from the platform through the Cloud Consumption Interface\n")

    # ---- 1. the catalog, held as families
    st, groups = c.get("/apis")
    if st != 200:
        print(f"FATAL: discovery answered HTTP {st}")
        sys.exit(2)
    catalog = []
    for g in groups.get("groups", []):
        if not any(k in g["name"] for k in ("vpc.nsx", "avi.vmware", "networking.k8s")):
            continue
        for v in g.get("versions", []):
            st2, rl = c.get(f"/apis/{v['groupVersion']}")
            if st2 != 200:
                print(f"FATAL: the resource list of {v['groupVersion']} answered {st2}")
                sys.exit(2)
            for res in (rl.get("resources") or []):
                if "/" in res["name"]:
                    continue
                entry = {"group": g["name"], "kind": res.get("kind"), "resource": res["name"],
                         "scope": "project" if res.get("namespaced") else "top level",
                         "writable": "create" in (res.get("verbs") or []),
                         "family": family_of(res.get("kind"))}
                if not res.get("namespaced") and "list" in (res.get("verbs") or []):
                    st3, body = c.get(f"/apis/{v['groupVersion']}/{res['name']}")
                    entry["held"] = len(body.get("items") or []) if st3 == 200 and isinstance(body, dict) else f"HTTP {st3}"
                catalog.append(entry)
    vpc_kinds = [e for e in catalog if e["group"] == "vpc.nsx.vmware.com"]
    from collections import Counter
    say(f"  catalog: {len(catalog)} networking kinds across {len({e['group'] for e in catalog})} groups; "
        f"{len(vpc_kinds)} of them in the VPC group alone")
    by_fam = Counter(e["family"] for e in vpc_kinds)
    for fam, _ in FAMILIES:
        got = [e for e in vpc_kinds if e["family"] == fam]
        if not got:
            continue
        used = sum(1 for e in got if isinstance(e.get("held"), int) and e["held"] > 0)
        say(f"     {fam:<26} {len(got):>2} kinds, {used} with anything on this estate")
    if by_fam.get("other"):
        say(f"     other                      {by_fam['other']:>2} kinds this grouping does not know, so re-read the catalog: "
            + ", ".join(sorted(e["kind"] for e in vpc_kinds if e["family"] == "other")))

    # ---- 2. the chain
    def one(resource, keep, created=False):
        out = []
        for o in c.items(resource):
            name = o["metadata"]["name"]
            L.get("netobj", name)
            sp = o.get("spec") or {}
            row = {"name": L.scrub(name), **{k: L.deep(sp.get(k)) for k in keep if k in sp}}
            if created:
                row["created"] = o["metadata"].get("creationTimestamp")
            out.append(row)
        return out

    # Register every name that other objects refer to, before reading the objects that refer to them, so the
    # recursive scrub has a label for each one.
    for resource in ("ipblocks", "vpcs", "transitgateways", "gatewayconnections", "vpcconnectivityprofiles",
                     "securityprofiles", "subnets"):
        for o in c.items(resource):
            L.get("netobj", o["metadata"]["name"])
    # A VPC names its region, and the region's name is the organization's own: register it before a record
    # carries it, and keep the real names for the capability read below.
    regions = sorted({(o.get("spec") or {}).get("regionName") for o in c.items("vpcs") if (o.get("spec") or {}).get("regionName")})
    for region in regions:
        L.get("region", region)
    blocks = one("ipblocks", ("cidrs", "visibility", "ipAddressType", "systemOwned", "subnetExclusive"))
    vpcs = one("vpcs", ("privateIPs", "loadBalancerVPCEndpoint", "regionName"), created=True)
    profiles = one("vpcconnectivityprofiles", ("isDefault", "externalIPBlockNames", "privateTGWIPBlockNames", "transitGatewayName"))
    tgws = one("transitgateways", ("isDefault", "transitSubnets"))
    vpcatt = one("vpcattachments", ("vpcName", "vpcConnectivityProfileName"), created=True)
    tgwatt = one("tgwattachments", ("transitGatewayName", "gatewayConnectionName", "routeAdvertisementRules"))
    gwconn = one("gatewayconnections", ("advertiseOutboundNetworks", "natConfig"))
    say(f"\n  the chain: {len(blocks)} IP block(s), {len(vpcs)} VPC(s), {len(profiles)} connectivity profile(s), "
        f"{len(tgws)} transit gateway(s), {len(gwconn)} gateway connection(s)")
    for b in blocks:
        say(f"     block  {str(b.get('cidrs')):<22} visibility={b.get('visibility'):<9} systemOwned={b.get('systemOwned')}")
    for tg in tgws:
        say(f"     transit gateway carries its own space: {tg.get('transitSubnets')}")

    # ---- 3. the subnets and the one field that decides reach
    subnets = []
    for o in c.items("subnets"):
        sp = o.get("spec") or {}
        L.get("netobj", o["metadata"]["name"])
        subnets.append({"name": L.scrub(o["metadata"]["name"]), "vpc": L.scrub(sp.get("vpcName") or ""),
                        "accessMode": sp.get("accessMode") or "Private",
                        "backing": "VLAN" if sp.get("vlanConnectionName") else "overlay",
                        "systemOwned": bool(sp.get("systemOwned")),
                        "declares": sorted(k for k in sp if k not in ("regionName", "vpcName"))})
    st, oa = c.get(f"/openapi/v3/apis/{VPC_GROUP}")
    access_doc = nat_doc = None
    for k, v in ((oa.get("components", {}) or {}).get("schemas", {}) or {}).items():
        if k.endswith("SubnetSpec"):
            access_doc = ((v.get("properties") or {}).get("accessMode") or {}).get("description")
        if k.endswith("VPCNATRuleSpec"):
            nat_doc = ((v.get("properties") or {}).get("action") or {}).get("description")
    modes = re.findall(r"- (Public|PrivateTGW|Private):", access_doc or "")
    say(f"\n  subnets: {len(subnets)}; the platform documents {len(modes)} access modes: {', '.join(modes) or 'not declared'}")
    for s in subnets:
        say(f"     {s['name'][:40]:<42} accessMode={s['accessMode']:<11} {s['backing']}")

    # ---- 4. the dial, and what is actually on it
    strategies = []
    for o in c.items("securitystrategies"):
        sp = o.get("spec") or {}
        strategies.append({"name": o["metadata"]["name"], "description": sp.get("description"),
                           "rules": [{"name": r.get("name"), "action": r.get("action"),
                                      "from": [g.get("groupName") for g in (r.get("from") or [])],
                                      "to": [g.get("groupName") for g in (r.get("to") or [])]}
                                     for r in (sp.get("ruleTemplates") or [])]})
    # A profile names its strategies in eastWestFirewall.securityStrategies; read them there rather than matching
    # descriptions, which a provider may edit.
    profs = []
    for o in c.items("securityprofiles"):
        sp = o.get("spec") or {}
        L.get("netobj", o["metadata"]["name"])
        profs.append({"name": L.scrub(o["metadata"]["name"]), "isDefault": bool(sp.get("isDefault")),
                      "strategies": list((sp.get("eastWestFirewall") or {}).get("securityStrategies") or []),
                      "northSouth": bool((sp.get("northSouthFirewall") or {}).get("enabled"))})
    attached = []
    for o in c.items("securityprofileattachments"):
        sp = o.get("spec") or {}
        for k in ("vpcName", "securityProfileName"):
            if sp.get(k):
                L.get("netobj", sp[k])
        prof = next((pr for pr in profs if pr["name"] == L.scrub(sp.get("securityProfileName", ""))), None)
        attached.append({"vpc": L.scrub(sp.get("vpcName")), "profile": L.scrub(sp.get("securityProfileName")),
                         "strategies": prof["strategies"] if prof else None, "isDefault": bool(prof and prof["isDefault"]),
                         "created": o["metadata"].get("creationTimestamp")})
    # The region's capability list is on the single-object read only; a list of the kind returns the objects
    # without it. Whether a security profile can be applied at all is one of those capabilities.
    entitlement = []
    for region in regions:
        st, obj = c.get(f"/apis/{VPC_GROUP}/regionnetworkingcapabilities/{region}")
        if st != 200:
            print(f"FATAL: the region's networking capabilities answered {st}")
            sys.exit(2)
        entitlement += [{"type": cap.get("type"), "state": bool(cap.get("state")), "reason": cap.get("reason")}
                        for cap in ((obj or {}).get("capabilities") or [])]
    say(f"\n  the isolation dial: {len(strategies)} strategies the platform ships, {len(profs)} profiles in this region")
    for s in strategies:
        acts = "/".join(sorted({r["action"] for r in s["rules"]})) or "no rules"
        say(f"     {s['name']:<40} {len(s['rules'])} rule(s) [{acts}]")
    for a in attached:
        say(f"     ATTACHED: the VPC's profile carries {', '.join(a['strategies'] or []) or 'no strategy'}"
            f"{' (the default profile)' if a['isDefault'] else ''}")
    off = [e for e in entitlement if not e["state"]]
    say(f"     the region: {len(entitlement)} networking capabilities, {len(off)} not enabled"
        + "".join(f"\n       OFF  {e['type']} ({e['reason']})" for e in off))

    # ---- 5. egress, as objects
    # Both of these carry addresses, so both go through the scrub rather than being copied out of spec raw.
    nat = [L.deep({"action": (o.get("spec") or {}).get("action"), "source": (o.get("spec") or {}).get("sourceNetwork"),
                   "translatedTo": (o.get("spec") or {}).get("translatedNetwork"),
                   "systemOwned": bool((o.get("spec") or {}).get("systemOwned"))}) for o in c.items("vpcnatrules")]
    alloc = [L.deep({"address": (o.get("spec") or {}).get("allocationIPs"),
                     "fromBlockVisibility": (o.get("spec") or {}).get("ipAddressBlockVisibility")})
             for o in c.items("vpcipaddressallocations")]
    services = len(c.items("networkservices"))
    natkind = next((e for e in catalog if e["kind"] == "VPCNATRule"), {})
    allockind = next((e for e in catalog if e["kind"] == "VPCIPAddressAllocation"), {})
    say(f"\n  egress: {len(nat)} translation rule(s), {len(alloc)} allocated address(es), "
        f"{services} predefined services rules can name")
    say(f"     the interface documents {len(re.findall(chr(92) + 'b(SNAT|DNAT|Reflexive|NoSNAT|NoDNAT)' + chr(92) + 'b', nat_doc or ''))} NAT actions, "
        f"and declares create on rules: {natkind.get('writable')}, on address allocations: {allockind.get('writable')}")
    for n in nat:
        say(f"     {n['action']} {n['source']} -> {n['translatedTo']} (system owned: {n['systemOwned']})")
    for g in gwconn:
        say(f"     the gateway advertises private space: {(g.get('advertiseOutboundNetworks') or {}).get('allowPrivate')}; "
            f"its own SNAT: {(g.get('natConfig') or {}).get('enableSNAT')}")

    # ---- 6. the walk, from the workload's subnet outward: the first missing link is the first line that names it
    say("\n  the walk, from each VPC's subnets outward:")
    for v in vpcs:
        att = [a for a in vpcatt if a.get("vpcName") == v["name"]]
        prof = next((pr for pr in profiles if att and pr["name"] == att[0].get("vpcConnectivityProfileName")), None)
        tgw = prof.get("transitGatewayName") if prof else None
        tatt = [a for a in tgwatt if tgw and a.get("transitGatewayName") == tgw]
        conn = tatt[0].get("gatewayConnectionName") if tatt else None
        # A VLAN-backed subnet names its VPC with a qualifier before a colon, empty here (":<vpc>"), where an
        # overlay subnet names it bare; join on the part after the colon or the VLAN subnets drop out of the walk.
        subs = [s for s in subnets if s["vpc"].split(":")[-1] == v["name"]]
        say(f"     {len(subs)} subnet(s) -> VPC {v['name']} -> "
            f"{'attachment ' + att[0]['name'] if att else 'NO VPC attachment'} -> "
            f"{'profile ' + prof['name'] if prof else 'no profile'} -> "
            f"{'transit gateway ' + tgw if tgw else 'no transit gateway'} -> "
            f"{'attachment ' + tatt[0]['name'] if tatt else 'NO transit gateway attachment'} -> "
            f"{'gateway connection ' + conn if conn else 'no gateway connection'}")

    # ---- 6. write, sanitized
    A = Addresses()
    for blob in (blocks, vpcs, profiles, tgws, vpcatt, tgwatt, gwconn, subnets, nat, alloc):
        A.learn(blob)
    A.freeze()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    records = {
        "network-model.json": {"captured_utc": stamp, "catalog": catalog,
                               "families": [{"family": f, "kinds": [e["kind"] for e in vpc_kinds if e["family"] == f]}
                                            for f, _ in FAMILIES if any(e["family"] == f for e in vpc_kinds)],
                               "accessModes": modes, "accessModeDoc": access_doc,
                               "natActions": re.findall(r"\b(SNAT|DNAT|Reflexive|NoSNAT|NoDNAT)\b", nat_doc or ""),
                               "natActionDoc": nat_doc,
                               "strategies": strategies, "profiles": profs, "attached": attached,
                               "entitlement": entitlement, "predefinedServices": services, "signIn": c.kind},
        "chain.json": {"captured_utc": stamp, "ipBlocks": blocks, "vpcs": vpcs, "connectivityProfiles": profiles,
                       "transitGateways": tgws, "vpcAttachments": vpcatt, "tgwAttachments": tgwatt,
                       "gatewayConnections": gwconn, "subnets": subnets, "nat": nat, "allocations": alloc,
                       "note": "addresses are documentation ranges substituted for the estate's own; the structure is the lesson"},
    }
    os.makedirs(out_dir, exist_ok=True)
    for fname, payload in records.items():
        text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
        for value in (c.bearer, refresh, password, user, host, org):
            assert not value or value not in text, f"an estate value reached {fname}"
        text = A.apply(text)
        bare = re.sub(r"\{\{[^}]*\}\}", "", text)
        for fam, m in L.maps.items():
            for name in m:
                if name and re.search(r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])", bare):
                    shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", name))
                    raise SystemExit(f"FATAL: a {fam} name ({len(name)} characters, shape {shape}) reached {fname}; not writing it")
        open(os.path.join(out_dir, fname), "w", encoding="utf-8").write(text + "\n")
    say(f"\nwrote network-model.json ({len(catalog)} kinds, {len(strategies)} strategies) and chain.json "
        f"({len(blocks)} blocks, {len(subnets)} subnets); every organization name replaced by a placeholder")
    for line in held_lines:
        print(A.apply(line))


if __name__ == "__main__":
    main()
