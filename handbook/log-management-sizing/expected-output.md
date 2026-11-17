# Expected output

What the two scripts print. Compare the shape with yours, never the numbers: the estate is an example, made up, and the layout read is one cluster on one day.

## `python sizing.py --example`

```
an example, made up
fleet 1, Log Management at Site A
  size and replicas     Small x 3  (3 for ingestion, 3 for storage; the minimum sets the count)
  volume                558 GB/day average, 558 GB/day at peak: 18,612 events/s against 60,000
  store                 27 TB with every replica grown to 9 TB (each deploys with about 0.5 TB); about 39 days searchable at 80% full
  worker nodes          about 7 at 16 vCPU / 32 GB, plus 3 control plane nodes (an estimate: the platform decides)
  node addresses        10 in use, 21 to budget, recommended pool 30
  VIPs                  default, agents (7K events/s at peak), external
```

## `sh layout.sh`, on a control plane node of a VCF services runtime

```
read at 2026-11-16T21:46:47Z
log store image tag: 3.6.0-fips-1.0
nodes: 3 control plane, 4 workers
node size: 3 x control plane, 4 vCPU 10 GiB
node size: 4 x worker, 24 vCPU 47 GiB
workers carrying a taint: 0
log-store: 1 ready, 1 container(s), requests cpu 5 memory 10Gi
log-processor: 1 ready, 2 container(s), requests cpu 3 100m memory 6Gi 128Mi
replica pods on distinct workers: 2 of 2 pods
pod autoscalers targeting the log store or log processor: 0 (of 6 in the cluster)
gateway pods: 1, requests cpu 4,5m memory 2Gi,32Mi
node address pools: 1, 30 addresses, 7 in use, 23 free
cluster autoscaler deployments: 1
```
