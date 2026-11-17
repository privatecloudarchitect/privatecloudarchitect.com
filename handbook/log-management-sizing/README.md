# How large should Log Management be, and what will the platform build under it?

Companion to field note 21
([privatecloudarchitect.com/notes/log-management-sizing](https://privatecloudarchitect.com/notes/log-management-sizing)):
the arithmetic the note's planner runs, as a script you can run on your own numbers, and a read-only script that shows
how Log Management is laid out on a cluster you already run. Standard library Python and POSIX shell; neither script
takes a password or token, and neither writes anything.

| File | What it is |
|---|---|
| `sizing.py` | The rule. You describe an estate (sites with the volume per day their platform components and their guests send, and any application large enough to size separately); it answers with the Log Management size and replica count, what sets that count, the worker nodes the VCF management services cluster grows to, the node addresses in use and to budget, and the VIPs with each gateway's load. It reads nothing from any system. |
| `layout.sh` | Read-only (`kubectl get`): node counts and sizes, what the log store and log processor pods request, whether a replica's pods share a worker, whether any pod autoscaler in the cluster targets the log store or the log processor, what a gateway pod requests, and the node address pools. A read that fails prints "could not read" on its line. It prints counts and sizes only: no node name, pod suffix or address. |
| `layout-reading.txt` | Example output: what `layout.sh` printed on one run, 2026-11-16, VCF 9.1.1. Yours prints the same lines for your cluster. |
| `expected-output.md` | The printed lines of both scripts. |

## Size an estate

```bash
python3 sizing.py --example                 # an example, made up: no estate has these numbers
python3 sizing.py --template > estate.json  # a file to fill in with yours
python3 sizing.py estate.json
python3 sizing.py estate.json --days 14 --head 2 --bytes 600
```

Sites carry GB per day (`infra` for the platform's own components, `guest` for guest agents) and the fleet they belong
to; the first site listed in a fleet hosts that fleet's Log Management. Applications carry TB per day (`avg`, `peak`)
and the position of their site in the list. The exit code is 1 when a fleet needs more than 19 replicas.

| Setting | Default | What it is |
|---|---|---|
| `--days` | 30 | days kept searchable in the store; older periods belong in an archive |
| `--head` | 1 | replicas of failure headroom (the design library says N+1 or N+2) |
| `--bytes` | 347 | bytes per event. Derived: Configuration Maximums 9.1.0 lists each size's volume per day beside its events per second, and each pair divides to 347 when a GB is a billion bytes (the page does not define it). Measure yours |
| `--ratio` | 1.0 | stored bytes per ingested byte; a placeholder, not on the pages read, so measure it on a running instance |
| `--partitions` | 4 | partitions, the two built in included; a replica's shards divided by this caps the days searchable |
| `--growth` | 20 | percent added to infrastructure and guest volume; a placeholder |
| `--fleetCpu` | 60 | vCPU the fleet's other services request on the same worker nodes; a placeholder, read yours from the cluster |

### Which part is the product's rule, and which is arithmetic

- **Rule**, from the VCF 9.1 design library and product pages: the event rate, resources and gateway of each replica
  size; 19 replicas at most; 9 TB of store per replica; the worker node size each Log Management size causes; two
  worker nodes for a Large replica; the node address rule (12 for the runtime, 6 for the installation, 1 for each
  Small or Medium replica and 2 for each Large one).
- **Arithmetic**, this script's: events per second from volume per day at the event size you state; the worker count
  (requests against worker capacity with five percent left unrequested, and at least two workers for each Large
  replica); VIPs for agents and for each application, as many as their peak needs gateways; storage counted with
  every replica grown to 9 TB and filled to 80%, the level past which an archive import fails; the size chosen at the
  lower end of the ranges the design library gives (five Small replicas, six Medium).
- **Not modelled:** connections per VIP, and the simple model's single replica. With nothing measured, the design
  library's estimate is 250 events per second for each ESX host.

The platform decides the real worker count, so treat that line as an estimate. On the one cluster `layout.sh` ran on,
the worker nodes were larger than the fleet sizing page gives for its Log Management size, and nothing read explains
it.

## Read a cluster's layout

On a control plane node of the VCF services runtime, as root (the vendor's page is "Establish an SSH Connection to a VCF Services Runtime Instance"; search for it by that name):

```bash
export KUBECONFIG=/etc/kubernetes/admin.conf
sh layout.sh
```

It runs `kubectl get` and nothing else. The lines it prints are the ones in `layout-reading.txt`.

## What was and was not tested

`sizing.py` is held equal to the planner on the note's page by a test in the site's repository: size, replica counts
and what sets them, workers, addresses, the shard budget and the VIP names, for every example estate at four settings.
The page's proxy cards and pod placement have no counterpart here. `layout.sh` ran on one cluster with one Small
replica and one VIP, which is the simple model, on a fleet whose Log Management reported version 9.1.1. The pod sizes
at Medium and Large in the note are the Small pods' ratio applied to the documented replica sizes; they were not read
on a running build.
