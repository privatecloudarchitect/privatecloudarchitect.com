# Orchestrator upgrade risk, measured on your own instance

Companion to field note 04,
[Aria Automation 8.18 to VCF Automation 9.1.1](https://privatecloudarchitect.com/notes/aria-automation-8-18-to-vcf-automation-9-1-1),
section 07, the Orchestrator. Two scripts answer the question an admin team asks before the upgrade:
which of our workflows, actions and environments stop working on the release we are moving to, and
what do we change. One reads, the other measures.

| File | What it is |
|---|---|
| `upgrade_risk.py` | Read-only, stdlib Python. Reads every action environment, action, workflow definition, plug-in, plug-in host, scheduled task and policy on your Orchestrator and checks them against the release you are moving to (R1 to R12, below). With `--files` it runs the script checks on exported `.py`, `.ps1` and `.js` files, so content kept in source control is checked with no instance at all. With `--compare` it diffs two probe records. Exit 0 nothing at risk, 1 at least one finding, 2 a read failed, 5 unknown option. |
| `probe.py` | Measures what each runtime actually provides, on throwaway objects. Plan by default. With `--execute` it creates up to four action environments, five actions in a new action module and one workflow in a new folder, runs the workflow once, prints and records the Python version and distributions, the PowerShell version and modules (with an import test of the names older scripts use), which JavaScript constructs the engine accepts and what each returns, and what an environment on a selector the instance no longer offers does. Then it deletes every object it created and reads each one back. Exit 0 clean, 1 an object it created is still there (its id is printed), 2 a call failed, 5 unknown option. |
| `targets/9.1.1.json`, `targets/9.1.0.0400.json` | What each release was measured to offer on the reference estate on 2026-10-16: runtime selectors, default memory, plug-ins, the Python distributions, the PowerCLI modules and the JavaScript constructs. `upgrade_risk.py --target` reads one. For another release, run `probe.py` on an instance of it and build the file the same way, or point `--target-host` at that instance. |
| `records/` | The two probe records and the two scan records (counts only) behind the tables below. |
| `examples/at-risk/`, `examples/fixed/` | Three scripts, a Python port check, a PowerCLI report and a JavaScript lookup, each as written for an older release and as fixed. `upgrade_risk.py --files` flags every at-risk one and clears the fixed ones. |
| `expected-output.md` | Transcripts of every command on this page, from the reference estate. |

## What the upgrade does to a script, measured

Read on the reference estate on 2026-10-16, on a standalone Orchestrator at 9.1.0.0400 and the
Orchestrator embedded in VCF Automation 9.1.1.0100, whose `/vco/api/about` reports 9.1.1.0.25643527.

| | 9.1.0.0400 | 9.1.1 |
|---|---|---|
| Python | `python:3.11`, runs 3.11.13 | `python:3.14`, runs 3.14.5 |
| PowerShell | `powershell:7.4`, runs 7.4.11 | `powershell:7.6`, runs 7.6.2 |
| PowerCLI | `powercli:9.0.0-powershell-7.4`: VCF.PowerCLI 9.0.0, VMware modules numbered 101.0.0 | `powercli:9.1.1-powershell-7.6`: VCF.PowerCLI 9.1.1, VMware modules numbered 13.5.1 |
| Node.js | `node:24` | `node:24` |
| JavaScript constructs accepted, of the 41 probed | 33 | 37: spread in arrays and objects, regular-expression named groups and lookbehind added; nothing removed |
| Default memory | 150 MB PowerShell and PowerCLI, 64 MB Python and Node.js | the same |

Four facts follow from those runs, and they decide how to read everything else here.

1. **The upgrade keeps the selector you stored.** An environment, an action or a scriptable task that
   names `python:3.11` still names it after the instance moves to 9.1.1, and reports
   `validationMessage: MISSING_RUNTIME`. The 8.18.1 release notes did state a remap when PowerCLI 12
   was removed ("Scripts depending on it are automatically run on the latest PowerCLI 13 with
   PowerShell 7.4 runtime"); the 9.1.1 release notes state no runtime version and no remap.
2. **The object still runs, on the newest runtime of that family.** An environment created on
   `python:3.11` on the 9.1.1 instance ran its action on Python 3.14.5, and one on
   `powercli:9.0.0-powershell-7.4` ran on PowerShell 7.6.2. The 9.1.0.0400 instance did the same
   with `python:3.10` (ran on 3.11.13) and `powercli:13-powershell-7.4` (ran on 7.4.11).
3. **Only the environment carries the flag.** An action bound to such an environment reports no validation
   message of its own. On the reference estate 17 actions sit on environments flagged
   `MISSING_RUNTIME` and every one of them reads clean. A scriptable task with its own runtime
   carries its own flag.
4. **So what breaks is the code meeting a newer runtime, not the selector.** A Python script that
   imports a module Python 3.13 removed, a PowerShell script that imports `VMware.PowerCLI`, a
   module version pin written against 101.0.0, a dependency pinned to a release that publishes no
   build for Python 3.14. Those are what `upgrade_risk.py` looks for.

Three more measurements belong beside them:

- **Neither PowerCLI runtime installs `VMware.PowerCLI`, PowerNSX or PowervRA.** `Import-Module`
  fails for all three on both releases ("no valid module file was found"), although the 9.1
  Scripting Environments page lists the PowerCLI runtime as including "VMware PowerCLI, PowerNSX,
  and PowervRA modules". `VMware.VimAutomation.Core` and the `VMware.Sdk.*` modules, including
  `VMware.Sdk.Nsx.Policy`, are installed on both.
- **In Python the context is a dict.** `context.getToken()` raises `AttributeError` on both releases;
  `context["getToken"]()` returned a token on the 9.1.0.0400 instance. On the 9.1.1 instance the
  same call failed on a fresh token with `CERTIFICATE_VERIFY_FAILED`. The two instances present
  certificates from different issuers, so the run does not separate the release from the
  certificate as the cause: run `probe.py` on your target and read the line.
- **The JavaScript engine still refuses classes and async functions, and `let` in a loop is not
  per iteration.** The probe's closure test answers 2 on both releases, the pre-2015 behavior, so
  code that relies on a fresh binding per pass gets the last value on either engine.

## Run it

Set the connection once. `VRO_TOKEN` is any bearer the appliance accepts; which one that is depends on
how the appliance authenticates, and `GET /vco/api/server/authentication`, unauthenticated, tells you
its mode.

```bash
export VRO_HOST=<orchestrator-fqdn>
read -rs VRO_TOKEN && export VRO_TOKEN          # typed, never in the shell history
export TLS_VERIFY=false                         # only on a self-signed lab CA
```

1. **Scan the instance you are upgrading, against the release you are moving to.** Read-only; run it
   on the 8.18 instance itself.

   ```bash
   python3 upgrade_risk.py --target targets/9.1.1.json
   python3 upgrade_risk.py --target targets/9.1.1.json --redact --record risk.json   # to share
   ```

2. **Scan what you keep in source control.** No instance needed.

   ```bash
   python3 upgrade_risk.py --target targets/9.1.1.json --files src/**/*.py src/**/*.ps1 src/**/*.js
   ```

3. **Measure, if you have a lab instance on each side.** `probe.py` writes, on throwaway objects
   only. Run it once on each release, compare, and give the scan the source record so it can name
   JavaScript constructs the two engines answer differently.

   ```bash
   python3 probe.py                                   # plan: nothing is created
   python3 probe.py --execute --record probe-source.json
   python3 upgrade_risk.py --compare probe-source.json records/probe-9.1.1.json
   python3 upgrade_risk.py --target targets/9.1.1.json --source-probe probe-source.json
   ```

4. **After the upgrade, scan again with the same target.** Every R1 line should now be an R2 line:
   kept, flagged, and running on the new runtime. Work that list down.

## Reading the output

`BREAKS` fails on the target as written. `CHECK` may work and has to be run there to know.

| Check | What it finds |
|---|---|
| R1 CHECK | A selector the target does not offer. The object will run on the target's runtime of that family; an action bound to the environment is listed under it. |
| R2 CHECK | A selector this instance already does not offer: it already runs on the newest. |
| R3 BREAKS | A Python import of a standard-library module the target's Python removed: `distutils`, `imp`, `asynchat`, `asyncore` and `smtpd` in 3.12; `aifc`, `audioop`, `cgi`, `cgitb`, `chunk`, `crypt`, `imghdr`, `mailcap`, `msilib`, `nis`, `nntplib`, `ossaudiodev`, `pipes`, `sndhdr`, `spwd`, `sunau`, `telnetlib`, `uu`, `xdrlib` and `lib2to3` in 3.13. |
| R4 BREAKS | `new Command(...)`: the Command scripting object was removed in Automation Orchestrator 8.17. |
| R5 | BREAKS for a plug-in installed here that the target does not ship; CHECK for one the target deprecates (Auto Deploy, deprecated since 9.0). |
| R6 CHECK | Environment dependencies to rebuild on the target selector, pinned and unpinned. A package with compiled parts pinned to an old release may publish no build for the new Python. |
| R7 | BREAKS for `context.getToken()` in Python; CHECK for any use of getToken, to run once on a fresh token and again after it refreshes. |
| R8 | BREAKS for a PowerShell import of a module the target's PowerCLI runtime does not install; CHECK for a module version pin. |
| R9 CHECK | JavaScript that reaches Java classes, and constructs the two engines answer differently. |
| R10 CHECK | Plug-in hosts to re-test: VM Apps hosts (how each authenticates), PowerShell hosts (a Kerberos host needs krb5.conf on the target), SSH hosts (FIPS-compatible algorithms). |
| R11 CHECK | Scheduled tasks and policies, to confirm each runs as its user after the upgrade. |
| R12 CHECK | Scripts with characters outside ASCII: the 9.1.1.0 release notes list such characters as encoded on package export. |

## Patterns that fix what it finds

- **Repoint after the upgrade, never before.** The target's selector does not exist on the source, so
  the change waits for the upgraded instance. Hold the subscriptions that start workflows, upgrade,
  set each environment R1 named to the new selector (the REST call is `PUT /vco/api/environments/{id}`,
  which answers 202 and rebuilds the dependencies), read the environment's `status`, run one action
  per environment, then release the subscriptions. A scriptable task or an action with a runtime of
  its own is changed in its editor or re-imported with the new selector.
- **Resolve the selector at deploy time.** Content in source control that names `python:3.11` will
  name it forever. Read `GET /vco/api/server-configuration/polyglot-runtimes` when you deploy, take
  the newest selector of the family, and refuse when the family is missing.
- **Python: use what every Python 3 ships.** `socket` in place of `telnetlib`, `shlex.quote` in place
  of `pipes.quote` (see `examples/`). Pin dependencies to releases that publish builds for the
  target's Python, or leave them unpinned and record what the rebuild resolved.
- **PowerShell: import the module you use, by name, without a version.** `VMware.VimAutomation.Core`
  rather than `VMware.PowerCLI`; `VMware.Sdk.Nsx.Policy` rather than PowerNSX; REST calls rather
  than PowervRA. A pin written against one release's numbering (101.0.0) fails on the next (13.5.1).
- **getToken: read it as the key it is.** `context["getToken"]()`, then run it once on the target,
  because the call goes back to the instance over TLS and the runtime has to trust what it finds.
- **JavaScript: no Command object, no Java classes, and no new syntax in shared packages during the
  window.** Run a command over SSH or in a Python action that JavaScript calls by module path
  (`examples/fixed/lookup_host.js`). External instances upgrade after the embedded one, so syntax
  9.1.1 accepts and 9.1.0 refuses stays out of anything an older instance imports.
- **Kerberos on a PowerShell host.** On VCF Automation 9.0.x, Broadcom KB 419182 creates krb5.conf by
  hand at `/usr/lib/vco/app-server/conf/krb5.conf` in each `vco-app` pod, and KB 439771 records that
  a 9.0.x restore does not bring the file back, with a fix stated for 9.2. The 8.18 release notes
  also list the PowerShell plug-in as not supporting Kerberos in FIPS mode. Test the host on your
  target before you rely on it.

## Scope, stated plainly

- One estate, two instances: an embedded Orchestrator on 9.1.1 and a standalone one on 9.1.0.0400.
  No 8.18 instance was available, so the 8.18 side rests on the vendor's release notes, and the scan
  runs against your 8.18 instance itself.
- The run on the newest runtime of a family was measured for Python and PowerCLI. Node.js offers the
  same selector on both releases, and a stale plain-PowerShell selector was not tested.
- Whether a dependency bundle built for one Python loads under the next was not measured; R6 says
  rebuild and read the log, because that is the only answer this run supports.
- `probe.py` installs no dependency, so it needs no package repository. It prints no token value:
  for getToken it records only whether a token came back and its type.
- `upgrade_risk.py` prints object names unless you pass `--redact`; `--record` writes counts only.
  A plug-in host is shown by its connection type and session mode, never its address or account.
