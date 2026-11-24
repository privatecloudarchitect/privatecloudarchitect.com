# Expected output

Example output: what `snowmp.py` printed for each subcommand with `--record`, on 2026-11-23, every name read from
the estate replaced by a placeholder. Your run prints your own names without `--record`, and placeholders with it.
Each block is the record of the same name under `records/`, printed line for line.

## `file`

The shipped example configuration and its custom tree, offline.

```
$ python3 snowmp.py file examples/config.json --record
HOLDS  custom trees are enabled and the custom_trees directory holds a tree: examples/custom_trees
HOLDS  custom class 'ESX host' maps identifiers
HOLDS  custom class 'ESX host' maps the name column
HOLDS  syncMode is one of the page's three: POPULATE_ONLY
NOTE   objectIdentifierSource: UUID: it applies to VMs only. MOID, the page's choice for a first population, is reassigned when a VM moves to another vCenter; UUID is optional on a VM. On a populated CMDB keep the format its object_id column already holds
HOLDS  every name filter key names a class the trees sync: 1 key(s)
NOTE   name filter 'ESX host' EXCLUDES the names it matches: ^(?!esx01\.example\.com$).*$
HOLDS  every alertingConfig has its own callerId: VCF Operations - host tier
HOLDS  alertingConfig 'VCF Operations - host tier' narrows its scope to object types: its scope takes object types only, so its own creates are not bounded by a rule's object scope
HOLDS  alertingConfig 'VCF Operations - host tier' names its alert definitions
HOLDS  alertingConfig 'VCF Operations - host tier' retrieves primitive columns only: by a list of common reference columns; snow --elements reads each column's type
NOTE   this file turns on the pack's alert sync (alertingConfigs): it adds to incidents a notification rule on the ServiceNow plug-in opens with the caller callerId names; on 9.1.1.0 it also opened records of its own: count the records one alert makes after three cycles
record: ./2026-11-24T014615Z-snowmp-file.json

9 held, 0 failed, 3 notes
```

## `ops`

VCF Operations, read with an administrator's api token: the pack installed, one adapter instance stopped, one ServiceNow plug-in instance and no notification rule on it.

```
$ python3 snowmp.py ops --record
HOLDS  the ServiceNow Management Pack is installed: ServiceNow Management Pack 9.1.1.0.25703502
NOTE   the pack's credential kinds: ServiceNow Credentials (sn_username, sn_password); ServiceNow + Proxy Credentials (proxy_username, proxy_password, sn_username, sn_password)
NOTE   the ServiceNow plug-in's credential types: basic
NOTE   a notification rule on the plug-in sets: caller_id, category, subcategory, business_service, contact_type, state, close_code, close_notes, hold_reason, impact, urgency, priority, assignment_group, assigned_to, severity, upon_approval, problem_id, caused_by, rfc; cmdb_ci is not among them
HOLDS  adapter '{{adapter-1}}': every integer setting is set
HOLDS  adapter '{{adapter-1}}': sn_ssl_config is one of No SSL, No Verify, Verify: Verify
NOTE   adapter '{{adapter-1}}' is stopped: it syncs nothing and opens nothing: STOPPED None
NOTE   ServiceNow plug-in instances: {{plugin-1}} (on)
record: ./2026-11-23T165728Z-snowmp-ops.json

3 held, 0 failed, 5 notes
```

## `snow`

ServiceNow before it was prepared for the pack: no VMwareTVS discovery source and no reconciliation rule for it, and two classes whose identification rule depends on nothing.

```
$ python3 snowmp.py snow --elements state,priority,assignment_group --record
FAILS  the discovery source VMwareTVS exists on cmdb_ci.discovery_source
FAILS  a reconciliation rule for VMwareTVS on cmdb_ci_vcenter_datastore
FAILS  cmdb_ci_vcenter_datastore's identification rule is independent or depends on something: rule from cmdb_ci_vm_object, independent False, depends_on 0
FAILS  a reconciliation rule for VMwareTVS on cmdb_ci_vcenter_datacenter
FAILS  cmdb_ci_vcenter_datacenter's identification rule is independent or depends on something: rule from cmdb_ci_logical_datacenter, independent False, depends_on 0
FAILS  a reconciliation rule for VMwareTVS on cmdb_ci_esx_server
HOLDS  cmdb_ci_esx_server's identification rule is independent or depends on something: rule from cmdb_ci_esx_server, independent True, depends_on 0
FAILS  a reconciliation rule for VMwareTVS on cmdb_ci_vcenter_cluster
HOLDS  cmdb_ci_vcenter_cluster's identification rule is independent or depends on something: rule from cmdb_ci_host_cluster, independent False, depends_on 1
FAILS  a reconciliation rule for VMwareTVS on cmdb_ci_vcenter
HOLDS  cmdb_ci_vcenter's identification rule is independent or depends on something: rule from cmdb_ci_appl, independent False, depends_on 1
FAILS  a reconciliation rule for VMwareTVS on cmdb_ci_vmware_instance
HOLDS  cmdb_ci_vmware_instance's identification rule is independent or depends on something: rule from cmdb_ci_vm_instance, independent False, depends_on 3
NOTE   cmdb_ci_vcenter_datastore: no CI from VMwareTVS yet: run snow again after the first sync
NOTE   cmdb_ci_vcenter_datacenter: no CI from VMwareTVS yet: run snow again after the first sync
NOTE   cmdb_ci_esx_server: no CI from VMwareTVS yet: run snow again after the first sync
NOTE   cmdb_ci_vcenter_cluster: no CI from VMwareTVS yet: run snow again after the first sync
NOTE   cmdb_ci_vcenter: no CI from VMwareTVS yet: run snow again after the first sync
NOTE   cmdb_ci_vmware_instance: no CI from VMwareTVS yet: run snow again after the first sync
HOLDS  the account reads sys_user_has_role (all configurations): answered 200
HOLDS  the account reads security_acl_detail (all configurations): answered 200
HOLDS  the account reads sys_security_operation (all configurations): answered 200
HOLDS  the account reads cmdb_metadata_hosting (resource grouping): answered 200
HOLDS  the account reads cmdb_metadata_reference (resource grouping): answered 200
HOLDS  the account reads cmdb_metadata_containment (resource grouping): answered 200
HOLDS  the account reads sys_dictionary (resource grouping): answered 200
HOLDS  the account reads sys_glide_object (resource grouping): answered 200
HOLDS  the account reads sys_choice (alerting): answered 200
HOLDS  the account reads incident (alerting): answered 200
HOLDS  the account reads sys_db_object (cmdb sync): answered 200
HOLDS  the account reads cmdb_reconciliation_definition (cmdb sync): answered 200
HOLDS  the account reads cmdb_rel_type (cmdb sync): answered 200
NOTE   em_alert on this instance: answered 400: the ALERT destination writes to this table, so use INCIDENT
NOTE   em_event on this instance: answered 400: the EVENT destination writes to this table, so use INCIDENT
HOLDS  incident.state is a primitive column: type integer
HOLDS  incident.priority is a primitive column: type integer
FAILS  incident.assignment_group is a primitive column: type reference
record: ./2026-11-23T165942Z-snowmp-snow.json

19 held, 10 failed, 8 notes
```
