#!/usr/bin/env python3
"""overlay.py: what the provider runs above a VPC, read from NSX and vCenter. Read-only; every call is a GET.

network.py reads the plane a tenant can see, and it ends at the gateway connection. Above that the provider owns the
fabric, and a tenant cannot read it. This asks the provider side, with a provider credential:

  1. the TIER-0 GATEWAYS: how many, their HA mode and failover, and the edge clusters they run on with their nodes;
  2. the GATEWAY CONNECTIONS: each one's Tier-0, and how many transit gateways attach to it, which says whether
     organizations share a path north;
  3. per NSX PROJECT: its transit gateway, the gateway connection that gateway attaches to (or none), its VPC
     connectivity profile (external blocks, service gateway), its VPCs, and whether the project names a Tier-0
     itself;
  4. the IP BLOCKS by visibility;
  5. with vCenter settings, the ZONES and the clusters each one holds, the compute side under the Supervisor.

Every object name is replaced by a label in what it prints and in what it writes, and the script refuses to write a
record in which a name survived. Product vocabulary (HA modes, visibilities) is kept.

Run:
  export NSX_HOST=<nsx-manager-fqdn>
  export NSX_USER=<provider-user> NSX_PASSWORD_FILE=~/.secrets/nsx     # mode 0600; or NSX_TOKEN_FILE, a bearer
  export VC_HOST=<vcenter-fqdn> VC_USER=<sso-user> VC_PASSWORD_FILE=~/.secrets/vc   # optional: the zone read
  export TLS_VERIFY=false                                              # only on a self-signed lab CA
  python3 overlay.py [--project <your NSX project id or display name>]  # marks yours in the output
Exit: 0 read · 2 a setting or argument is missing, or a secret file is open to group or other · 3 a sign-in or a read
      failed · 4 the record refused to write because a name survived
"""
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request


class ReadFailed(Exception):
    """A read the record depends on did not succeed."""


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


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def getter(host, headers):
    def get(path):
        rq = urllib.request.Request(f"https://{host}{path}", headers=dict(headers, Accept="application/json"))
        try:
            with urllib.request.urlopen(rq, context=ctx(), timeout=60) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ReadFailed(f"{path.split('?')[0]} answered HTTP {e.code}: a provider credential is needed") from None
            return e.code, None
        except (urllib.error.URLError, OSError) as e:
            raise ReadFailed(f"{path.split('?')[0]}: {e}") from None
    return get


class Labels:
    # Words the product itself uses as ids (the default project, the infra space), kept verbatim like any other
    # product vocabulary: a scrub that replaced them would make the record unreadable and prove nothing.
    RESERVED = {"default", "infra"}

    def __init__(self):
        self.of, self.names = {}, set()

    def __call__(self, kind, key, *names):
        """A stable label for KEY; NAMES (display names, ids) are remembered so the record can be checked for them."""
        for n in (key, *names):
            if n and str(n) not in self.RESERVED:
                self.names.add(str(n))
        if not key:
            return None
        return self.of.setdefault((kind, key), f"{kind}-{sum(1 for k in self.of if k[0] == kind) + 1}")


def results(body):
    return (body or {}).get("results") or []


def read_nsx(L, mine):
    host = os.environ["NSX_HOST"]
    if os.environ.get("NSX_TOKEN_FILE"):
        auth = "Bearer " + read_secret("NSX_TOKEN_FILE")
    else:
        auth = "Basic " + base64.b64encode(f"{os.environ['NSX_USER']}:{read_secret('NSX_PASSWORD_FILE')}".encode()).decode()
    get = getter(host, {"Authorization": auth})
    st, t0s = get("/policy/api/v1/infra/tier-0s")
    if st != 200:
        raise ReadFailed(f"the Tier-0 list answered HTTP {st}")
    tier0s = []
    for t in results(t0s):
        st, ls = get(f"/policy/api/v1/infra/tier-0s/{t['id']}/locale-services")
        paths = [x["edge_cluster_path"] for x in results(ls) if x.get("edge_cluster_path")]
        clusters = []
        for ecp in paths:
            # The policy path and the management API name the same cluster by different ids, so the nodes are read
            # under the policy path itself.
            st, en = get(f"/policy/api/v1{ecp}/edge-nodes")
            clusters.append({"edgeCluster": L("edge-cluster", ecp, ecp.rsplit("/", 1)[-1]),
                             "edgeNodes": len(results(en)) if st == 200 else None})
        tier0s.append({"tier0": L("tier0", t["path"], t.get("id"), t.get("display_name")), "haMode": t.get("ha_mode"),
                       "failoverMode": t.get("failover_mode"), "edgeClusters": clusters})
    st, gcs = get("/policy/api/v1/infra/gateway-connections")
    gconns = {g["path"]: {"gatewayConnection": L("gateway-connection", g["path"], g.get("id"), g.get("display_name")),
                          "tier0": L("tier0", g.get("tier0_path")), "transitGatewaysAttached": 0} for g in results(gcs)}
    st, prj = get("/policy/api/v1/orgs/default/projects")
    if st != 200:
        raise ReadFailed(f"the NSX project list answered HTTP {st}")
    projects = []
    for p in results(prj):
        pid, base = p["id"], f"/policy/api/v1/orgs/default/projects/{p['id']}"
        row = {"project": L("project", p["path"], pid, p.get("display_name")), "default": pid == "default",
               "yours": bool(mine) and mine in (pid, p.get("display_name")),
               "namesTier0Itself": len(p.get("tier_0s") or []), "externalBlocks": len(p.get("external_ipv4_blocks") or []),
               "transitGateways": []}
        st, tgs = get(f"{base}/transit-gateways")
        for g in results(tgs):
            st, att = get(f"{base}/transit-gateways/{g['id']}/attachments")
            conns = [a.get("connection_path") for a in results(att) if a.get("connection_path")]
            for c in conns:
                if c in gconns:
                    gconns[c]["transitGatewaysAttached"] += 1
            row["transitGateways"].append({"transitGateway": L("transit-gateway", g["path"], g.get("display_name")),
                                           "default": bool(g.get("is_default")),
                                           "attachedTo": [L("gateway-connection", c) for c in conns]})
        st, cps = get(f"{base}/vpc-connectivity-profiles")
        row["connectivityProfiles"] = [{"profile": L("profile", c["path"], c.get("display_name")),
                                        "transitGateway": L("transit-gateway", c.get("transit_gateway_path")),
                                        "externalBlocks": len(c.get("external_ip_blocks") or []),
                                        "serviceGateway": bool((c.get("service_gateway") or {}).get("enable"))}
                                       for c in results(cps)]
        st, vps = get(f"{base}/vpcs")
        vpcs = results(vps)
        for v in vpcs:
            L("vpc", v["path"], v.get("id"), v.get("display_name"))
        row["vpcs"] = len(vpcs)
        projects.append(row)
    st, ver = get("/api/v1/node/version")
    st, ib = get("/policy/api/v1/infra/ip-blocks")
    vis = {}
    for b in results(ib):
        vis[str(b.get("visibility") or "unset")] = vis.get(str(b.get("visibility") or "unset"), 0) + 1
    return {"nsxVersion": (ver or {}).get("product_version"),
            "tier0s": tier0s, "gatewayConnections": list(gconns.values()), "projects": projects,
            "ipBlocks": {"total": len(results(ib)), "byVisibility": vis}}


def read_zones(L):
    host = os.environ["VC_HOST"]
    basic = base64.b64encode(f"{os.environ['VC_USER']}:{read_secret('VC_PASSWORD_FILE')}".encode()).decode()
    rq = urllib.request.Request(f"https://{host}/api/session", method="POST", headers={"Authorization": f"Basic {basic}"})
    try:
        with urllib.request.urlopen(rq, context=ctx(), timeout=60) as r:
            sid = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ReadFailed(f"the vCenter sign-in answered HTTP {e.code}") from None
    try:
        get = getter(host, {"vmware-api-session-id": sid})
        st, ver = get("/api/appliance/system/version")
        st, clusters = get("/api/vcenter/cluster")
        st, zs = get("/api/vcenter/consumption-domains/zones")
        if st != 200:
            raise ReadFailed(f"the zone list answered HTTP {st}")
        zones, seen = [], []
        for z in ((zs or {}).get("items") if isinstance(zs, dict) else zs) or []:
            st, assoc = get(f"/api/vcenter/consumption-domains/zones/cluster/{z['zone']}/associations")
            seen += assoc or []
            zones.append({"zone": L("zone", z["zone"], z["zone"]), "clusters": [L("cluster", c, c) for c in assoc or []]})
        return {"vcenterVersion": (ver or {}).get("version"), "zones": zones, "clusters": len(clusters or []),
                "clustersInAZone": len(set(seen)),
                "clusterInTwoZones": len(seen) != len(set(seen))}
    finally:
        try:
            urllib.request.urlopen(urllib.request.Request(f"https://{host}/api/session", method="DELETE",
                                                          headers={"vmware-api-session-id": sid}), context=ctx(), timeout=30).close()
        except (urllib.error.URLError, OSError):
            pass


def show(rec):
    print(f"  NSX {rec.get('nsxVersion')}" + (f", vCenter {rec['compute'].get('vcenterVersion')}" if rec.get("compute") else ""))
    for t in rec["tier0s"]:
        e = ", ".join(f"{c['edgeCluster']} ({c['edgeNodes']} nodes)" for c in t["edgeClusters"]) or "none"
        print(f"  {t['tier0']}: {t['haMode']}, {t['failoverMode']}, on {e}")
    for g in rec["gatewayConnections"]:
        print(f"  {g['gatewayConnection']} -> {g['tier0']}: {g['transitGatewaysAttached']} transit gateway(s) attached")
    for p in rec["projects"]:
        tags = ", ".join(x for x in ("default" if p["default"] else "", "yours" if p["yours"] else "") if x)
        tg = "; ".join(f"{t['transitGateway']} -> {', '.join(t['attachedTo']) or 'NO ATTACHMENT'}" for t in p["transitGateways"])
        cp = "; ".join(f"{c['profile']} ({c['externalBlocks']} external block(s), service gateway "
                       f"{'on' if c['serviceGateway'] else 'off'})" for c in p["connectivityProfiles"])
        print(f"  {p['project']}{' [' + tags + ']' if tags else ''}: {p['vpcs']} VPC(s); {tg}; {cp}; "
              f"names a Tier-0 itself: {p['namesTier0Itself']}")
    print(f"  ip blocks: {rec['ipBlocks']['total']}, {rec['ipBlocks']['byVisibility']}")
    z = rec.get("compute")
    if z:
        for x in z["zones"]:
            print(f"  {x['zone']} -> {', '.join(x['clusters']) or 'no cluster'}")
        print(f"  clusters in a zone: {z['clustersInAZone']} of {z['clusters']}; a cluster in two zones: {z['clusterInTwoZones']}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    mine = None
    if argv:
        if argv[0] != "--project" or len(argv) != 2:
            raise KeyError("the only argument is --project <your NSX project id or display name>")
        mine = argv[1]
    L = Labels()
    print("overlay.py: what the provider runs above a VPC\n")
    rec = {"capturedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **read_nsx(L, mine)}
    if os.environ.get("VC_HOST"):
        rec["compute"] = read_zones(L)
    show(rec)
    text = json.dumps(rec, indent=1)
    for n in sorted(L.names, key=len, reverse=True):
        if len(n) >= 4 and re.search(r"(?<![A-Za-z0-9-])" + re.escape(n) + r"(?![A-Za-z0-9-])", text):
            raise SystemExit(f"FATAL: a name ({len(n)} characters) reached the record")
    for var in ("NSX_HOST", "VC_HOST", "NSX_USER", "VC_USER"):
        if os.environ.get(var) and os.environ[var] in text:
            raise SystemExit(f"FATAL: {var} reached the record")
    out = os.path.join(os.environ.get("OUT_DIR", "."), "overlay.json")
    open(out, "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote {os.path.basename(out)}; every object name replaced by a label")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, PermissionError) as e:
        print(f"overlay.py: {e}", file=sys.stderr)
        sys.exit(2)
    except (ReadFailed, urllib.error.URLError, OSError) as e:
        print(f"READ FAILED: {e}", file=sys.stderr)
        sys.exit(3)
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            sys.exit(4 if e.code.startswith("FATAL") else 2)
        raise
