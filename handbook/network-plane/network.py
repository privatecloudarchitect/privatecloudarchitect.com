#!/usr/bin/env python3
"""network.py: the network plane of a VCF Automation 9.1 organization, read from the platform itself.

Read-only. The networking group is by far the largest the Cloud Consumption Interface declares, and almost all
of it is provider publication rather than anything a tenant creates. Rather than describe that, this asks:

  1. the NETWORKING GROUPS the build declares, and for each kind its scope, its verbs and how many the
     organization can see, which separates the handful of kinds you use from the long tail you never touch;
  2. the CHAIN, object by object: the IP blocks and what each one's visibility is, the connectivity profile
     that names which block serves which purpose, the VPC, the attachment that joins it to a transit gateway,
     and the gateway connection that decides what is advertised outward;
  3. the SUBNETS and the access mode each declares, which is the one field that chooses both the address plane
     a subnet draws from and how far it can be reached;
  4. the SECURITY STRATEGIES the platform ships, the rule templates each expands into, and which profile is
     actually attached to the VPC, because that last one is the question an estate usually cannot answer;
  5. the EGRESS path as objects: the address the VPC translates to, and the switches on the gateway.

Every organization-specific name is replaced by a stable placeholder and the script refuses to write a record
in which one survived. Access modes, strategy names, visibilities and rule actions are the product's own
vocabulary and are kept verbatim.

Addresses are neither. An estate's ranges are its own, so every distinct network is discovered as it is read and
swapped for one reserved for documentation, at the same prefix length, before anything is written. This script
names no address of its own, which is what lets it be published alongside the records. The structure is the lesson (which range carries
which visibility, which one the profile assigns to which purpose, what the translation maps onto) and the
particular numbers are one estate's arbitrary choices. Running this against your own estate shows you your own
ranges on screen; only the written record is substituted.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
  export TLS_VERIFY=false                                  # only on a self-signed lab CA
  python3 network.py
"""
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
# The families the 46 kinds fall into. A kind not matched here lands in "other", which is the signal to
# re-read the catalog: the product added something this grouping does not know about.
FAMILIES = (
    ("the chain", ("VPC", "Subnet", "TransitGateway", "TGWAttachment", "VPCAttachment", "GatewayConnection",
                   "DistributedVLANConnection", "VPCConnectivityProfile")),
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
    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def scrub(self, text):
        """One pass, longest name first: a subnet name contains its VPC name, which contains the region."""
        if not isinstance(text, str):
            return text
        known = [(real, label) for m in self.maps.values() for real, label in m.items()]
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = text.replace(real, "{{%s}}" % label)
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


class Cci:
    def __init__(self, host, org, refresh_token):
        self.host = host
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(
            f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            self.bearer = json.loads(r.read())["access_token"]

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
        st, body = self.get(f"/apis/{group}/{resource}")
        return (body.get("items") or []) if st == 200 and isinstance(body, dict) else []


def family_of(kind):
    for name, kinds in FAMILIES:
        if kind in kinds:
            return name
    return "other"


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Cci(host, org, refresh)
    L = Labels()
    print("network.py: the network plane, read from the platform through the Cloud Consumption Interface\n")

    # ---- 1. the catalog, held as families
    st, groups = c.get("/apis")
    if st != 200:
        print(f"FATAL: discovery answered HTTP {st}")
        sys.exit(1)
    catalog, counts = [], {}
    for g in groups.get("groups", []):
        if not any(k in g["name"] for k in ("vpc.nsx", "avi.vmware", "networking.k8s")):
            continue
        for v in g.get("versions", []):
            st2, rl = c.get(f"/apis/{v['groupVersion']}")
            if st2 != 200:
                continue
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
    print(f"  catalog: {len(catalog)} networking kinds across {len({e['group'] for e in catalog})} groups; "
          f"{len(vpc_kinds)} of them in the VPC group alone")
    by_fam = Counter(e["family"] for e in vpc_kinds)
    for fam, _ in FAMILIES:
        got = [e for e in vpc_kinds if e["family"] == fam]
        if not got:
            continue
        used = sum(1 for e in got if isinstance(e.get("held"), int) and e["held"] > 0)
        print(f"     {fam:<26} {len(got):>2} kinds, {used} with anything on this estate")
    if by_fam.get("other"):
        print(f"     other                      {by_fam['other']:>2} kinds this grouping does not know: re-read the catalog")

    # ---- 2. the chain
    def one(resource, keep):
        out = []
        for o in c.items(resource):
            name = o["metadata"]["name"]
            L.get("netobj", name)
            sp = o.get("spec") or {}
            out.append({"name": L.scrub(name), **{k: L.deep(sp.get(k)) for k in keep if k in sp}})
        return out

    # Register every name that other objects refer to, before reading the objects that refer to them, so the
    # recursive scrub has a label for each one.
    for resource in ("ipblocks", "vpcs", "transitgateways", "gatewayconnections", "vpcconnectivityprofiles",
                     "securityprofiles", "subnets"):
        for o in c.items(resource):
            L.get("netobj", o["metadata"]["name"])
    blocks = one("ipblocks", ("cidrs", "visibility", "ipAddressType", "systemOwned", "subnetExclusive"))
    vpcs = one("vpcs", ("privateIPs", "loadBalancerVPCEndpoint"))
    profiles = one("vpcconnectivityprofiles", ("isDefault", "externalIPBlockNames", "privateTGWIPBlockNames", "transitGatewayName"))
    tgws = one("transitgateways", ("isDefault", "transitSubnets"))
    vpcatt = one("vpcattachments", ("vpcName", "vpcConnectivityProfileName"))
    tgwatt = one("tgwattachments", ("transitGatewayName", "gatewayConnectionName", "routeAdvertisementRules"))
    gwconn = one("gatewayconnections", ("advertiseOutboundNetworks", "natConfig"))
    print(f"\n  the chain: {len(blocks)} IP block(s), {len(vpcs)} VPC(s), {len(profiles)} connectivity profile(s), "
          f"{len(tgws)} transit gateway(s), {len(gwconn)} gateway connection(s)")
    for b in blocks:
        print(f"     block  {str(b.get('cidrs')):<22} visibility={b.get('visibility'):<9} systemOwned={b.get('systemOwned')}")
    for t in tgws:
        print(f"     transit gateway carries its own space: {t.get('transitSubnets')}")

    # ---- 3. the subnets and the one field that decides reach
    subnets = []
    for o in c.items("subnets"):
        sp = o.get("spec") or {}
        L.get("netobj", o["metadata"]["name"])
        subnets.append({"name": L.scrub(o["metadata"]["name"]), "accessMode": sp.get("accessMode") or "Private",
                        "backing": "VLAN" if sp.get("vlanConnectionName") else "overlay",
                        "systemOwned": bool(sp.get("systemOwned")),
                        "declares": sorted(k for k in sp if k not in ("regionName", "vpcName"))})
    st, oa = c.get(f"/openapi/v3/apis/{VPC_GROUP}")
    access_doc = None
    for k, v in ((oa.get("components", {}) or {}).get("schemas", {}) or {}).items():
        if k.endswith("SubnetSpec"):
            access_doc = ((v.get("properties") or {}).get("accessMode") or {}).get("description")
    modes = re.findall(r"- (Public|PrivateTGW|Private):", access_doc or "")
    print(f"\n  subnets: {len(subnets)}; the platform documents {len(modes)} access modes: {', '.join(modes) or 'not declared'}")
    for s in subnets:
        print(f"     {s['name'][:40]:<42} accessMode={s['accessMode']:<11} {s['backing']}")

    # ---- 4. the dial, and what is actually on it
    strategies = []
    for o in c.items("securitystrategies"):
        sp = o.get("spec") or {}
        strategies.append({"name": o["metadata"]["name"], "description": sp.get("description"),
                           "rules": [{"name": r.get("name"), "action": r.get("action"),
                                      "from": [g.get("groupName") for g in (r.get("from") or [])],
                                      "to": [g.get("groupName") for g in (r.get("to") or [])]}
                                     for r in (sp.get("ruleTemplates") or [])]})
    profs = []
    for o in c.items("securityprofiles"):
        sp = o.get("spec") or {}
        L.get("netobj", o["metadata"]["name"])
        profs.append({"name": L.scrub(o["metadata"]["name"]), "isDefault": bool(sp.get("isDefault")),
                      "strategy": next((s["name"] for s in strategies if (sp.get("description") or "")[:40] == (s["description"] or "")[:40]), None)})
    attached = []
    for o in c.items("securityprofileattachments"):
        sp = o.get("spec") or {}
        for k in ("vpcName", "securityProfileName"):
            if sp.get(k):
                L.get("netobj", sp[k])
        prof = next((p for p in profs if p["name"] == L.scrub(sp.get("securityProfileName", ""))), None)
        attached.append({"vpc": L.scrub(sp.get("vpcName")), "profile": L.scrub(sp.get("securityProfileName")),
                         "strategy": prof["strategy"] if prof else None})
    print(f"\n  the isolation dial: {len(strategies)} strategies the platform ships, {len(profs)} profiles in this region")
    for s in strategies:
        acts = "/".join(sorted({r["action"] for r in s["rules"]})) or "no rules"
        print(f"     {s['name']:<40} {len(s['rules'])} rule(s) [{acts}]")
    for a in attached:
        print(f"     ATTACHED: the VPC runs the {a['strategy'] or 'unknown'} strategy")

    # ---- 5. egress, as objects
    # Both of these carry addresses, so both go through the scrub rather than being copied out of spec raw.
    nat = [L.deep({"action": (o.get("spec") or {}).get("action"), "source": (o.get("spec") or {}).get("sourceNetwork"),
                   "translatedTo": (o.get("spec") or {}).get("translatedNetwork"),
                   "systemOwned": bool((o.get("spec") or {}).get("systemOwned"))}) for o in c.items("vpcnatrules")]
    alloc = [L.deep({"address": (o.get("spec") or {}).get("allocationIPs"),
                     "fromBlockVisibility": (o.get("spec") or {}).get("ipAddressBlockVisibility")})
             for o in c.items("vpcipaddressallocations")]
    services = len(c.items("networkservices"))
    print(f"\n  egress: {len(nat)} translation rule(s), {len(alloc)} allocated address(es), "
          f"{services} predefined services rules can name")
    for n in nat:
        print(f"     {n['action']} {n['source']} -> {n['translatedTo']} (system owned: {n['systemOwned']})")
    for g in gwconn:
        print(f"     the gateway advertises private space: {(g.get('advertiseOutboundNetworks') or {}).get('allowPrivate')}; "
              f"its own SNAT: {(g.get('natConfig') or {}).get('enableSNAT')}")

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
                               "strategies": strategies, "profiles": profs, "attached": attached,
                               "predefinedServices": services},
        "chain.json": {"captured_utc": stamp, "ipBlocks": blocks, "vpcs": vpcs, "connectivityProfiles": profiles,
                       "transitGateways": tgws, "vpcAttachments": vpcatt, "tgwAttachments": tgwatt,
                       "gatewayConnections": gwconn, "subnets": subnets, "nat": nat, "allocations": alloc,
                       "note": "addresses are documentation ranges substituted for the estate's own; the structure is the lesson"},
    }
    os.makedirs(out_dir, exist_ok=True)
    for fname, payload in records.items():
        text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
        for secret in (c.bearer, refresh, host, org):
            assert secret not in text, f"an estate value reached {fname}"
        text = A.apply(text)
        bare = re.sub(r"\{\{[^}]*\}\}", "", text)
        for fam, m in L.maps.items():
            for name in m:
                if name and re.search(r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])", bare):
                    shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", name))
                    raise SystemExit(f"FATAL: a {fam} name ({len(name)} characters, shape {shape}) reached {fname}; not writing it")
        open(os.path.join(out_dir, fname), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote network-model.json ({len(catalog)} kinds, {len(strategies)} strategies) and chain.json "
          f"({len(blocks)} blocks, {len(subnets)} subnets); every organization name replaced by a placeholder")


if __name__ == "__main__":
    main()
