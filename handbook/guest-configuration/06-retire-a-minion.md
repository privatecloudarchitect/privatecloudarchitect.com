# Retire a minion: the key first, then the machine, then the master

[05-a-windows-minion](./05-a-windows-minion.md) left you a master with two accepted minions. This page takes all of it
down. The order is the lesson: undo trust before you remove the thing that was trusted, and remove the master last,
because it is the one thing that can still issue trust.

## The one idea

An accepted key outlives its machine. Delete a minion's VM and leave its key, and the master still holds an accepted
identity named `salt-minion-linux`. The next machine to present a key under that id is refused (page 02's denied key).
A machine that has a copy of the old private key, from a backup or a cloned disk, is accepted as the old minion. So
retire in this order:

1. **The key,** on the master: the identity stops being trusted.
2. **The machine,** through `kubectl delete`: nothing is left to present the key.
3. **The master, and its front doors,** once no minion depends on it.

## Step 1: delete the keys, by exact id

```bash
ssh salt-operator@198.51.100.26 'sudo salt-key -d salt-minion-linux -y; sudo salt-key -d salt-minion-win -y'
```

```
The following keys are going to be deleted:
Accepted Keys:
salt-minion-linux
Key for minion salt-minion-linux deleted.
The following keys are going to be deleted:
Accepted Keys:
salt-minion-win
Key for minion salt-minion-win deleted.
```

`-d <id>` deletes that one id, the same discipline as `-a <id>`. There is a `-D` that deletes every key; like `-A`, these
pages never use it.

## Step 2: delete the minions, and read the master's key list

```bash
kubectl delete -f minion-linux.yaml -f minion-win.yaml
ssh salt-operator@198.51.100.26 'sudo salt-key -L'
```

What they printed, with your namespace's name in place of the reference estate's:

```
secret "salt-minion-linux-bootstrap" deleted from <your-namespace> namespace
virtualmachine.vmoperator.vmware.com "salt-minion-linux" deleted from <your-namespace> namespace
secret "salt-minion-win-bootstrap" deleted from <your-namespace> namespace
virtualmachine.vmoperator.vmware.com "salt-minion-win" deleted from <your-namespace> namespace
Accepted Keys:
Denied Keys:
Unaccepted Keys:
Rejected Keys:
```

Deleting by file removes the Secret with the machine, and with it the Windows Administrator password. The master is
back to page 01's empty list.

## Step 3: delete the master and its two load balancers

```bash
kubectl delete -f master.yaml -f ssh-front-door.yaml
kubectl get virtualmachines,virtualmachineservices,secrets,pvc
```

```
secret "salt-master-bootstrap" deleted from <your-namespace> namespace
virtualmachine.vmoperator.vmware.com "salt-master" deleted from <your-namespace> namespace
virtualmachineservice.vmoperator.vmware.com "salt-api" deleted from <your-namespace> namespace
virtualmachineservice.vmoperator.vmware.com "salt-master-ssh" deleted from <your-namespace> namespace
No resources found in <your-namespace> namespace.
```

The read is the proof, not the deletes: four kinds, nothing left. Then clear your working folder, which holds the
API's private key, its password, the Windows password and the filled templates:

```bash
cd .. && rm -r salt-lessons
```

## Three things that will bite you

**A key that comes back.** Deleting a key does not stop its minion. A minion still running offers its key again, and
the master lists it as unaccepted. In the VM Apps proof of these pages, a key deleted while its machine still ran was
back, pending, before the machine's delete had finished, and a new machine built under the same id then landed in
`Denied Keys`, as page 02's box on a second machine under one id says. An unaccepted key is not trusted, so undoing trust first is still right. Read
the key list once the machines are gone, and delete by its id anything that came back.

**A machine deleted before its key.** Delete the VM first and its key stays accepted on the master. Nothing warns you.
Read `salt-key -L` after every retirement and delete any id with no machine behind it. On a master that runs for years,
that list is your inventory of trust; keep it honest.

**A namespace delete as a shortcut.** Deleting the whole namespace removes everything in it, so the order stops
mattering for these lessons. On a real estate the master outlives every minion, and minions leave one at a time. Practice
the order here, where it costs nothing.

## What you just did, and where it goes

| You did | Why it matters | In a pipeline |
|---|---|---|
| deleted each key by exact id | trust undone before the machine goes | the API's `key.delete` with a match of one id |
| deleted the machines by their files | the Secret and its password go with them | deleting the deployment (page 07) |
| deleted the master last, and read the namespace | the proof is the read, not the delete | the same read after a deployment delete |

## Next

[`07-the-same-as-blueprints.md`](./07-the-same-as-blueprints.md): the same master and minions as VCF Automation
blueprints, which a catalog can offer and a deployment can delete.
