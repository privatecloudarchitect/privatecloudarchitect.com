# Drift: name it before you correct it

[03-your-first-state](./03-your-first-state.md) proved the state changes nothing on a machine nobody touched. Machines
get touched. This page changes the managed file by hand, as a person under pressure would, and then lets Salt find the
change, show it, and only then put the file back.

## The one idea

`test=True` asks Salt what an apply **would** do, and does nothing. Run it first, every time: on a machine that drifted
it is a report of exactly what changed, with the diff; on a machine that did not, it is proof you are about to change
nothing. Correcting drift without reading it first throws away the evidence of what happened.

## Step 1: drift the file

Through the master, sign in to the minion and overwrite the managed file:

```bash
ssh -J salt-operator@198.51.100.26 salt-operator@192.0.2.67 \
  "echo 'managed-by: someone-else' | sudo tee /etc/guestcfg/managed.conf"
```

```
managed-by: someone-else
```

## Step 2: ask what an apply would do

```bash
ssh salt-operator@198.51.100.26 'sudo salt salt-minion-linux state.apply guestcfg test=True'
```

What it printed on the reference estate, 2026-11-12, shortened:

```
          ID: guestcfg-managed-file
    Function: file.managed
        Name: /etc/guestcfg/managed.conf
      Result: None
     Comment: The file /etc/guestcfg/managed.conf is set to be changed
              Note: No changes made, actual changes may
              be different due to other states.
     Changes:
              ----------
              diff:
                  ---
                  +++
                  @@ -1 +1,2 @@
                  -managed-by: someone-else
                  +managed-by: salt
                  +baseline: guest-configuration

Succeeded: 1 (unchanged=1, changed=1)
```

`Result: None` is how Salt says "would change". The diff is the drift, line for line: what someone wrote, and what the
baseline says. Nothing on the machine moved.

## Step 3: correct it, and read the file

```bash
ssh salt-operator@198.51.100.26 'sudo salt salt-minion-linux state.apply guestcfg'
ssh -J salt-operator@198.51.100.26 salt-operator@192.0.2.67 'cat /etc/guestcfg/managed.conf'
```

Shortened:

```
      Result: True
     Comment: File /etc/guestcfg/managed.conf updated
Succeeded: 1 (changed=1)
managed-by: salt
baseline: guest-configuration
```

## Two things that will bite you

**A drift you correct every hour and never read.** A schedule that applies the state every hour corrects drift
silently. Keep the hourly apply if you want it, but run `test=True` on a schedule too and keep its output: a file that
drifts every day is a process problem, and the diff names who to talk to.

**Two owners of one file.** If an application rewrites a file Salt also manages, each apply undoes the application and
the application undoes the apply. Salt owns the guest's files; what the Supervisor declares (the machine, its class, its
network) Salt must never try to change. Decide one owner per file before you write the state.

## What you just did, and where it goes

| You did | The habit |
|---|---|
| changed a managed file by hand | the realistic case: drift is not hypothetical |
| ran `test=True` first, and read the diff | evidence before correction |
| applied, then read the file | close the loop on the machine, not on the report |

## Next

[`05-a-windows-minion.md`](./05-a-windows-minion.md): the same minion, the same state, on Windows.
