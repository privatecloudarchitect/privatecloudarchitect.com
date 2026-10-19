# Failure record

One entry per failure, appended when the failure is understood, never edited away. Copy the entry below, number it,
and fill every field. `triage.py --corpus failure-record.md --entry '^### (F-\d+):'` audits a file of these entries
and prints how many carry each field; a field nobody fills is the step your practice skips.

The layer is one of five words, the same five every time, so the audit can count them:

| layer | the cause sits in |
|---|---|
| information contract | a component lacked the data it needed to produce the right output |
| processing logic | a component had the data and handled it wrong |
| structural design | the design produces the failure by construction |
| platform configuration | a manifest, policy, probe, role or alert definition |
| infrastructure | the network, storage, compute or the hypervisor underneath |

---

### F-001: <one line: what failed, where>

**Symptom:** what was observed, in one sentence, before any cause: the alert, the status, the error text, the time.

**Root cause (information contract):** the cause, named, with the layer in the brackets chosen from the table above.

**Fix:** what changed, at the layer the cause sits in, and how the change was confirmed on a re-run.

**Evidence:** the read that showed it: the API call and the status it answered, the log search and the line it
found, the record file. Name where it can be found again.

Related: F-000, the earlier entry this one depends on or corrects, if any.
