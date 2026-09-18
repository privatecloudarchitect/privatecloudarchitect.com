# Walking the load-balancer graph behind a control-plane VIP

Companion to the chapter
([privatecloudarchitect.com/handbook/control-plane-lb](https://privatecloudarchitect.com/handbook/control-plane-lb)):
one read-only script that walks the object graph on the load-balancer controller itself and reports what is
there now. Stdlib Python only; no password or session token is printed or written.

| File | What it is |
|---|---|
| `vip.py` | Logs in to the controller, then walks forwards from every virtual service: the address object it references, the policy set it carries, and the pools that policy set's rules select. Reconciles the pool count against the number of selection rules, which is how a pool nothing routes to becomes visible, and reports how many members each pool holds. Writes `vip.json`, and refuses to write a record carrying an estate value. |
| `vip.json` | That record from the reference estate, 2026-09-18. The chapter's plates render it. |

## Run it

```bash
export AVI_HOST=<controller-fqdn>
export AVI_USER=<username>
export AVI_PASSWORD_FILE=/path/to/password   # mode 0600
export TLS_VERIFY=false                      # only on a self-signed lab CA

python3 vip.py
```

The controller's API is a **session login, not a bearer**: `POST /login` with a username and password, then
carry the session cookie together with the CSRF token it sets and a `Referer` header on every read. A script
written against the bearer habit fails here in a way that looks like an authorization problem.

## Forwards is the only direction that works

A virtual service holds no pool reference. It carries a policy set, and the policy set's rules select pools, so
the chain is four objects rather than three and the port-to-pool choice is made in the fourth. That is why one
virtual service can front more than one pool, and why walking backwards from a pool answers nothing.

## Scope, stated plainly

- Read-only. Every call is a `GET` after the login.
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
`emptyPools` the orphan shape no health view surfaces. `poolSizes` is the membership histogram and
`addressesAllocated` the address count.
