# Identifier planes

You tag a machine `prod` in vSphere, write an NSX security group whose criterion is `VM Tag equals prod`,
and the group stays empty. Nothing errors. Every object in the chain reads healthy.

A workload on VCF 9.1 can be labelled in at least five places, and three of them use the word *tag*:

| plane | shape | who can read it |
|---|---|---|
| **vSphere tag** | `category = value` | VCF Operations collects it and its custom groups match on it |
| **vSphere custom attribute** | `key = value` | a different store on the same objects; not what a tag rule matches |
| **Kubernetes label** | `key = value`, selectable | Kubernetes selectors, on the Supervisor's `VirtualMachine` |
| **Kubernetes annotation** | `key = value`, **not** selectable | controllers write here; nothing selects on it |
| **NSX tag** | `scope = tag` | the only plane an NSX group criterion can see |

## Six relationships, all of them called "sync"

"vCenter tags do not sync to NSX" is true and nearly useless, because it collapses six different things:

| kind | what it means |
|---|---|
| **replication** | B keeps a live copy of A's identifier and follows it |
| **import** | B creates its own identifiers from A's, **once**; they diverge from that moment |
| **discovery** | B ingests A's continuously, marks them foreign (`dis:` prefix), and refuses edits |
| **reference** | B's rule engine reads A's store when it evaluates, storing nothing |
| **projection** | A writes into B's store, and needs a credential on B to do it |
| **coincidence** | two planes use the same word and share nothing |

The one people assume between vCenter and NSX is **reference**, and it is the one that does not happen. NSX
documents an **import** of vCenter tags, which creates NSX tags; that is a different relationship with a
different failure mode (it is correct on the day you run it and drift by the following week).

## Run it

```bash
export VC_HOST=<vcenter-fqdn>  VC_USER=<user>  VC_PASSWORD_FILE=/path/to/pw    # mode 0600
export NSX_HOST=<nsx-fqdn>     NSX_USER=<user> NSX_PASSWORD_FILE=/path/to/pw   # optional
export OPS_HOST=<ops-fqdn>     OPS_TOKEN_FILE=/path/to/token                   # optional
export TLS_VERIFY=false                                                        # self-signed lab CA only
python3 identifiers.py
```

That is read-only. It reports which planes it could reach and with which credential (reading all five takes
three), how many identifiers each plane has **defined** against how many objects **carry** one, and every
group whose membership is defined by a tag together with whether it currently resolves to anything.

That last number is the one worth scheduling. A group is a query, and a query the plane cannot answer
returns **zero rather than an error**, so an empty group appears on no dashboard and in no alert.

To measure the propagation question rather than read about it:

```bash
export IDENT_PROBE_VMS="a-machine,another-machine"
python3 identifiers.py --probe-propagation
```

This creates one vSphere tag category, one tag inside it, and one NSX group; attaches that tag to the
machines **you named**; looks for the value in NSX's own inventory; and asks a purpose-built NSX group about
it. It will not choose the machines for you: a script that picks its own subjects on somebody's estate is
not a probe, it is a surprise.

Two disciplines are worth copying out of it:

- **It refuses to run without a positive control.** If no NSX group matching an NSX-native tag currently
  resolves to any member, the probe stops, because a zero would then be unreadable: equally consistent with
  a broken endpoint, a wrong id, an unlicensed feature, and a genuine absence.
- **It verifies its own teardown after a delay.** An NSX policy `DELETE` that returns `200`, followed by a
  `GET` that returns `404`, is not proof. One group deleted exactly that way was present again later,
  carrying its original expression. The teardown now reads back twice, 30 seconds apart, reports both
  answers, and refuses to finish if the delayed one is not `404`.

## What it does not cover

The Security Services Platform is not exercised by this script. The **write** discipline, meaning who may set a
tag, how a machine's guess must not overwrite a human's designation, how classification gets written back
without rotting, is a separate subject with its own chapter; this one is only about which plane holds an
identifier and who can see it.
