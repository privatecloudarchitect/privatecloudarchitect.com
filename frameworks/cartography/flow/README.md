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
python3 discover_flows.py                                  # pull the last 24h, print the findings
python3 discover_flows.py --hours 168 --min-fan-in 5       # a week, stricter shared-service threshold
python3 discover_flows.py --hours 168 --export findings.json
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

`python3 discover_flows.py --self-test` runs the whole pure pipeline on a shipped fixture
(`fixtures/flows.json`, twenty-two synthetic flows covering two infrastructure shared services, a
review case, a three-tier app, a two-tier app, and an unnamed cluster) and compares the result
against the golden findings (`fixtures/expected-findings.json`). No vRNI, deterministic. Run it to
confirm the analysis before you point it at an estate; the pure cores (`lib/_shared_services.py`,
`lib/_boundaries.py`) carry no I/O, which is exactly what makes them offline-checkable.

## What this lens carries, and what it does not

It carries Phases 4 and 5 of [the method](../METHOD.md): shared-services extraction and
boundary-plus-tier clustering, on port-only heuristics. That is the flow lens's defining capability
and it is self-contained, flow-only.

It does not carry the fuller triangulation: the identity anchor (vRNI's own authoritative entity
typing, which turns a host-data-plane port guess into a proven VCF-component role), the environment
and security-zone overlay, and the arbitration that fuses the flow lens with the supervisor and
metadata lenses into one confidence-scored classification per workload. Those live in the platform's
`pca vcf-opsnet discover-*` commands and are the natural next slice of this estate.

## The method and the other lens

[`../METHOD.md`](../METHOD.md) is the whole ten-phase method on one page. The narrative teaching, with
the live evidence, is the [Discovery and naming](https://privatecloudarchitect.com/handbook/cartography)
chapter series. The [supervisor lens](../README.md) is the other half of this framework: where a
workload declares its identity as Kubernetes labels, read it rather than infer it, and adopt that lens
first because its source is authoritative.
