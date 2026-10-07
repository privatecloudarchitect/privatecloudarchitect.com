# The resilient API call, as code

Step three of the chapter
([privatecloudarchitect.com/handbook/resilient-api-call](https://privatecloudarchitect.com/handbook/resilient-api-call)):
the three guarantees as a client you can read in one sitting, and a demo that exercises each one against your own
estate, read-only unless you ask it to write. Stdlib Python only; no token value is ever printed.

| File | What it is |
|---|---|
| `resilient.py` | The client. A bearer minted through a callable you supply, cached with its expiry and refreshed on a UTC buffer, re-minted exactly once when a call answers 401; `unwrap()` and `require()` as the typed boundary, naming the key or field that drifted; `paginate()` reading a whole collection and refusing to stop short of the total the envelope declares; `ensure()` as find-by-key, update-if-changed, create-if-absent, with a dry run that returns the request instead of sending it; `confirm()` re-reading an object by its stable key after a write, which `ensure()` calls on every write it sends, so a write answered as a success that applied nothing raises `EffectError` instead of returning `created`; `confirm_gone()` reading back that a deleted object is gone. TLS verification is configuration, warned about on stderr whenever it is off. |
| `test_resilient.py` | The write guarantees checked offline with stubbed reads and writes, nine cases: a dry run sends nothing, a write that applies is confirmed, a second run sends nothing, a write answered that applied nothing and an update that left the object wrong are both refused, and a delete is confirmed gone or refused when the object is still there. No network. |
| `demo.py` | Seven read-only steps and one write you ask for: one read through the boundary; the bearer corrupted and recovered with one re-mint; a whole collection read against its declared total; the answer that lies (a capped page declaring the true total, and an answer with more headers than the standard library accepts by default); the boundary refusing two drifted shapes by name; an idempotent ensure in dry-run mode; the effect read back by its key, on an object that exists and on the one the dry run never sent; and, with `--write`, that request sent once, confirmed by a re-read, sent nothing on a second run, and deleted and read back as gone. Exit 0 when every step ran. |

## Run it

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>          # omit if the broker shares the Ops FQDN
export OPS_API_TOKEN=<your-api-token>              # OPS_REALM defaults to CUSTOMER
export TLS_VERIFY=false                            # only on a self-signed lab CA; the client warns every run
export CACHE_FILE=/path/to/cache.json              # optional; written atomically, owner-only

# optional, for step 4 (the capped page): the consumption surface's tenant refresh-token grant
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600; rewritten only if the answer carries a different value

python3 demo.py                # steps 1 to 7, read-only
python3 demo.py --write        # adds step 8: one throwaway custom group, created, confirmed and deleted
python3 test_resilient.py      # offline: the write guarantees, no estate needed
```

## Scope, stated plainly

- Run on one VCF Operations 9.1.1 instance and its VCF Automation on 2026-10-07, with `--write` (first on 9.1.0,
  2026-09-16 and 2026-09-21, read-only); every number in `expected-output.md` is from the 2026-10-07 run. Your totals will differ; the shape
  of each step should not.
- Read-only unless you pass `--write`. Steps 1 to 7 send no mutation: step 6 runs `ensure()` in dry-run mode and
  prints the request it would have sent, and step 7 shows `confirm()` on reads alone. Step 8, only with `--write`,
  sends that request: it refuses to start if a custom group named `PCA - Resilient call demo - throwaway` already
  exists, creates one whose only membership rule matches a machine name nobody uses, and deletes the group it
  created even when a check in between fails. It needs a credential that may create and delete custom groups. The
  one file the client writes is the cache file, atomically, at owner-only permissions.
- A dry run proves the request a program would send, never that the platform accepts it. Step 6's request as first
  written named `Custom Group` as the group type, which none of the reference estate's eighteen types is, and
  carried no member criteria; its dry run printed it without complaint on every run. With the type corrected, the
  platform refused it the first time it was sent (HTTP 400, "Define member criteria or objects to include"). A
  custom group's `resourceKindKey` is its group type, `Environment` here, and a group needs a rule or a member.
- The 401 in step 2 is simulated by corrupting the cached bearer, because a real expiry cannot be scheduled into a
  demo; the client's path is the same one an expired bearer takes.
- The consumption surface answers a large collection page with more than a hundred response headers (one `link`
  header per page); the standard library refuses such an answer unless its header limit is raised, which
  `resilient.py` does at import. Other HTTP libraries have their own limits; check yours.
- `paginate()` needs to know how the envelope declares its total: `pageInfo.totalCount` on VCF Operations (pages
  are 0-based), `resultTotal` on the consumption surface's cloud API (pages are 1-based and capped at 128).

## Reading the output

- Step 2 prints the mint count before and after; the difference is exactly one.
- Step 4 prints the values returned against `resultTotal`; a difference is the cap, and the walk that follows
  collects the declared total.
- Step 5 prints two `ShapeError` messages; each names the key or field that drifted and what was present instead.
- Step 6 prints `would send` with the method, path, and body size when the object is absent, or `exists` when it is
  there, and either way nothing is sent.
- Step 7 prints that the first resource reads back as expected, then the `EffectError` for the group step 6 did
  not send. In your own code, `ensure()` raises that error after a write whose effect a re-read cannot find.
- Step 8 prints `created` with the group count before and after, the second `ensure()` as `unchanged` with one
  write sent across both runs, the `EffectError` for an expectation the stored group does not meet, and the delete
  read back as gone, with the group count back where it started.

## Expected output

See [`expected-output.md`](expected-output.md).
