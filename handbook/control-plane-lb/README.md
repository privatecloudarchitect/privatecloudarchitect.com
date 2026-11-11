# Walking the load-balancer graph behind a control-plane VIP

Companion to the chapter
([privatecloudarchitect.com/handbook/control-plane-lb](https://privatecloudarchitect.com/handbook/control-plane-lb)):
one read-only script that walks the object graph on the load-balancer controller itself and reports what is
there now. Stdlib Python only; no password or session token is printed or written.

| File | What it is |
|---|---|
| `vip.py` | Logs in to the controller, then walks forwards from every virtual service: the address object it references, the policy set it carries, and the pools that policy set's rules select. Reconciles the pool count against the number of selection rules, which is how a pool nothing routes to becomes visible, and reports how many members each pool holds. Writes `vip.json`, and refuses to write a record carrying an estate value. |
| `vip.json` | Example output: the record of the walk on the reference estate's controller, 2026-10-22, every object name replaced. Your run writes the record of your own controller in its place. |

## Run it

```bash
export AVI_HOST=<controller-fqdn>
export AVI_USER=<username>
export AVI_PASSWORD_FILE=/path/to/password   # mode 0600
export TLS_VERIFY=false                      # only on a self-signed lab CA

python3 vip.py
```

`vip.py` sends no `X-Avi-Tenant` header, so it walks the tenant your login lands in. A guest cluster's endpoint sits
in its organization's tenant on the controller, so it appears in the walk only when that is your login's default
tenant.

| Exit | Meaning |
|---|---|
| 0 | every pool holds a member |
| 1 | a pool is empty: expected during a build, the failure after one, so schedule the check outside build windows |
| 2 | an argument was given, a setting is missing, or a password file is open to group or other |
| 3 | the login or a read failed |
| 4 | the record refused to write because an estate name survived the scrub |

`expected-output.md` is example output: what it printed on the reference estate, to compare your own run against.

The controller's API takes a **session login**: `POST /login` with a username and password, then the session cookie
together with the CSRF token it sets and a `Referer` header on every read. On Avi 32.1.1 the VCF Identity Broker's
bearer answered 401, and other schemes were not tried. A script written against the bearer habit fails in a way that
looks like an authorization problem.

## Walk it forwards

In every walk on VCF 9.1.0 and 9.1.1 no virtual service held a direct pool reference. Each carried a policy set, and
the policy set's rules selected pools, so the chain was four objects rather than three and the choice of pool was made
in the policy set. That is why one virtual service can front more than one pool, and why walking backwards from a pool
is the harder direction. `vip.py` prints how many direct pool references your controller carries.

## Scope, stated plainly

- Read-only. Every call is a `GET` after the login.
- It sends no tenant header, so it walks the tenant its login defaults to. A guest cluster's objects sit in its
  organization's tenant on the controller, and a read in another tenant does not return them.
- It reports the graph **at rest**. The objects carry a last-modified timestamp and no creation time, so the
  order in which they were provisioned exists only in the controller's configuration-event log, not here.
- If the counts do not reconcile on your controller, the graph has a shape this script did not expect. That
  difference is the finding, and the record prints the arithmetic rather than a verdict.
- Every object name in the record is a placeholder.

## Reading the record

`counts` is the census: virtual services, address objects, policy sets, pools and the selection rules that
explain the pool total. `graph` is one row per virtual service with its ports, its address object, its policy
sets and the pools those select, plus `hasDirectPoolRef` which is how the missing reference is shown rather
than described. `reconciles` is the arithmetic check, `poolsSelectedByARule` the count that feeds it, and
`emptyPools` the pools holding no member, the alert outside a build window. `poolSizes` is the membership histogram and
`addressesAllocated` the address count.
