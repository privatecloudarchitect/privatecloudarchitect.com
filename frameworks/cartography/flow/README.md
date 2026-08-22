# Cartography flow lens: discover applications from the flow graph

The second lens of the cartography framework, and the one the method calls primary. Where the
[supervisor lens](../README.md) reads a classification Kubernetes-managed workloads already declare,
the flow lens infers one from behaviour: it is the only instrument that shows the real east-west
dependency graph. It pulls the flows VCF Operations for Networks already collects, quarantines the
shared services (the high-fan-in DNS / AD / NTP / platform nodes that otherwise make every
application look adjacent to every other), then clusters the remaining VM-to-VM graph into candidate
applications and assigns each member a tier from the ports it serves.

Read-only. Nothing is written and nothing is tagged: the output is a defensible proposal, every
verdict carrying its basis, that an admin confirms and then hands to the supervisor lens's write-back
or to their own tagging. It leaves your estate exactly as it found it.

## Dependencies and environment

Python 3 plus exactly `pydantic`. One plane, from the environment:

```bash
export VRNI_HOST=<vrni-fqdn> VRNI_USERNAME=<user> VRNI_PASSWORD=<password>
export VRNI_INSECURE=1     # only on a self-signed lab CA
# VRNI_DOMAIN defaults to LOCAL; for a directory user use LDAP:<domain>, e.g. LDAP:example.com
```

The credential is a vRNI user (Settings, User Management). The NetworkInsight auth path this uses is
self-contained: it works with a local vRNI account whether or not the appliance is wired to VCF
Operations' unified identity, so you need nothing but an account.

## The recipe

```bash
python3 discover_flows.py                                  # Phases 4-5: shared services + boundaries
python3 discover_flows.py --hours 168 --export findings.json

python3 discover_arbitration.py                            # Phases 4-7: one scored classification per VM
python3 discover_arbitration.py --declared recs.json       # fuse the supervisor lens's export
python3 discover_arbitration.py --hours 168 --export report.json
```

The findings are two lists. **Shared services** are destinations reached by many distinct sources on
infrastructure ports (`shared-service`), plus the ambiguous cases reached only on a web port
(`review`, a shared service or a popular front-end, confirm which). **Applications** are the clusters
the VM-to-VM graph decomposes into once the shared services are quarantined, each member tiered
`web` / `app` / `data` from the ports it serves, each cluster named from its members' common stem (or
`app-cluster-N` when there is none). Flows are a sampled behavioural signal: budget a full business
cycle, two to four weeks, before you trust a "no dependency" conclusion, because absence of a flow is
only evidence once you have watched long enough for it to have appeared.

## The offline self-test

Both entries carry one. `python3 discover_flows.py --self-test` runs Phases 4-5 on a twenty-two-flow
synthetic fixture; `python3 discover_arbitration.py --self-test` runs the whole Phase 4-7 pipeline on a
fixture that exercises every path (the identity anchor typing an ESXi host, a flow-only shared service,
a four-lens high-confidence application, a data-tier-in-dmz conflict, and a low-information VM). Each
compares against a golden report, no vRNI, deterministic. Run them to confirm the analysis before you
point anything at an estate; the pure cores carry no I/O, which is what makes them offline-checkable.

## What this lens carries

It carries the whole read-only pipeline of [the method](../METHOD.md), Phases 4 through 7:

- **Phase 4, shared services** (`lib/_shared_services.py`) with the **identity anchor**
  (`lib/_identity.py`): vRNI's own authoritative entity typing turns a host-data-plane port guess into
  a proven VCF-component role, so an ESXi host or NSX node is recognised with certainty rather than
  guessed from a port.
- **Phase 5, boundaries + tiers** (`lib/_boundaries.py`): the shared-service-free graph clustered into
  tiered applications.
- **Phase 6, environment + zone** (`lib/_env_zone.py`): env from naming and placement, zone from
  security constructs and observed internet exposure.
- **Phase 7, arbitration** (`lib/_arbitrate.py`, `discover_arbitration.py`): fuse the lenses into one
  confidence-scored classification per VM, with the conflicts a human must confirm. The optional
  declared lens (`--declared`, the supervisor lens's export) is authoritative where present.

`discover_flows.py` runs Phases 4-5; `discover_arbitration.py` runs all of 4-7. Confirmed
classifications hand to the [supervisor lens's write-back](../README.md) (Phase 8); keeping the map
true on a cadence (Phase 9) is the standing governance loop.

## The method and the other lens

[`../METHOD.md`](../METHOD.md) is the whole ten-phase method on one page. The narrative teaching, with
the live evidence, is the [Discovery and naming](https://privatecloudarchitect.com/handbook/cartography)
chapter series. The [supervisor lens](../README.md) is the other half of this framework: where a
workload declares its identity as Kubernetes labels, read it rather than infer it, and adopt that lens
first because its source is authoritative.
