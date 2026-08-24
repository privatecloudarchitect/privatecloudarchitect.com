#!/usr/bin/env python3
"""Converge one Ping Adapter instance's address list to checks.yaml (dry-run by default).

The L1 reachability crawl: one Ping Adapter instance, owned by name, whose address list converges to
the addresses you declare in checks.yaml (an IP, an FQDN, a CIDR, or a range). Level-triggered and
idempotent, so run it as often as you like. It touches ONLY the instance named in checks.yaml, and it
prunes the check objects for addresses you have removed. Nothing else on the estate is affected.

  export OPS_HOST=ops.example.com  OPS_API_TOKEN=...  OPS_TLS_VERIFY=false   # self-signed CA
  python reconcile_checks.py                        # dry-run: the convergence plan
  python reconcile_checks.py --execute              # apply (create or update, start), then poll
  python reconcile_checks.py --status               # read-only: the checks and their loss / latency
  python reconcile_checks.py --config-file          # OFFLINE: emit the native address-list XML
  python reconcile_checks.py --teardown --execute   # stop and delete this instance
"""
import argparse
import re
import sys
import time
from pathlib import Path

import yaml

from opslib import bearer, ops

HERE = Path(__file__).resolve().parent
CHECKS_YAML = HERE / "checks.yaml"
# peak_* are the non-instanced ping-check stats: peak packet loss and peak latency read straight off
# the check object, no computed metric required. That is what makes the crawl dependency-free.
L1_STATS = ("peak_packet_loss", "peak_latency")


def req(method, path, tok, body=None, params=None):
    """One Ops call that raises on HTTP error and returns the parsed body."""
    p = dict(params or {})
    p.setdefault("_no_links", "true")
    status, data = ops(method, path, tok, body=body, params=p)
    if status >= 300:
        raise SystemExit(f"{method} {path} -> HTTP {status}: {data}")
    return data or {}


def load_source():
    doc = yaml.safe_load(open(CHECKS_YAML, encoding="utf-8"))
    inst = doc.get("instance") or {}
    if not inst.get("name"):
        raise SystemExit("checks.yaml needs an instance.name (the Ping Adapter instance this owns)")
    checks = sorted({str(c["address"]).strip() for c in doc.get("checks") or [] if c.get("address")})
    if not checks:
        raise SystemExit("checks.yaml declares no checks")
    return inst, checks


def emit_config_file(checks):
    """Render VMware's native Ping-adapter AddressList XML (the conf_file_name form).

    The AddressList accepts the SAME grammar as the API address list: individual IPs, CIDRs
    (10.0.0.0/24), ranges (a.b.c.1-a.b.c.254), and FQDNs, so one line can cover a whole subnet.
    Upload it via Administration > Management Packs Configuration and point the adapter's
    conf_file_name at it, as an ALTERNATIVE to the API-converged address list (use one or the other).
    """
    body = ", ".join(checks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<AdapterKinds>\n"
        '    <AdapterKind adapterKindKey="PingAdapter">\n'
        "        <AddressList>\n"
        f"            {body}\n"
        "        </AddressList>\n"
        "    </AdapterKind>\n"
        "</AdapterKinds>\n"
    )


def collector_group_id(tok, name):
    for g in req("GET", "/api/collectorgroups", tok).get("collectorGroups", []):
        if g.get("name") == name:
            return g["id"]
    raise SystemExit(f"collector group {name!r} not found (set instance.collector_group in checks.yaml)")


def find_instance(tok, name):
    body = req("GET", "/api/adapters", tok, params={"adapterKindKey": "PingAdapter"})
    for a in body.get("adapterInstancesInfoDto", []):
        if a.get("resourceKey", {}).get("name") == name:
            return a
    return None


def identifier_value(inst, key):
    for ri in inst.get("resourceKey", {}).get("resourceIdentifiers", []):
        if ri.get("identifierType", {}).get("name") == key:
            return ri.get("value")
    return None


def desired_identifiers(inst_cfg, name, address_list):
    # unique_name is the pack's internal identifier and MUST be a plain slug: a space or punctuation
    # in it makes the adapter silently load zero checks while heartbeating healthy. Derive one from
    # the name if the config omits it.
    slug = inst_cfg.get("unique_name") or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    ids = [{"name": "unique_name", "value": slug}, {"name": "address_list", "value": address_list}]
    for k, v in (inst_cfg.get("settings") or {}).items():
        ids.append({"name": str(k), "value": str(v)})
    return ids


def instance_resources(tok, aid):
    body = req("GET", f"/api/adapters/{aid}/resources", tok)
    out = []
    for r in body.get("resourceList", []):
        rk = r.get("resourceKey", {})
        out.append((rk.get("resourceKindKey", "?"), rk.get("name", "?"), r.get("identifier")))
    return out


def prune_stale_checks(tok, aid, desired, execute):
    """Converge the check objects to exactly the desired addresses (plus the resolved-IP children an
    FQDN still owns). Removing an address stops the ping but leaves the object behind, red and still
    counted, so an unpruned run drifts. Two-phase: find all victims against the pre-deletion graph,
    then delete, so removing an FQDN never hides its now-orphaned child mid-pass."""
    body = req("GET", f"/api/adapters/{aid}/resources", tok)
    victims = []
    for r in body.get("resourceList", []):
        rk = r.get("resourceKey", {})
        if rk.get("resourceKindKey") not in ("ip_type", "fqdn_type"):
            continue
        name = rk.get("name", "")
        if name in desired:
            continue
        parents = [p.get("resourceKey", {}) for p in
                   req("GET", f"/api/resources/{r['identifier']}/relationships/parents", tok).get("resourceList", [])]
        if any(pk.get("resourceKindKey") == "fqdn_type" and pk.get("name") in desired for pk in parents):
            continue  # the adapter re-mints this child under a live FQDN every cycle; keep it
        victims.append((name, r["identifier"]))
    for name, rid in victims:
        if not execute:
            print(f"  DRY-RUN would prune stale check {name}")
        else:
            req("DELETE", f"/api/resources/{rid}", tok)
            print(f"  pruned stale check {name}")
    return len(victims)


def latest_l1(tok, rid):
    body = req("POST", "/api/resources/stats/latest/query", tok,
               body={"resourceId": [rid], "statKey": list(L1_STATS)})
    out = {k: None for k in L1_STATS}
    for v in body.get("values", []):
        for s in v.get("stat-list", {}).get("stat", []):
            key = s.get("statKey", {}).get("key")
            data = s.get("data") or []
            if key in out and data:
                out[key] = data[-1]
    return out


def show_status(tok, inst):
    aid = inst["id"]
    print(f"instance: {inst['resourceKey']['name']}  id={aid[:8]}  lastHeartbeat={inst.get('lastHeartbeat')}")
    print(f"  address_list = {identifier_value(inst, 'address_list')!r}")
    checks = [r for r in instance_resources(tok, aid) if r[0] in ("ip_type", "fqdn_type")]
    print(f"  minted checks: {len(checks)}")
    for kind, name, rid in checks:
        stats = latest_l1(tok, rid) if rid else {}
        loss, lat = stats.get("peak_packet_loss"), stats.get("peak_latency")
        loss_s = f"{loss:.0f}% loss" if loss is not None else "no data yet"
        lat_s = f"{lat:.1f} ms" if lat is not None else "-"
        print(f"    {kind:10} {name:34} {loss_s:14} {lat_s}")


def main():
    ap = argparse.ArgumentParser(description="Converge one Ping Adapter instance to checks.yaml (L1 reachability crawl)")
    ap.add_argument("--execute", action="store_true", help="apply (default: dry-run)")
    ap.add_argument("--status", action="store_true", help="read-only: the checks and their latest loss / latency")
    ap.add_argument("--teardown", action="store_true", help="stop and delete this instance")
    ap.add_argument("--config-file", action="store_true", help="OFFLINE: emit the native address-list XML for upload")
    ap.add_argument("--poll-minutes", type=float, default=4.0, help="how long to wait for checks to mint after an execute")
    args = ap.parse_args()

    inst_cfg, checks = load_source()
    name = inst_cfg["name"]
    address_list = ",".join(checks)

    if args.config_file:
        out = HERE / "ping_adapter_config.xml"
        out.write_text(emit_config_file(checks), encoding="utf-8")
        print(f"wrote {out.name} ({len(checks)} address entries).\n")
        print(out.read_text(encoding="utf-8"))
        print("Upload via Administration > Management Packs Configuration, then set the adapter's conf_file_name to it.")
        return 0

    tok = bearer()
    live = find_instance(tok, name)

    if args.status:
        show_status(tok, live) if live else print(f"instance {name!r} not present")
        return 0

    if args.teardown:
        if not live:
            print(f"instance {name!r} not present, nothing to tear down")
            return 0
        if not args.execute:
            print(f"DRY-RUN would stop and DELETE adapter instance {name!r} (id {live['id'][:8]})")
            return 0
        req("PUT", f"/api/adapters/{live['id']}/monitoringstate/stop", tok)
        req("DELETE", f"/api/adapters/{live['id']}", tok)
        print(f"teardown: deleted; gone = {find_instance(tok, name) is None}")
        return 0

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"reachability L1 converge · {mode}")
    print(f"  desired: {len(checks)} check(s) -> address_list = {address_list!r}")

    if live is None:
        gid = collector_group_id(tok, inst_cfg.get("collector_group", "Default collector group"))
        payload = {"name": name, "adapterKindKey": "PingAdapter",
                   "description": "Reachability crawl - L1 checks (checks.yaml)", "collectorGroupId": gid,
                   "resourceIdentifiers": desired_identifiers(inst_cfg, name, address_list)}
        if not args.execute:
            print(f"  DRY-RUN would CREATE instance {name!r} on {inst_cfg.get('collector_group')!r} + start")
            return 0
        aid = req("POST", "/api/adapters", tok, body=payload).get("id")
        print(f"  created instance id={str(aid)[:8]}")
        req("PUT", f"/api/adapters/{aid}/monitoringstate/start", tok)
        print("  monitoring started")
    else:
        aid = live["id"]
        desired_map = {d["name"]: d["value"] for d in desired_identifiers(inst_cfg, name, address_list)}
        live_map = {ri.get("identifierType", {}).get("name"): str(ri.get("value"))
                    for ri in live.get("resourceKey", {}).get("resourceIdentifiers", [])}
        drift = {k: (live_map.get(k), v) for k, v in desired_map.items() if str(live_map.get(k)) != str(v)}
        if not drift:
            print(f"  instance exists (id {aid[:8]}) and all identifiers converged, no-op")
        else:
            print(f"  instance exists (id {aid[:8]}); identifier drift:")
            for k, (was, want) in sorted(drift.items()):
                print(f"    {k}: live={was!r} desired={want!r}")
            if not args.execute:
                print("  DRY-RUN would PUT the updated identifiers")
                prune_stale_checks(tok, aid, set(checks), False)
                return 0
            rk = live["resourceKey"]
            keep = [ri for ri in rk.get("resourceIdentifiers", [])
                    if ri.get("identifierType", {}).get("name") not in desired_map]
            for ri_name, ri_value in desired_map.items():
                dtype = "STRING" if not str(ri_value).lstrip("-").isdigit() else "INTEGER"
                keep.append({"identifierType": {"name": ri_name, "dataType": dtype,
                                                "isPartOfUniqueness": ri_name == "unique_name"}, "value": str(ri_value)})
            rk["resourceIdentifiers"] = keep
            req("PUT", "/api/adapters", tok,
                body={"id": aid, "resourceKey": rk, "collectorGroupId": live.get("collectorGroupId"),
                      "description": live.get("description")})
            req("PUT", f"/api/adapters/{aid}/monitoringstate/start", tok)
            print(f"  updated {len(drift)} identifier(s) + (re)started monitoring")

    deadline = time.time() + args.poll_minutes * 60
    minted = []
    while time.time() < deadline:
        live = find_instance(tok, name)
        minted = [r for r in instance_resources(tok, live["id"]) if r[0] in ("ip_type", "fqdn_type")] if live else []
        if len(minted) >= len(checks):
            break
        time.sleep(15)
    print(f"\n  minted {len(minted)} check resource(s) (expected >= {len(checks)}):")
    for kind, rname, _ in minted:
        print(f"    {kind:10} {rname}")
    if len(minted) < len(checks):
        print("  (collection may still be warming; re-run --status in a few minutes)")
    pruned = prune_stale_checks(tok, live["id"], set(checks), args.execute)
    if pruned:
        print(f"  {'pruned' if args.execute else 'would prune'} {pruned} stale check object(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
