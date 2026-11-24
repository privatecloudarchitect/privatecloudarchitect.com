# VCF Operations to ServiceNow: check both sides before the first sync

Companion to the chapter
([privatecloudarchitect.com/handbook/servicenow-management-pack](https://privatecloudarchitect.com/handbook/servicenow-management-pack)):
one script that reads what the ServiceNow Management Pack and VCF Operations' ServiceNow plug-in need, on each side,
before the pack's first sync and after every change to its configuration. It reads only: it creates, changes and
deletes nothing, in VCF Operations or in ServiceNow. Stdlib Python only; no token or password is printed or written,
and a secret file open to group or other is refused unread.

| File | What it is |
|---|---|
| `snowmp.py` | `file` (offline: your copy of the pack's configuration file and its custom trees), `ops` (VCF Operations) and `snow` (ServiceNow, as the account you name). Each prints one line per check, `HOLDS`, `FAILS` or `NOTE`, and with `--record` writes `<time>-snowmp-<subcommand>.json` to `OUT`, every estate name replaced by a placeholder, and refuses to write one in which a name survived. |
| `snowmp_ops.py` | The sign-in every VCF Operations companion shares, byte for byte: an api token from the console traded at the identity broker for a bearer. It carries this folder's own module name, so it never stands in for another folder's `opslib`. |
| `examples/` | A configuration file and a custom tree that pass every `file` check: one host class synced to `cmdb_ci_esx_server`, and one alerting configuration naming its alert definitions. Replace the definition id and the host name before you use them. |
| `records/` | Example output: the record each subcommand wrote in one run, kept to compare your own records against. |
| `expected-output.md` | Example output: what each subcommand printed in the same run. |

## Before you run it

1. **For `ops`, an identity that can read VCF Operations' solutions, adapters, outbound plug-ins and notification
   rules**, with an api token minted in the console, mode 0600.
2. **For `snow`, the account the pack or the plug-in signs in with**, and its password in a file, mode 0600. Run it once
   as each account: what it reports is what that account can read. On an instance that admits Basic API sign-in only
   to accounts holding `snc_basic_auth_api_access` or flagged web-service-access-only, an account with neither is
   refused at sign-in, and `snow` stops with exit 3, naming the two forms.
3. **For `file`, your copy of the pack's configuration file.** `snowmp.py` reads no file on the
   appliance: the pack reads its file from its `work` directory on the node that runs the adapter. Keep the copy you
   place there under version control and run `file` on it before each placement.

## Run it

```bash
python3 snowmp.py file my-config.json                          # offline; its custom_trees directory beside it

export OPS_HOST=<operations-fqdn> OPS_BROKER_HOST=<identity-broker-fqdn>
export OPS_API_TOKEN_FILE=~/.secrets/ops-reader                # mode 0600
export OPS_TLS_VERIFY=false                                    # only on a self-signed lab CA
python3 snowmp.py ops

export SNOW_INSTANCE=https://<instance>.service-now.com
export SNOW_USER=<the pack's account> SNOW_PASSWORD_FILE=~/.secrets/snow-pack   # mode 0600
python3 snowmp.py snow --elements state,priority              # the columns your alertingConfigs retrieve

export OUT=~/snowmp-records                                    # add --record to any of them to keep a shareable record
```

`snowmp.py` exits 0 when every check held; 1 when a check failed; 2 on a missing argument or setting, or a secret file
open to group or other; 3 when a sign-in or a read failed, or when the record was refused because a registered name
survived its scrub.

## What each subcommand checks

**`file`.** Whether the trees you enabled exist and map what they need: a custom class maps identifiers and the `name`
column, since a custom tree syncs only the columns it maps. Whether `syncMode` is one of the pack's three. Whether every
key of `nameFilter` names a class the trees sync: the CMDB class for the built-in tree, the `classIdentifier` for a
custom tree. Each filter is printed as what it is, an expression whose matches are **excluded**. Whether every
alerting configuration has its own `callerId`, names the alert definitions it acts on, and retrieves no reference
column. Each entry must name object types; its `filters.scope` takes object types only (the pack's configuration page
and its own sample configurations show no object or group scope on 9.1.1.0), so its own creates are not bounded by a
rule's object scope. A file with `alertingConfigs` prints a note: the pack's alert sync adds to the incident a notification rule
on the ServiceNow plug-in opens, matched by the caller (`callerId` is the caller the plug-in's rule sets), and on
9.1.1.0 it also opened records of its own, so count the records one alert makes after three cycles.

**`ops`.** The pack's version, then each of its adapter instances: every integer setting set (an instance created
through the API gets none of the defaults the pack's describe file declares), `sn_ssl_config` one of `No SSL`,
`No Verify` or `Verify`, and its status. A status the pack set when it refused its configuration carries the reason,
and `ops` prints it. Then each ServiceNow plug-in instance and every notification rule that uses one, each held to
carrying an object scope, a production group's objects, with definitions only narrowing it: a rule scoped by
definitions alone sends their alerts from every object, non-production included. It prints the pack's credential
kinds, the credential types the plug-in accepts, and the fields a rule on the plug-in sets, which carry no CI. When an
enabled rule on the plug-in and a pack instance are both present, it prints a note: it reads no file on the appliance,
so whether an `alertingConfigs` entry names the caller a rule sets is yours to read.

**`snow`.** The discovery source `VMwareTVS` on `cmdb_ci.discovery_source`; a reconciliation rule for it on each class
the trees sync (by default the built-in tree's six, `--classes` to name others); each class's identification rule,
which must be independent or depend on something, the rule the pack's own refusal states. The pack's refusal named
one class, and `snow` reads all of them. Then whether the account can read each table the pack's page "Creating a
Least Privileged User" lists, grouped by the purpose the page gives it, and whether it can query `sys_choice` by
field, which the pack's configure does. Event Management's tables are a note: the pack's page lists `em_alert` and `em_event` for the `ALERT` and `EVENT`
destinations, so an instance without them takes `INCIDENT`. With `--elements`, each column's type on the incident table, read from `incident` or
`task`, where most of its columns are defined. Last, for each class, that no two CIs the pack wrote share an identifier
(`correlation_id`, or `object_id` with `vcenter_uuid`): run it after the first sync and again after the second, which
should update each CI rather than add one.

## Reading the records

| Record | Fields to read |
|---|---|
| `file.json` | `facts.classes` (what the trees sync), `checks` |
| `ops.json` | `facts.pack`, `facts.adapters`, `facts.plugins`, `facts.rules_on_plugins`, `checks` |
| `snow.json` | `facts.classes`, `facts.elements`, `checks` |

Every check is `{"verdict", "check", "detail"}`. Every name is a placeholder: `{{adapter-n}}` an adapter instance,
`{{plugin-n}}` a plug-in instance, `{{rule-n}}` a notification rule, `{{host-n}}` a host, `{{account-n}}` the
ServiceNow account, `{{file-n}}` the pack's configuration file.

## What it does not cover

- **Writes.** It creates no discovery source, reconciliation rule, identification rule, role or account. Each refusal
  it reports names what to create; create it in ServiceNow and run `snow` again.
- **The least-privileged role.** `snow` reports what the account can read. Whether a role narrower than administrator
  passes the pack's configure is known only from the pack's status after a configure, which `ops` reads.
- **The pack's file on the appliance.** Run `file` on the copy you place; `ops` reads the API only, not the placed file.
- **Event Management.** It reports whether the tables exist and checks nothing in them.

Held by `platform/tests/test_servicenow_management_pack_companion.py` in the private repository, offline, against
stand-ins for VCF Operations and ServiceNow.
