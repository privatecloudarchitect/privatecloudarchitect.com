#!/usr/bin/env python3
"""sizing.py: size and lay out a VCF 9.1 Log Management instance for an estate you describe.

It is arithmetic on the product's published figures and reads nothing from any system. Give it your sites and, if you
have them, your high-volume application sources; it answers with the Log Management size and replica count, what sets
that count (ingestion or storage), the worker nodes the VCF management services cluster grows to, the node addresses
in use and to budget, and the VIPs with each gateway's load.

    python sizing.py --example                      the made-up estate the field note opens on
    python sizing.py estate.json                    your estate (see --template)
    python sizing.py --template                     print a file to fill in
    python sizing.py estate.json --json             the same answer as JSON

Which part is the product's rule and which is this script's arithmetic:
  rule        per-replica event rate, replica and gateway sizes, 19 replicas at most, 9 TB per replica, the worker size
              each Log Management size causes, two workers per Large replica, the address rule (12 for the runtime, 6
              for the installation, 1 per Small or Medium replica, 2 per Large), "N+1 or N+2" (VCF 9.1 design library)
  arithmetic  events per second from GB per day at a stated event size; the worker count (requests against capacity
              with 5% left unrequested); VIPs for agents and for each application, as many as their peak needs
              gateways; storage counted with every replica grown to 9 TB and filled to 80%, the level past which an
              archive import fails
The worker count is an estimate: the platform decides the real one. Connections per VIP are not modelled: count them
against the product's limits yourself. With nothing measured, the design library's estimate is 250 events per second
for each ESX host. Python 3.9+, standard library only.
"""
from __future__ import annotations
import argparse, json, math, sys

# Per size: the published per-replica event rate and resources, the gateway behind each VIP, the worker node the fleet
# sizing page gives for that Log Management size, node addresses per replica, the shards a replica holds, and the
# replica count past which the design library advises the next size ("once you exceed 5-6 small replicas, or large once
# you get to 6-8 medium replicas"; this script takes the lower bound of each range). "min" is the high availability
# model's three replicas; the size table itself allows one Small replica, the simple model, which this script does not
# size. store_cpu and proc_cpu are estimates: the split read on one Small replica, applied to the documented sizes.
SIZES = {
    "S": {"name": "Small", "eps": 20000, "cpu": 8, "gb": 16, "store_cpu": 5, "proc_cpu": 3, "worker_cpu": 16, "worker_gb": 32,
          "gw_cpu": 4, "gw_eps": 200000, "ip": 1, "min": 3, "advise": 5, "shards": 700},
    "M": {"name": "Medium", "eps": 40000, "cpu": 16, "gb": 32, "store_cpu": 10, "proc_cpu": 6, "worker_cpu": 24, "worker_gb": 48,
          "gw_cpu": 4, "gw_eps": 200000, "ip": 1, "min": 3, "advise": 6, "shards": 800},
    "L": {"name": "Large", "eps": 60000, "cpu": 32, "gb": 64, "store_cpu": 20, "proc_cpu": 12, "worker_cpu": 24, "worker_gb": 48,
          "gw_cpu": 6, "gw_eps": 300000, "ip": 2, "min": 3, "advise": 19, "shards": 900},
}
LIMITS = {"replicas": 19, "replica_tb": 9, "fill": 0.8, "pool_recommended": 30, "runtime_ips": 12, "install_ips": 6,
          "control_plane": 3, "proxy_buffer_gb": 20, "proxy_small_eps": 200000, "headroom": 0.95}
# Defaults to replace with your own. Only "head" is the vendor's (N+1). 347 bytes per event is derived: Configuration
# Maximums 9.1.0 lists each size's ingestion in GB per day beside its events per second, and the two divide to 347. The
# growth allowance, the stored ratio, the partition count and the other services' requests are placeholders, made up.
DEFAULTS = {"days": 30, "head": 1, "ratio": 1.0, "bytes": 347, "growth": 20, "fleetCpu": 60, "partitions": 4}
HOST_EPS = 250  # the design library's estimate when nothing is measured: events per second for each ESX host

EXAMPLE = {  # an example, made up: no estate has these numbers
    "sites": [{"name": "Site A", "fleet": 1, "infra": 140, "guest": 90}, {"name": "Site B", "fleet": 1, "infra": 80, "guest": 60},
              {"name": "Site C", "fleet": 1, "infra": 45, "guest": 30}, {"name": "Site D", "fleet": 1, "infra": 15, "guest": 5}],
    "apps": [],
}
EXAMPLES = {
    "ref": EXAMPLE,
    "app": {"sites": EXAMPLE["sites"], "apps": [{"name": "Application 1", "site": 1, "avg": 2.4, "peak": 3.6}]},
    "fleets": {"sites": [dict(s, fleet=1 if i < 2 else 2) for i, s in enumerate(EXAMPLE["sites"])],
               "apps": [{"name": "Application 1", "site": 1, "avg": 2.4, "peak": 3.6}]},
    "big": {"sites": EXAMPLE["sites"], "apps": [{"name": "Application 1", "site": 0, "avg": 5, "peak": 6.5},
                                                 {"name": "Application 2", "site": 1, "avg": 4, "peak": 7},
                                                 {"name": "Application 3", "site": 2, "avg": 3, "peak": 4}]},
}


def eps(gb_per_day: float, bytes_per_event: float) -> float:
    return gb_per_day * 1e9 / 86400 / bytes_per_event


def plan(estate: dict, fleet: int, **settings) -> dict:
    """The design for one fleet of `estate`. Sites carry GB per day (infra, guest); applications TB per day (avg, peak)
    and the index of their site. The first site listed in a fleet hosts its Log Management. Negative volumes count as 0."""
    s = {**DEFAULTS, **settings}
    pos = lambda v: max(0.0, float(v))  # noqa: E731
    idx = [i for i, x in enumerate(estate["sites"]) if x["fleet"] == fleet]
    sites = [estate["sites"][i] for i in idx]
    apps = [a for a in estate.get("apps", []) if a["site"] in idx]
    g = 1 + s["growth"] / 100
    base = sum(pos(x["infra"]) + pos(x["guest"]) for x in sites) * g
    avg = base + sum(pos(a["avg"]) * 1000 for a in apps)
    peak = base + sum(max(pos(a["avg"]), pos(a["peak"])) * 1000 for a in apps)
    pe = eps(peak, s["bytes"])
    key = "L"
    for c in ("S", "M", "L"):
        if max(SIZES[c]["min"], math.ceil(pe / SIZES[c]["eps"]) + s["head"]) <= SIZES[c]["advise"]:
            key = c
            break
    z = SIZES[key]
    usable = LIMITS["replica_tb"] * 1000 * LIMITS["fill"]  # GB a replica keeps searchable: grown to 9 TB, filled to 80%
    ing = max(z["min"], math.ceil(pe / z["eps"]) + s["head"])
    sto = max(z["min"], math.ceil(avg * s["days"] * s["ratio"] / usable))
    rep = max(ing, sto)
    sets = "storage" if sto > ing else "ingestion" if ing > sto else "the minimum" if rep == z["min"] else "both"
    vips = [{"name": "default", "avg": None, "peak": None}]
    guest = eps(sum(pos(x["guest"]) for x in sites) * g, s["bytes"])
    n = max(1, math.ceil(guest / z["gw_eps"]))
    for j in range(n):
        vips.append({"name": "agents" + (f"-{j + 1}" if n > 1 else ""), "avg": guest / n, "peak": guest / n})
    for a in apps:
        pk = eps(max(pos(a["avg"]), pos(a["peak"])) * 1000, s["bytes"])
        n = max(1, math.ceil(pk / z["gw_eps"]))
        for j in range(n):
            vips.append({"name": "agents-" + slug(a["name"]) + (f"-{j + 1}" if n > 1 else ""), "avg": eps(pos(a["avg"]) * 1000, s["bytes"]) / n, "peak": pk / n})
    vips.append({"name": "external", "avg": None, "peak": None})
    lay = layout(key, rep, len(vips), s["fleetCpu"])
    demand, workers = lay["demandCpu"], lay["workers"]
    shard_days = z["shards"] // max(1, int(s["partitions"]))
    return {"fleet": fleet, "host": sites[0]["name"], "size": z["name"], "key": key, "replicas": rep, "forIngestion": ing, "forStorage": sto,
            "sets": sets, "fits": rep <= LIMITS["replicas"], "pastAdvised": rep > z["advise"],
            "avgGb": avg, "peakGb": peak, "peakEps": pe, "capacityEps": rep * z["eps"], "storeTb": rep * LIMITS["replica_tb"],
            "daysHeld": (rep * usable / (avg * s["ratio"])) if avg > 0 and s["ratio"] > 0 else None,
            "shardDays": shard_days, "shardLimited": s["days"] > shard_days,
            "workers": workers, "workerCpu": z["worker_cpu"], "workerGb": z["worker_gb"],
            "demandCpu": demand, "addressesInUse": LIMITS["control_plane"] + workers,
            "addressBudget": LIMITS["runtime_ips"] + LIMITS["install_ips"] + rep * z["ip"], "vips": vips}


def layout(key: str, replicas: int, vips: int = 3, fleet_cpu: int = DEFAULTS["fleetCpu"]) -> dict:
    """What a size and replica count cause underneath: requests, worker nodes, node addresses in use and to budget."""
    z = SIZES[key]
    demand = fleet_cpu + replicas * z["cpu"] + vips * z["gw_cpu"]
    fit = math.ceil(demand / (z["worker_cpu"] * LIMITS["headroom"]))
    # a Large replica is spread across two workers (documented); otherwise the first count at which requests fit
    workers = max(2 * replicas, fit) if key == "L" else max(3, fit)
    return {"demandCpu": demand, "workers": workers, "inUse": LIMITS["control_plane"] + workers,
            "budget": LIMITS["runtime_ips"] + LIMITS["install_ips"] + replicas * z["ip"]}


def slug(name: str) -> str:
    out = "".join(ch if ch.isalnum() else "-" for ch in name.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "app"


def fleets(estate: dict) -> list[int]:
    return sorted({x["fleet"] for x in estate["sites"]})


def vol(gb: float) -> str:
    return f"{gb / 1000:,.1f} TB/day" if gb >= 1000 else f"{gb:,.0f} GB/day"


def report(estate: dict, **settings) -> list[str]:
    out = []
    s_ = {**DEFAULTS, **settings}
    for f in fleets(estate):
        p = plan(estate, f, **settings)
        out += [f"fleet {f}, Log Management at {p['host']}",
                f"  size and replicas     {p['size']} x {p['replicas']}  ({p['forIngestion']} for ingestion, {p['forStorage']} for storage; {p['sets']} sets the count)",
                f"  volume                {vol(p['avgGb'])} average, {vol(p['peakGb'])} at peak: {p['peakEps']:,.0f} events/s against {p['capacityEps']:,.0f}",
                f"  store                 {p['storeTb']} TB with every replica grown to {LIMITS['replica_tb']} TB (each deploys with about 0.5 TB); "
                + (f"about {p['daysHeld']:,.0f} days searchable at {LIMITS['fill']:.0%} full" if p["daysHeld"] is not None else "no volume entered"),
                f"  worker nodes          about {p['workers']} at {p['workerCpu']} vCPU / {p['workerGb']} GB, plus {LIMITS['control_plane']} control plane nodes (an estimate: the platform decides)",
                f"  node addresses        {p['addressesInUse']} in use, {p['addressBudget']} to budget, recommended pool {LIMITS['pool_recommended']}",
                "  VIPs                  " + ", ".join(v["name"] + (f" ({v['peak'] / 1000:,.0f}K events/s at peak)" if v["peak"] is not None else "") for v in p["vips"])]
        if p["shardLimited"]:
            out.append(f"  shard budget          {p['shardDays']} days at most with {s_['partitions']} partitions ({SIZES[p['key']]['shards']} shards a replica): fewer partitions, or fewer days")
        if not p["fits"]:
            out.append(f"  DOES NOT FIT          {p['replicas']} replicas against a maximum of {LIMITS['replicas']}: reduce volume, shorten the searchable window, or split into fleets")
        elif p["pastAdvised"]:
            out.append(f"  past the advised count for {p['size']}: consider fewer searchable days with an archive before adding replicas")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("estate", nargs="?", help="a JSON file shaped like --template")
    ap.add_argument("--example", action="store_true", help="size the made-up estate")
    ap.add_argument("--template", action="store_true", help="print an estate file to fill in")
    ap.add_argument("--json", action="store_true", help="print the plans as JSON")
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k, type=type(v), default=v)
    a = ap.parse_args(argv)
    if a.template:
        print(json.dumps({"_": "an example, made up: replace every value with yours", **EXAMPLES["app"]}, indent=2))
        return 0
    if not a.example and not a.estate:
        ap.error("give an estate file, or --example")
    estate = EXAMPLE if a.example else json.load(open(a.estate, encoding="utf-8"))
    settings = {k: getattr(a, k) for k in DEFAULTS}
    plans = [plan(estate, f, **settings) for f in fleets(estate)]
    print(json.dumps(plans, indent=2) if a.json else "\n".join((["an example, made up"] if a.example else []) + report(estate, **settings)))
    return 0 if all(p["fits"] for p in plans) else 1


if __name__ == "__main__":
    sys.exit(main())
