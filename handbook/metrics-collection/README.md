# Metrics collection harness

Backs the metrics-collection sheet
([privatecloudarchitect.com/handbook/metrics-collection](https://privatecloudarchitect.com/handbook/metrics-collection)).
The sheet's claims about what VCF Operations collects, keeps, and serves, runnable against your own
instance, read-only:

1. **The three planes** (`collection_planes.py`): the vCenter adapters collect through vStats at a
   sampling rate they own and store one value per 5 minutes; the global settings decide how long
   the 5-minute band, the hourly roll-ups, the real-time store, and the ESX Top set are kept; the
   default policy's allocation model is the ruler that capacity and rightsizing measure against.
   Every retention value prints beside its product default, and a tuned value is flagged.
2. **The roll-up** (`rollup_check.py`): the stored 5-minute value is one number per point, so
   asking for MIN or MAX at that grain returns the same values as AVG; server-side hourly AVG and
   MAX buckets are checked against the native points and pass only when exact to three decimals.
   The VM's peak keys (`20_sec_peak_*`, `peak_*`) are listed: the only within-cycle maxima that
   survive at 5-minute cadence.
3. **The extraction coefficients** (`extract_measure.py`): points, bytes, latency, bytes per point,
   and points per second for one VM over 7 days at native resolution and as hourly buckets, then an
   optional fan-out of N VMs x 4 statkeys over a day. Resources with no data in a window are
   omitted from the response; the script reports them as absence, never as zero.
4. **The identity key** (`identity_keys.py`): the identifiers one VM carries, which of them the
   platform marks as part of uniqueness, and the composite key the sheet recommends,
   `(vcenter_instance_uuid, moid)`.
5. **The real-time path** (`rtm_query.py`): mints the service-scoped JWT the VCF services runtime
   requires, reads which hosts of the vCenter have the 2-second ESX Top set switched on, counts
   the metric names collected for one vCenter, runs one PromQL instant query and
   a `count by (profile)` beside it (one call returns at most 101 series and reports the cut only in a
   warning), then reads the served cadence per acquisition profile as the spacing between value
   changes at a 2-second step: 2 seconds for the ESX Top profile, 20 for the 20-second profiles.
   A range vector is printed last as the contrast, because it returns a 20-second grid for every
   profile and hides the 2-second data.

## Run it

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>    # omit if the broker shares the Ops FQDN
export OPS_API_TOKEN=<your-api-token>        # OPS_REALM defaults to CUSTOMER
export OPS_TLS_VERIFY=false                  # only on a self-signed lab CA

python3 collection_planes.py
python3 rollup_check.py                      # or --vm <name>; default: the busiest VM by CPU MHz
python3 extract_measure.py --vms 50          # --vms is optional; calls run one at a time
python3 identity_keys.py --vm <name>

export RTM_HOST=<your-vcf-instance-services-fqdn>   # fronts /data-query-service
python3 rtm_query.py --source-id <vcenter-instance-uuid>   # VMEntityVCID from identity_keys.py
```

Stdlib Python only. `opslib.py` holds the broker exchange (the api-token flow the handbook's
Part 0 identity chapter teaches); `rtmlib.py` holds the per-service JWT exchange that the
Real-Time Metrics API requires in place of the suite-api bearer (`GET /api/integrations/services`
for the `VCF_VODAP` key, then `POST /api/auth/token/exchange`; the JWT lasted 35 minutes on the
build it was proven on and is minted fresh every run). Nothing here writes.

## Scope, stated plainly

- Everything was proven on one VCF Operations 9.1.0 instance with Real-Time Metrics deployed
  (proven 2026-09-15). Retention and policy values print beside their defaults because the
  sheet's figures are the defaults; if yours are tuned, the sheet's numbers change accordingly.
- The coefficients `extract_measure.py` prints are inputs to your own sizing estimate, not facts
  about the product: bytes per point and latency depend on your node and your network. Run it for a
  day of extraction before sizing streams.
- `rollup_check.py` needs a VM with three hours of data; a fresh instance or an idle VM reports a
  short window rather than a verdict.
- `rtm_query.py` needs Real-Time Metrics deployed on the VCF instance that fronts `RTM_HOST`, and a
  `--source-id` that is the vCenter instance UUID. Any other value returns a successful empty
  answer, because the service does not validate the source.

## Reading the output

- `collection_planes.py` exits 0 when every retention key sits at its default, 1 when one is tuned.
- `rollup_check.py` exits 0 when every full hourly bucket matches the native points exactly.
- `rtm_query.py` exits 1 when the source returns no series; check the UUID before anything else.
  When the instant query returns fewer series than the count, the call was cut at the service's
  ceiling: read that metric one host at a time in a pipeline, never from one call.

## Expected output

See [`expected-output.md`](expected-output.md) for the transcript shape of each script.

## The atlas and the dashboard

- `collection-planes-atlas.html` is the published Collection Planes Atlas, twelve plates that draw the planes,
  the horizons, the catalog with vCenter statistics levels, the extraction contract, the regional shape, the
  domains beyond vSphere, the identity key, the real-time plane's rules, and the proof that the store's mean
  and peak keys are rollups of the 20-second samples. Open it in a browser; it is the same page as the
  published artifact linked from the chapter.
- `../../frameworks/collect-once/` is the PCA - Collection Strategy Guide: an importable VCF Operations
  dashboard (six live VM lists, the catalog mapped to Operations keys, the hidden-peak charts, three PromQL
  Viewers, the extraction contract with the calls behind it), its generators, the reference lists every key
  is checked against, and `promql/`, the verified PromQL reference with `verify_promql.py`, which re-runs the
  functions and the ten strategy queries against your own instance.
