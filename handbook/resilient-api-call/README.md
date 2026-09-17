# The resilient API call, as code

Step three of the chapter
([privatecloudarchitect.com/handbook/resilient-api-call](https://privatecloudarchitect.com/handbook/resilient-api-call)):
the three guarantees as a client you can read in one sitting, and a read-only demo that exercises each one against
your own estate. Stdlib Python only; no token value is ever printed.

| File | What it is |
|---|---|
| `resilient.py` | The client. A bearer minted through a callable you supply, cached with its expiry and refreshed on a UTC buffer, re-minted exactly once when a call answers 401; `unwrap()` and `require()` as the typed boundary, naming the key or field that drifted; `paginate()` reading a whole collection and refusing to stop short of the total the envelope declares; `ensure()` as find-by-key, update-if-changed, create-if-absent, with a dry run that returns the request instead of sending it. TLS verification is configuration, warned about on stderr whenever it is off. |
| `demo.py` | Six read-only steps: one read through the boundary; the bearer corrupted and recovered with one re-mint; a whole collection read against its declared total; the answer that lies (a capped page declaring the true total, and an answer with more headers than the standard library accepts by default); the boundary refusing two drifted shapes by name; an idempotent ensure in dry-run mode. Exit 0 when every step ran. |

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

python3 demo.py
```

## Scope, stated plainly

- Proven on one VCF Operations 9.1.0 instance and its VCF Automation on 2026-09-16; every number in
  `expected-output.md` is from that run. Your totals will differ; the shape of each step should not.
- Read-only. The demo sends no mutation: step 6 runs `ensure()` in dry-run mode and prints the request it would
  have sent. The one file the client writes is the cache file, atomically, at owner-only permissions.
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

## Expected output

See [`expected-output.md`](expected-output.md).
