# Identifier placement record

Two tables, kept beside the estate's design and reviewed on the same schedule as the group check
(`python3 identifiers.py`). Fill them in before designing anything on tags; a hop or a consumer you cannot fill
in is one you are assuming.

## 1. Every hop an identifier makes between planes

One row per hop. The relationship is one of the six: replication, import, discovery, reference, projection,
coincidence. Between vCenter and NSX, reference does not exist: an NSX group criterion reads NSX's own
inventory.

| from plane | to plane | relationship | what runs it | how you would notice it stopping |
|---|---|---|---|---|
| | | | | |

## 2. The authoritative plane for each consumer

One row per consumer that turns an identifier into membership: a firewall rule, a policy, an alert, a report,
a controller or a selector.

| consumer | what it must see | authoritative plane | owner |
|---|---|---|---|
| | | | |

## 3. Every fact held on two planes

One row per fact that has to exist twice because two consumers read different planes. A row with no owner is
the next empty group.

| fact | plane A | plane B | what keeps the copies true | owner | how often it is checked |
|---|---|---|---|---|---|
| | | | | | |
