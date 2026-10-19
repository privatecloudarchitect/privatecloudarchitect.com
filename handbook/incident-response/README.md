# What is in the alert queue, and what your failure record kept

Companion to the chapter
([privatecloudarchitect.com/handbook/incident-response](https://privatecloudarchitect.com/handbook/incident-response)):
one read-only script that answers the questions a response method cannot answer about itself. Stdlib Python 3 only; no
token is printed or written.

| File | What it is |
|---|---|
| `triage.py` | Reads every alert instance and profiles the open ones by age, impact badge, concentration and control state; ranks the definitions that fill the queue; audits whatever failure record you keep. Writes `triage.json`. |
| `failure-record.template.md` | A record entry carrying every field the audit counts: symptom, root cause with its layer from a fixed list of five, fix, evidence, a cross-link. |
| `triage.json` | The run on the reference estate, 2026-10-19, VCF Operations 9.1.1.0 (build 25679751). The chapter renders it. |
| `expected-output.md` | The transcripts behind that record. |
| `opslib.py` | The broker exchange and request helper, shared with the other Part IV harnesses. |

## Run it

```bash
export OPS_HOST=<operations-fqdn>
export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/ops-api-token )   # paste your api-token, then Ctrl-D
export OPS_API_TOKEN_FILE=~/.vcf/ops-api-token   # mode 0600; minted in the operations console
export OPS_OWNER="PCA"                          # the owner prefix your own alert definitions carry
export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA

python3 triage.py --standing      # the thirty-second read: what has been open longest, oldest first
python3 triage.py --rank          # the definitions that fill the queue, commonest first
python3 triage.py                 # the queue profile; writes triage.json
python3 triage.py --corpus /path/to/your/failure-record.md
python3 triage.py --corpus record.md --entry '^### (F-\d+):'    # your own heading shape
```

The api-token is read from `OPS_API_TOKEN_FILE`, a file of mode 0600; a wider mode is refused. The value itself in
`OPS_API_TOKEN` still works, but it lands in the shell's history and the process list, so keep it for a throwaway
credential. The identity behind it needs read access to alerts.

Every mode reads the whole alert list, page by page, to its declared total. The list answers newest first, so a single
page holds the newest alerts and none of the oldest, which are the ones the standing read exists to find. A refused or
short read stops the run with exit 4.

## Question one: is the queue made of incidents?

A response method assumes the thing in front of you started recently. That is a claim about the queue, not about the
method, and it is one read. An alert counts as open while its status is anything but `CANCELED`.

`--standing` prints the open alerts oldest first, with each one's control state, impact badge and criticality, and how
many are `OPEN`: nobody has assigned, suspended or suppressed them. The profile adds the median and oldest age, how many
started in the last week and how many have stood over a month, and the median lifetime of the closed ones, which is
what an event looks like on your estate. Open alerts many times older than that are conditions, not incidents.

It then splits the open alerts by impact badge, because the badge predicts the treatment: a risk alert is a warning
about the future, and it belongs to planning, not to the response queue. Severity is not a routing dimension in the same
way; criticality is spread across the queue.

## Question two: which definitions fill it?

`--rank` counts the open alerts by the definition that raised them, commonest first, with each one's impact badge, how
many objects it sits on, and its median age. A handful of definitions usually produce most of the queue, and each of
the top rows is a routing-table row to write: the symptom, the owner who gets it, and the first read. The record keeps
product definition names; a definition carrying your `OPS_OWNER` prefix is recorded by the prefix only.

## Question three: what did the method leave in the record?

A record of failures is the output of an incident practice, so it is where the practice can be audited. Point
`--corpus` at a markdown file of entries and it reports how many:

- state the symptom, before any cause
- name the root cause
- **classify that cause to a layer** (usually the weak step)
- state a fix
- cite where the finding came from
- cross-link another entry

plus how many correct an earlier reading, quote an HTTP status, or mention a log. The heading pattern is an argument
and the fields are patterns over the entry, so this audits your record rather than any particular one, and it counts
only the labels it is given: an entry that writes its fix under another word reads as missing one. It reports a
funnel, not a score; the step that falls away is the one your practice has stopped doing.

`failure-record.template.md` is an entry the audit reads as written. Its layer is one of five words (information
contract, processing logic, structural design, platform configuration, infrastructure), the same five every time, so
the audit can count them and "other wording" falls toward zero.

**Running it again without `--corpus` does not erase what the flag captured.** A run that audited no record has nothing
to say about that section of `triage.json`, which is not the same as having found it empty, so the run carries the
earlier audit forward and prints that it did.

## The record

`triage.json` carries counts, ages and product definition names. It names no object and no host: which of an
estate's machines is unhappy is that estate's business.
