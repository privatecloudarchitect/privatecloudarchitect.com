# Metrics collection: the guide first, then the proof

The chapter ([privatecloudarchitect.com/handbook/metrics-collection](https://privatecloudarchitect.com/handbook/metrics-collection))
makes one claim in three planes: the hypervisor half of any VM utilization list is already collected once by
VCF Operations, kept at a cadence you can name, and served through APIs you can size. This folder is the
hands-on side of that claim, in the order a first visit should take it.

| Step | Where | What you do | Time |
|---|---|---|---|
| 1 | [`import/`](import/) | Import two files into your VCF Operations and bind three widgets. You now have the **PCA - Collection Strategy Guide** running on your own VMs. | about ten minutes |
| 2 | the dashboard | Read it top to bottom. The order of its widgets is the lesson; the list below says what each one teaches. | an hour, once |
| 3 | [`harness/`](harness/) | Run the read-only scripts that reproduce the chapter's measurements against your instance: the planes and their retention, the roll-up check, the extraction coefficients, the identity key, the real-time path. | an afternoon |
| 4 | [`collection-planes-atlas.html`](collection-planes-atlas.html) | The twelve plates the chapter draws, as one page you can open in a browser or hand to someone. | as needed |

## 1. Import the guide

[`import/README.md`](import/README.md) is the whole procedure: the prerequisites, the two files in the order
they must go in (views, then the dashboard that binds them), the one instance-specific step (pointing the
three PromQL Viewers at your VCF domain), what to adjust if you want to, and what each symptom means if a
widget stays empty. Nothing in it writes through the API; both imports take the product's own Manage >
Import screens.

## 2. Read the guide in order

The dashboard is one tab of twenty-four widgets, laid out top to bottom as a course. Read them in this order:

1. **Start here: collect once, decide at source.** The claim, the three planes, and how to use the rest of the tab.
2. **The VM utilization catalog, mapped to Operations.** Every counter a BI or platform team asks for, beside the
   Operations key that already holds it, the vCenter counter behind it with its statistics level, the guest-OS
   family Tools reports, and the decision keys only Operations carries.
3. **Configuration and state**, with a live list of your VMs beside it. Each of the six families is a pair: the
   text explains the keys, the list shows your own estate under exactly those keys.
4. **CPU: demand, ready, co-stop**, with its live list.
5. **Memory: active, consumed, the reclamation ladder**, with its live list.
6. **Virtual disk and network**, with two live lists.
7. **Storage and guest filesystem**, with its live list.
8. **The mean and its hidden peak.** Click a VM in the CPU or memory list: the two charts draw the 5-minute mean
   beside the in-cycle peak the mean hides, which is the chapter's central measurement made visible.
9. **Real-Time Metrics: read a name, pin the feature**, with three PromQL Viewers charting queries written for the
   strategy: the bounded contention hot list, the vCPU-to-core ratio computed live from two families, and the
   2-second latency tail.
10. **PromQL for the strategy.** Ten queries, the functions the engine serves, and the dialect's rules, every one
    executed against a live instance when the guide was built.
11. **What should not come from Operations, and when.**
12. **Extract it: three tiers, one key, the rules, and the PromQL calls.** The contract for feeding a warehouse.
13. **Reference: every column, statkey, unit, cadence.** The lookup table, last on purpose.

## 3. Prove it on your instance

[`harness/README.md`](harness/README.md) runs five stdlib-Python scripts, read-only, against your own
instance: the planes and their retention beside the product defaults, the roll-up exactness check, the
extraction coefficients, the identity key, and the real-time path. Each prints beside an expected transcript.

## 4. The atlas

`collection-planes-atlas.html` is the Collection Planes Atlas: twelve plates that draw the planes, the
horizons, the catalog with vCenter statistics levels, the extraction contract, the regional shape, the
domains beyond vSphere, the identity key, the real-time plane's rules, and the proof that the store's mean
and peak keys are roll-ups of the 20-second samples. It is the same page as the artifact linked from the
chapter.

## Where the guide comes from

[`../../frameworks/collect-once/`](../../frameworks/collect-once/) holds the guide's sources and generators
(the six view definitions, the thirteen teaching widgets, the dashboard builder), the reference lists every
key is checked against, and `promql/`, the verified PromQL reference with the script that re-runs it against
your instance. The two files in `import/` here are byte copies of the bundles those generators emit; rebuild
there when you change something, and the copies here follow.
