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

Python 3 plus exactly `pydantic`. One plane, configured from the environment, with the password read from a file
of mode 0600 (a file open to group or other is refused before it is read):

```bash
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vrni-password )       # paste the password, then Ctrl-D
export VRNI_HOST=<vrni-fqdn> VRNI_USERNAME=<user> VRNI_PASSWORD_FILE=~/.vcf/vrni-password
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
python3 discover_flows.py --hours 168 --record flows.json        # counts only: no name or address

python3 discover_arbitration.py                            # Phases 4-7: one scored classification per VM
python3 discover_arbitration.py --declared recs.json       # fuse the supervisor lens's export
python3 discover_arbitration.py --hours 168 --export report.json
python3 discover_arbitration.py --hours 168 --declared recs.json --confirmations confirmed.txt \
    --export-recommendations handoff.json --record arbitration.json   # the hand-off to the write-back
```

The findings are two lists. **Shared services** are destinations reached by many distinct sources on
infrastructure ports (`shared-service`), plus the ambiguous cases reached only on a web port
(`review`, a shared service or a popular front-end, confirm which). **Applications** are the clusters
the VM-to-VM graph decomposes into once the shared services are quarantined, each member tiered
`web` / `app` / `data` from the ports it serves, each cluster named from its members' common stem (or
`app-cluster-N` when there is none). Flows are a sampled behavioural signal: budget a full business
cycle, two to four weeks, before you trust a "no dependency" conclusion, because absence of a flow is
only evidence once you have watched long enough for it to have appeared.

The findings file names workloads and addresses, so it stays with you. `--record` writes the run in counts and
protocol vocabulary instead: the window, whether the search cap was hit, the flow totals, each quarantined
service's fan-in and ports, and the boundaries' sizes and tiers; the script refuses to write one in which a name
or an address survived. `records/` holds that record from the reference estate and what the run printed.

## The offline self-test

Both entries carry one. `python3 discover_flows.py --self-test` runs Phases 4-5 on a twenty-two-flow
synthetic fixture; `python3 discover_arbitration.py --self-test` runs the whole Phase 4-7 pipeline on a
fixture of thirteen flows and five VM records, which classifies seven workloads and covers five cases (the
identity anchor typing an ESXi host, a flow-only shared service, a four-lens high-confidence application, a
data-tier-in-dmz conflict, and a low-information VM). It then folds in the fixture's five confirmations and
checks the hand-off as well. Each compares against a golden report, no vRNI, deterministic. Run them to confirm the analysis before you
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

## The review queue and the hand-off

The arbitration writes nothing on the estate. Its review queue (every conflict, and every workload one lens
or none could place) is worked into a confirmations file, one decision per line:

```text
order-db-01 accept              # a person read the row's conflicts and accepts it as it stands
order-db-01 zone internal       # or sets one axis: app, tier (web, app, data), env or zone
mon-01 app monitoring
```

`--confirmations confirmed.txt` folds the file into every later run, so a resolved row stays resolved; a
value line adds the `confirmed` lens without resolving a conflict, `accept` resolves them, and a line for a
workload the run did not see is named stale, never dropped silently. Keep the file: it is the record of what
a person decided.

`--export-recommendations handoff.json` writes every row that needs no review in the supervisor lens's
recommendations schema, which `../writeback_tags.py --recommendations` reads: one row per axis (`app`, `tier`
as the app-layer value, `env` as the observed environment). A row is marked approve only when a person or the
workload's own label set the value (an app or tier declared or confirmed; an env confirmed); everything
inferred is marked confirm. Review-queue workloads are held, and an endpoint known only by its address is
left out. Give the write-back an approve file and dry-run it first: it holds any change to a value already set.

`--record arbitration.json` writes the run in counts and the framework's vocabulary: the roles, the
confidence spread, how often each lens placed a workload, the review queue by conflict kind, the identity
anchor's typed components, the confirmations and the hand-off's size; it refuses a record in which a workload,
an application id or an address survived. `records/arbitration/` holds the reference estate's record, the two
dry runs of the write-back reading its hand-off, and what each printed.

## The method and the other lens

[`../METHOD.md`](../METHOD.md) is the whole ten-phase method on one page. The narrative teaching, with
the live evidence, is the [Discovery and naming](https://privatecloudarchitect.com/handbook/cartography)
chapter series. The [supervisor lens](../README.md) is the other half of this framework: where a
workload declares its identity as Kubernetes labels, read it rather than infer it, and adopt that lens
first because its source is authoritative.
