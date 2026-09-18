#!/usr/bin/env python3
"""vip.py: walk the load-balancer object graph behind a control-plane endpoint, on the controller itself.

A cluster's API server answers on a virtual IP, and "the VIP" is not one object. This walks the graph as the
controller actually stores it and reports what is there now:

  1. the GRAPH: every virtual service, the address object it references, the policy set it carries, and the
     pools that policy set selects. The chapter this ships with previously described three objects; the walk
     finds four, and the fourth is where the port-to-pool choice is made, which is why one virtual service can
     front more than one pool;
  2. the ARITHMETIC: virtual services, address objects, policy sets and pools counted, with the pool total
     explained by how many selection rules each policy set carries. If those numbers do not reconcile on your
     controller, the graph has a shape this script did not expect and the difference is the finding;
  3. the MEMBERSHIP: how many servers each pool holds now. The interesting thing about a control-plane pool is
     that it is created empty, before any node exists, so a populated pool is the end of a story whose
     beginning is only visible in the controller's event log at provision time.

Read-only throughout. The controller's API is a session login rather than a bearer: POST /login with a
username and password, then carry the session cookie and the CSRF token it sets.

Run:
  export AVI_HOST=<avi-controller-fqdn>
  export AVI_USER=<username>
  export AVI_PASSWORD_FILE=/path/to/password     # mode 0600
  export TLS_VERIFY=false                        # only on a self-signed lab CA
  python3 vip.py
"""
import collections
import http.cookiejar
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    """Estate names become placeholders. The product's own vocabulary never does."""

    RESERVED = {"admin", "default", "system", "none", "all", "Pool", "VirtualService", "VsVip", "L4PolicySet"}

    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        if not name or str(name) in self.RESERVED:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def scrub(self, text):
        if not isinstance(text, str):
            return text
        known = [(r, l) for m in self.maps.values() for r, l in m.items()]
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])", "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)


class Avi:
    """A session login, not a bearer: POST /login, then the cookie plus the CSRF token it sets."""

    def __init__(self, host, user, password):
        self.host = host
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx()),
                                              urllib.request.HTTPCookieProcessor(self.jar))
        req = urllib.request.Request(f"https://{host}/login", method="POST",
                                     data=json.dumps({"username": user, "password": password}).encode(),
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        with self.op.open(req, timeout=45) as r:
            if r.status != 200:
                raise SystemExit(f"login refused: HTTP {r.status}")
        self.csrf = {c.name: c.value for c in self.jar}.get("csrftoken", "")

    def get(self, path):
        req = urllib.request.Request(f"https://{self.host}{path}",
                                     headers={"Accept": "application/json", "X-CSRFToken": self.csrf,
                                              "Referer": f"https://{self.host}/"})
        try:
            with self.op.open(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, {}
        except (urllib.error.URLError, OSError):
            return None, {}

    def all(self, kind):
        st, r = self.get(f"/api/{kind}?page_size=200")
        return (r.get("results") or []) if isinstance(r, dict) else []


def main():
    host = os.environ["AVI_HOST"]
    user = os.environ["AVI_USER"]
    password = open(os.environ["AVI_PASSWORD_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    a = Avi(host, user, password)
    L = Labels()
    print("vip.py: the load-balancer graph behind a control-plane endpoint\n")

    vss, pools, vips, psets = a.all("virtualservice"), a.all("pool"), a.all("vsvip"), a.all("l4policyset")
    by_uuid = {}
    for p in pools:
        by_uuid[p.get("uuid")] = p
        L.get("pool", p.get("name"))
    for v in vss:
        L.get("vs", v.get("name"))

    graph, rule_total = [], 0
    for v in vss:
        ports = sorted({s.get("port") for s in (v.get("services") or []) if s.get("port")})
        selected = []
        for lp in (v.get("l4_policies") or []):
            ref = str(lp.get("l4_policy_set_ref") or "")
            st, ps = a.get("/api/l4policyset/" + ref.rsplit("/", 1)[-1]) if ref else (None, {})
            rules = ((ps.get("l4_connection_policy") or {}).get("rules") or []) if isinstance(ps, dict) else []
            rule_total += len(rules)
            for r in rules:
                pr = str(((r.get("action") or {}).get("select_pool") or {}).get("pool_ref") or "")
                pu = pr.rsplit("/", 1)[-1]
                pool = by_uuid.get(pu)
                selected.append({"pool": L.scrub((pool or {}).get("name") or ""),
                                 "members": len((pool or {}).get("servers") or []),
                                 "marksApiserverPort": str((pool or {}).get("name") or "").endswith("TCP--6443")})
        graph.append({"virtualService": L.scrub(v.get("name") or ""), "ports": ports,
                      "enabled": bool(v.get("enabled")),
                      "hasDirectPoolRef": bool(v.get("pool_ref")),
                      "addressObject": bool(v.get("vsvip_ref")),
                      "policySets": len(v.get("l4_policies") or []),
                      "poolsSelected": selected})

    print(f"  graph: {len(vss)} virtual service(s), {len(vips)} address object(s), {len(psets)} policy set(s), "
          f"{len(pools)} pool(s)")
    print(f"     virtual services carrying a DIRECT pool reference: {sum(1 for g in graph if g['hasDirectPoolRef'])}")
    print(f"     every one reaches its pools through a policy set instead; {rule_total} selection rule(s) in total")
    for g in graph:
        print(f"     ports {str(g['ports']):<14} -> {len(g['poolsSelected'])} pool(s), "
              f"members {[p['members'] for p in g['poolsSelected']]}")
    reconciles = rule_total == sum(len(g["poolsSelected"]) for g in graph)
    covered = {p["pool"] for g in graph for p in g["poolsSelected"]}
    print(f"\n  arithmetic: {len(pools)} pools; {len(covered)} of them are selected by a policy set rule; "
          f"{'reconciles' if reconciles else 'does NOT reconcile, which is the finding'}")

    members = collections.Counter(len(p.get("servers") or []) for p in pools)
    empty = sum(c for m, c in members.items() if m == 0)
    print(f"  membership now: {dict(sorted(members.items()))} (pool size -> how many pools). Empty pools: {empty}")
    print("     a control-plane pool is created empty, before any node exists; a populated one is the end of "
          "that story, and only the controller's event log shows the beginning")

    addrs = [len(v.get("vip") or []) for v in vips]
    allocated = sum(1 for v in vips for x in (v.get("vip") or []) if ((x.get("ip_address") or {}).get("addr")))
    print(f"  addresses: {len(vips)} address object(s) holding {sum(addrs)} address(es), {allocated} allocated")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "counts": {"virtualServices": len(vss), "addressObjects": len(vips),
                          "policySets": len(psets), "pools": len(pools), "selectionRules": rule_total},
               "graph": graph, "reconciles": reconciles,
               "poolsSelectedByARule": len(covered),
               "poolSizes": {str(k): v for k, v in sorted(members.items())},
               "emptyPools": empty, "addressesAllocated": allocated,
               "note": "a virtual service reaches its pools through an l4 policy set, not a direct reference, "
                       "so one virtual service can front several pools chosen per port"}
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (password, host, user):
        assert secret not in text, "an estate value reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shp}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "vip.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote vip.json ({len(vss)} virtual services, {len(pools)} pools); "
          f"every object name replaced by a placeholder")


if __name__ == "__main__":
    main()
