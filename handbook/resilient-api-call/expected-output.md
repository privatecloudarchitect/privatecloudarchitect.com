# Expected output

## demo.py, 2026-10-07

One run of `demo.py --write` on a VCF Operations 9.1.1 instance and its VCF Automation 9.1, 2026-10-07 18:19 UTC,
host names replaced. No cache file was set, so step 1 minted the first bearer and step 2's re-mint is the second.
Steps 1 to 7 wrote nothing; step 8 created one throwaway custom group, whose only rule matches no machine, and
deleted it before the run ended, fifteen seconds after it began. A separate read afterwards found no group and no
resource by its name, and the estate's 62 custom groups as before.

Step 4 ran on a session bearer handed to the client in place of the refresh-token mint, because the organization's
stored refresh token was refused at the token endpoint that day (the vcfa-api chapter's `runway.py` reads exactly
that). The client's path from the bearer onward is the same either way.

```text

1. one read, parsed at the boundary
   first resource: kind pgdatabase-resource; the envelope declares 4706 resources in all; mints so far: 1

2. the bearer expires mid-run (simulated by corrupting the cached one)
   the call answered 401 once, the client re-minted once and retried: HTTP 200, mints so far: 2 (one more than before)

3. a whole collection, the declared total honored
   139 virtual machines collected in pages of 100; equals the declared total

4. the answer that lies: a page that is capped while the total is declared
   asked for 512 per page: 128 values returned, resultTotal 182, HTTP 200 and no error: a membership check on this page alone would be wrong
   the answer carried 141 response headers (129 named link); the standard library refuses more than 100 unless told otherwise
   walked at 128 per page: 182 rights collected, equal to the declared total

5. the boundary refusing a drifted shape
   wrapper key moved: no list under any of ['resourceList']; the answer's keys are ['pageInfo', 'resources']
   field missing:     resource: missing field 'resourceKey'; present: ['identifier']

6. an idempotent ensure(), dry run: nothing is sent
   not found; would send POST /api/resources/groups with a 564-byte body; a second run finds it and sends nothing

7. the effect, read back by the stable key
   an object that exists: a re-read by its identifier finds it, in the state expected
   the group step 6 did not send: the demo group: the write was answered, and a re-read by its key finds nothing
   a write answered as a success that applied nothing reads exactly like this, and this is where it is caught

8. the write itself: sent once, confirmed, run twice, and deleted
   created: one POST sent; a re-read by name found it in the state sent (Environment type, one rule that matches no machine, auto-resolve on); the list went from 62 groups to 63
   a second re-read, by the identifier the first one found, agrees
   a second ensure(): unchanged; writes sent across both runs: 1
   an expectation the stored group does not meet (auto-resolve off): the throwaway group: a re-read by its key finds it, not in the desired state
   deleted; a re-read by its identifier answers 404, and the list, back to 62 groups, has none by its name

done: mints 2; every step ran

stderr:
warning: TLS verification is OFF (TLS_VERIFY=false); acceptable for a self-signed lab CA, never for production

exit 0
```

What to read in it: step 2 is the first guarantee measured (one 401, one re-mint, one retry, the mint count up by
exactly one); steps 3 and 4 are the collection read the way the envelope demands, with step 4 showing the answer
that lies (a capped page with the true total declared, and an answer with more response headers than the standard
library accepts by default); step 5 is the boundary refusing drift with the field named; step 6 is the mutation
that is safe to run twice, in a dry run that sends nothing; step 7 is the effect read back by its key, passing on an
object that exists and refusing the one step 6 never sent, which is what a write that applied nothing looks like;
step 8 is the write itself: sent once, found by a re-read in the state it was sent in, a second run that sends
nothing, an expectation the stored object does not meet refused by name, and the delete read back as gone.

A dry run proves the request a program would send, never that the platform accepts it. Step 6's request as first
written named `Custom Group` as the group type, which none of the estate's eighteen types is, and carried no member
criteria; its dry run printed it without complaint on every run. With the type corrected, the platform refused it
the first time step 8 sent it (HTTP 400, "Define member criteria or objects to include"). Send a write once, on a
throwaway, before you trust its dry run.

Your totals will differ; the shape of each step should not. Without `--write`, step 8 prints that it was skipped and
nothing is written.
