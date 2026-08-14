# Firewall-policy round-trip harness

Backs the microsegmentation sheet
([privatecloudarchitect.com/handbook/microsegmentation](https://privatecloudarchitect.com/handbook/microsegmentation)).
The sheet teaches three write disciplines for firewall-as-code; this harness proves all three on
your own estate in about a minute:

1. **Ship disabled, enable deliberately.** The section lands with its rule `disabled: true`,
   gets reviewed in place, and the enable is a one-field flip you can diff before applying.
2. **Realized is the only status that counts.** Every step verifies
   `status.conditions[type=Realized]` before proceeding.
3. **Rules speak groups.** The rule's from/to/appliedTo are a named group the harness creates
   and removes; no addresses anywhere.

## What it creates (and removes)

| Object | Kind | Why it is safe |
|---|---|---|
| `seg-proof-app` | `NetworkSecurityGroup` | carries no members, so it matches nothing |
| `seg-proof-section` | `FirewallPolicy` | one HTTPS allow rule, shipped disabled, `appliedTo` scoped to the empty group, priority 900000 (beneath everything you run) |

No traffic on your estate changes at any step. Teardown deletes both objects; run with `KEEP=1`
to keep them for inspection instead.

## Prereqs

A kubectl context named `vcfa-cci` at the org gateway with an org-admin **session** token
(same recipe as the isolation-design harness):

```bash
kubectl config set-cluster vcfa-cci --server=https://<vcfa-fqdn>/cci/kubernetes
kubectl config set-credentials vcfa-cci-user --token=<access-token>
kubectl config set-context vcfa-cci --cluster=vcfa-cci --user=vcfa-cci-user
```

The access token comes from the session login (`POST /cloudapi/1.0.0/sessions`); on an estate
with a self-signed CA add `--insecure-skip-tls-verify=true` to `set-cluster`. Then:

```bash
export VCFA_REGION=<your-region>     # kubectl --context vcfa-cci get regions
./run.sh
```

`run.sh` substitutes `<your-region>` into working copies of the manifests; you can equally edit
the three files under `manifests/` directly and apply them by hand in order.

## Four gateway facts the docs will not tell you

All four surfaced by first-party writes on a live estate; the harness is built around them:

- **Server-side dry-run is NOT dry on this plane.** `kubectl apply --dry-run=server` against
  `vpc.nsx` kinds at the org gateway **persists the object** when it passes NSX validation (the
  response still says "server dry run"). Do not use dry-run as a preview here. The review gate
  this plane actually gives you is the one the sheet teaches: land the document with its rule
  `disabled: true`, read it back, then flip the field.
- **Field managers are not persisted**, so every apply over an existing `vpc.nsx` object reports
  a conflict with `before-first-apply` even when your manager applied it seconds ago.
  `--force-conflicts` is the standard update idiom on this plane, not an override of another
  owner. (Creates apply cleanly either way.)
- **Tenant rules accept `ipProtocol: IPV4` only.** The platform's own default rules carry
  `IPV4_IPV6`, but that value is rejected on a tenant create.
- **Tenant priority must be 0-999999.** The default section sits at max-int priority; that is a
  system special you cannot use.

One more read-path detail: the **list** view of `firewallpolicies` trims `rules[]` (you see
`RULE COUNT` but no rules). Fetch the single object (`-o yaml`) to see the full rule grammar.

## Expected output

See [`expected-output.md`](expected-output.md) for the transcript shape a healthy run produces.
