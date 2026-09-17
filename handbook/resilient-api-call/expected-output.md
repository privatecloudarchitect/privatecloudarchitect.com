# Expected output

One run of `demo.py` on a VCF Operations 9.1.0 instance and its VCF Automation, 2026-09-16, host names replaced.
The cache file was warm from an earlier run, which is why step 1 needed no mint: a valid cached bearer is used as
is, and the count rises only when the client has to mint.

```text
1. one read, parsed at the boundary
   first resource: kind pgdatabase-resource; the envelope declares 3292 resources in all; mints so far: 0

2. the bearer expires mid-run (simulated by corrupting the cached one)
   the call answered 401 once, the client re-minted once and retried: HTTP 200, mints so far: 1 (one more than before)

3. a whole collection, the declared total honored
   112 virtual machines collected in pages of 100; equals the declared total

4. the answer that lies: a page that is capped while the total is declared
   asked for 512 per page: 128 values returned, resultTotal 175, HTTP 200 and no error: a membership check on this page alone would be wrong
   the answer carried 141 response headers (129 named link); the standard library refuses more than 100 unless told otherwise
   walked at 128 per page: 175 rights collected, equal to the declared total

5. the boundary refusing a drifted shape
   wrapper key moved: no list under any of ['resourceList']; the answer's keys are ['pageInfo', 'resources']
   field missing:     resource: missing field 'resourceKey'; present: ['identifier']

6. an idempotent ensure(), dry run: nothing is sent
   not found; would send POST /api/resources/groups with a 171-byte body; a second run finds it and sends nothing

done: mints 1; every step ran

stderr:
warning: TLS verification is OFF (TLS_VERIFY=false); acceptable for a self-signed lab CA, never for production

exit 0
```

What to read in it: step 2 is the first guarantee measured (one 401, one re-mint, one retry, the mint count up by
exactly one); step 3 and step 4 are the collection read the way the envelope demands, with step 4 showing the
answer that lies (a capped page with the true total declared, and an answer with more response headers than the
standard library accepts by default); step 5 is the boundary refusing drift with the field named; step 6 is the
mutation that is safe to run twice, in a dry run that sends nothing.
