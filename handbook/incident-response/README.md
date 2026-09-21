# Two measurements an incident practice needs about itself

Companion to the chapter
([privatecloudarchitect.com/handbook/incident-response](https://privatecloudarchitect.com/handbook/incident-response)):
one read-only script that answers the two questions a response method cannot answer about itself. Stdlib
Python only; no token is printed or written.

| File | What it is |
|---|---|
| `triage.py` | Profiles every alert instance on the platform by age, impact, concentration and control state, and audits whatever failure record you keep for what each entry retained of the method. Writes `triage.json`. |
| `triage.json` | That record from the reference estate, 2026-09-19. The chapter's plates render it. |
| `opslib.py` | The broker exchange and request helper, shared with the other Part IV harnesses. |

## Run it

```bash
export OPS_HOST=<operations-fqdn>
export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
export OPS_REALM=CUSTOMER
export OPS_API_TOKEN=<api-token>                # minted in the operations console
export OPS_OWNER="PCA"                          # the owner prefix your content carries
export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA

python3 triage.py
python3 triage.py --corpus /path/to/your/failure-record.md
python3 triage.py --corpus record.md --entry '^### (F-\d+):'    # your own heading shape
```

## Question one: is the queue made of incidents?

A response method assumes the thing in front of you started recently. That is a claim about the queue, not
about the method, and it is one read.

The script reports how many alerts are standing, their median and maximum age, how many started in the last
week, how many have stood over a month, and how many have ever been acknowledged or suspended. It also reports
the median lifetime of the closed ones, which is what an event actually looks like on your estate.

On the reference estate: 259 standing, median age 67 days, 2 started in the last week, and **none of them ever
touched**. The closed ones lived 1.17 hours at the median. Those are two different populations and only the
second is incidents.

It then splits the standing alerts by impact badge, because the badge predicts the treatment: health alerts
stood 12 days at the median here and risk alerts 67. That five-fold difference is the correct handling of a
warning about the future, and it means the badge is a usable first routing dimension. Severity is not:
criticality is spread across the whole queue.

Finally it counts how few definitions produce the queue. Here 47 definitions produced all 259 standing alerts
and the six commonest produced 116 of them, which is a routing table's first six rows for the price of a
ranking.

## Question two: what did the method leave in the record?

A scar corpus is the output of an incident practice, so the corpus is where the practice can be audited. Point
the script at a markdown file of recorded failures and it reports, per entry, whether it:

- states the symptom, before any cause
- names the root cause
- **classifies that cause to a layer** (usually the weak step)
- states a fix or a discipline
- cites where the finding came from
- cross-links another entry
- claims verification in its heading
- corrects an earlier reading

The heading pattern and the labels are arguments, so this audits **your** record rather than any particular
one. It reports a funnel, not a score: the shape tells you which step of your method has become ceremonial.

Two ratios come out of the same pass and neither is a target:

- **Entries that correct an earlier reading** are diagnoses paid for twice. One in six here.
- **Entries quoting an HTTP status against entries mentioning a log** is which evidence plane your practice
  actually runs on. Four to one here, in favour of the API reads.


**Running it again without `--corpus` does not erase what the flag captured.** A run that audited no corpus has
nothing to say about that section of the record, which is not the same as having found it empty. So when the
record on disk holds a block this run did not produce, the block is carried forward and the script prints
that it carried it. Writing the section as empty instead would publish a narrower record as though it were a
newer one.

## Scope, stated plainly

- Read-only. The alert half issues `GET`s; the record half reads a file.
- The corpus audit is regular expressions over labels. It measures whether a trace was kept, never whether the
  diagnosis was good, and an entry can keep every trace and still be wrong.
- The layer distribution counts only entries that qualify the cause at all, and reports separately how many
  use wording outside the taxonomy rather than folding them in.
- **No alert, object or machine is named in the record.** The queue is published as counts and ages: which of
  an estate's machines is currently unhappy is that estate's business.

## Reading the record

`queue` carries the instance counts, `ageDays` for the standing alerts, `closedDurationHours` for what closed,
`byImpact` with the median age per badge, `byLevel`, the definition and object counts with the top-six share,
and the control states. `corpus` carries the entry count, `carrying` with one number per trace, and
`layerTags` with `layerTagged` so the denominator is visible.
