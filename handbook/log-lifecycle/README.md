# Log lifecycle: what your store keeps, sends, hides and drops, read and proven

The chapter ([privatecloudarchitect.com/handbook/log-lifecycle](https://privatecloudarchitect.com/handbook/log-lifecycle))
teaches how to decide, per class of log, what VCF Operations Log Management does with an event after it arrives: which
partition keeps it and for how long, whether an archive outlives that, which forwarder sends a copy to a SIEM, which mask
keeps a secret out of the store, and which filter drops what nobody reads. This folder holds one tool for reading your
store and proving each kind of rule before you trust it.

Proven on VCF 9.1.1 (Log Management 9.1.1.0, small size, one node) on 2026-10-15, with the exact file in this folder.

## What is here

| File | What it does | Writes |
|---|---|---|
| `lifecycle.py census` | Every partition with its order, filter, retention, archive, event count and oldest timestamp; how far back a search reaches, from the events held per day; the external storage; every forwarder, mask and filter; events a day and by application. Then the checks the chapter teaches, each marked BAD, WARN or INFO | nothing |
| `lifecycle.py plan` | The shard arithmetic of the 9.1 design page for a size, a replica count, a number of partitions and the retentions you name | nothing |
| `lifecycle.py trial filter\|mask\|partition` | A throwaway rule whose condition is an application name made for the run, labelled lines to a syslog listener you name, the store read back, then the rule deleted and read back absent | the rule and the lines (with `--send`) |
| `lifecycle.py trial forwarder` | Log Management's connection test against a destination you name | nothing |
| `records/` | The runs on the reference estate the chapter renders, every estate value replaced by a placeholder | |

## Run it

Standard library Python 3. The sign-in, the Log Management token and the search are the `log-alerts` folder's
`lmlib.py`, which takes the Operations sign-in from `metrics-collection/harness/` and the scrubber from
`log-collection/`; the tool finds them in the folders beside this one, so run it from this folder of a full clone.

```
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/ops-api-token )   # paste your api-token, then Ctrl-D
export OPS_HOST=<operations fqdn>  OPS_API_TOKEN_FILE=~/.vcf/ops-api-token  OPS_TLS_VERIFY=false   # optional OPS_BROKER_HOST, OPS_REALM

# what the store keeps, sends, masks and drops, and how far back it reaches
python3 lifecycle.py census --size medium

# the shard budget for the partitions you intend
python3 lifecycle.py plan --size medium --replicas 3 --partitions 5 --retention audit=365 --retention security=180 --retention ops=30

# prove a rule before you trust it (without --send each prints its plan and changes nothing)
python3 lifecycle.py trial mask      --target ssl://<a syslog listener>:<port> --selector 'password=(\S+)' --sample 'password={hex}' --send
python3 lifecycle.py trial filter    --target ssl://<a syslog listener>:<port> --send
python3 lifecycle.py trial partition --target ssl://<a syslog listener>:<port> --retention-days 1 --send
python3 lifecycle.py trial forwarder --host <your SIEM> --port 6514 --protocol RAW --tls
```

The api-token is read from `OPS_API_TOKEN_FILE`, a file of mode 0600, when it is set; a wider mode is refused.
The value itself in `OPS_API_TOKEN` still works, but it lands in the shell's history and the process list, so
keep it for a throwaway credential.

The listener is any syslog-over-TLS listener whose events reach this Log Management, such as a unified cloud proxy's
(the `log-collection` folder's `log_paths.py` names each host's). `--out ./records` writes a scrubbed record of any
command. A mask trial's `--sample` must contain `{hex}`, which the tool replaces with a fresh random value on each line,
so the value the mask should hide is never a real one.

Exit codes: 0 done; 1 a census with a BAD finding, a trial whose rule did not do what the chapter says, or a
forwarder destination whose test did not answer 200; 2 a usage or sign-in error.

## What each command settles, and how to read it

- **How far back a search reaches.** `census` counts the events the store holds per day and prints the depth: the
  run of whole days near the store's usual volume, ending yesterday. That count, not the retention setting and not a
  partition's oldest event, is how far back a search reaches today. A partition's oldest event is only the oldest
  timestamp it holds, and a source that sends old lines late moves it back by days without bringing any history; on
  the reference store, VCF Operations lines stamped up to nine days earlier did exactly that. A retention is a ceiling
  the shard budget and the disk both have to allow, and the store removes its oldest events once its disk reaches its
  threshold whatever the retention says, so a partition whose retention is longer than the days the store holds is
  marked WARN.
- **The shard budget.** With `--size`, `census` and `plan` apply the design page's rule: a day of retention costs one
  shard per partition on each replica, against 700, 800 or 900 shards per replica for small, medium and large. The
  page's example, a medium store with eight partitions, holds at most 100 days. That partitions with different
  retentions share the budget by their sum is the tool's arithmetic on that rule, and more replicas add disk, not shard
  days.
- **A mask before the secret.** `trial mask` sends one line before the mask exists and the rest after. A mask changes
  only what is ingested once it is active: the earlier line keeps its value and is still found by a search, and every
  line after the first few seconds is stored with the mask value, so a search for the original value finds nothing.
  Prove your own `--selector` this way before the source starts writing the value.
- **A filter drops, and wins.** `trial filter` shows a filtered line is never stored, beside control lines from an application no rule names, which must arrive. The 9.1 page says a filtered
  event is never forwarded either, so `census` warns whenever filters and forwarders both exist.
- **A partition is in force at once, and takes its events with it.** `trial partition` shows the first line landing in
  the new partition within seconds, a search with no partition named finding it, and, after the partition is deleted,
  none of its lines found. Archive a partition's events, or let its retention run out, before you remove it.
- **A destination before a forwarder.** `trial forwarder` answers 200 for a destination that accepts the connection
  and whose certificate is trusted; 400 `Connect timed out` for one that does not answer; and 502 `certificate not
  trusted` for a TLS destination whose issuer Log Management does not trust (the answer carries the certificate it was
  shown, which the record keeps only by its length).

## What a trial changes, and what it leaves

A trial creates one rule named `pca-trial-<nonce>-<kind>` whose condition is `appname` equal to `pcatrial<nonce><kind>`,
an application no source writes, so no other event can match it. It refuses to start while a rule from an earlier trial
is present, deletes its rule in a `finally` block, and reads it back absent. The labelled lines (`pcatrial<nonce>`,
"labelled test line, safe to ignore", hostname `pcatrial-<nonce>.invalid`) stay in the store until its retention or
its disk removes them; a partition trial's lines go with the partition. `trial forwarder` creates nothing.

Not covered: archiving (it needs external storage, and adding or changing storage restarts Log Management), forwarded
delivery (it needs a receiver you control; the connection test is the part this tool proves), and whether a forwarded
copy carries a mask, which the 9.1 pages do not state: prove it at your receiver.
