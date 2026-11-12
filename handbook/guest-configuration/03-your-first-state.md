# Your first state: declare the end, then apply it twice

[02-one-minion-and-its-key](./02-one-minion-and-its-key.md) left you one trusted minion. This page gives it something to
hold. You read a short state, apply it, and apply it again. The second apply is the lesson.

## The one idea

A state does not say what to do. It says what must be true when it is done: this file, with these contents. Salt
compares that with the machine and changes only the difference. So the first apply creates what is missing, and every
apply after it, on a machine nobody touched, changes **nothing**. An apply that changes something the second time is a
state that fights itself, and it will fight you in production.

## Step 1: read the state

The master's first boot put three small states under `/srv/salt/guestcfg/`:

```bash
ssh salt-operator@198.51.100.26 'ls /srv/salt/guestcfg'
```

```
drift.sls
init.sls
probe.sls
```

`init.sls` is [`states/guestcfg/init.sls`](./states/guestcfg/init.sls) in this folder, which the master's template
writes there; read it on the master with `cat`, or here. Its three comment lines say what it is for; the state is:

```yaml
{% set managed_file = 'C:\\ProgramData\\guestcfg\\managed.conf' if grains['os_family'] == 'Windows' else '/etc/guestcfg/managed.conf' %}

guestcfg-managed-file:
  file.managed:
    - name: {{ managed_file }}
    - makedirs: True
    - contents: |
        managed-by: salt
        baseline: guest-configuration
```

`init.sls` is the state named `guestcfg`: one file, the same on Linux and Windows, at a path chosen from the minion's
own `os_family` grain. `drift.sls` and `probe.sls` serve the harness and the next pages.

## Step 2: apply it

```bash
ssh salt-operator@198.51.100.26 'sudo salt salt-minion-linux state.apply guestcfg'
```

What it printed on the reference estate, 2026-11-12, shortened:

```
salt-minion-linux:
----------
          ID: guestcfg-managed-file
    Function: file.managed
        Name: /etc/guestcfg/managed.conf
      Result: True
     Comment: File /etc/guestcfg/managed.conf updated
     Changes:
              ----------
              diff:
                  New file

Summary for salt-minion-linux
------------
Succeeded: 1 (changed=1)
Failed:    0
------------
Total states run:     1
```

## Step 3: apply it again

```bash
ssh salt-operator@198.51.100.26 'sudo salt salt-minion-linux state.apply guestcfg'
```

Shortened:

```
      Result: True
     Comment: File /etc/guestcfg/managed.conf is in the correct state
     Changes:

Succeeded: 1
Failed:    0
```

No `changed=`. Salt read the file, found it already true, and touched nothing. That one line is what makes a state safe
to run every hour.

## Two things that will bite you

**A state that always changes.** A command run with `cmd.run` and no `creates:`, `unless:` or `onlyif:` reports a change
on every apply, so the second-apply test fails and real drift hides among the false changes. Prefer `file`, `pkg` and
`service` states, which compare before they act; guard a command with the condition that makes it unnecessary.

**Targeting by name forever.** `salt salt-minion-linux` names one machine. Name a group instead as soon as there are
two: a grain (`salt -G 'os_family:RedHat'`), or a list (`salt -L 'web-01,web-02'`). The API account's rights in page 01
are a list of exactly this kind.

## What you just did, and where it goes

| You did | The habit |
|---|---|
| read a state before applying it | a state is code; read it like code |
| applied it twice, and read the second | idempotence, proven on the machine rather than assumed |
| targeted one minion by id | target by what a machine is, as soon as there is more than one |

## Next

[`04-drift.md`](./04-drift.md): change the file by hand, and watch Salt name the change before it undoes it.
