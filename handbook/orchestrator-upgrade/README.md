# Orchestrator upgrade risk, measured on your own instance

Companion to field note 04,
[Aria Automation 8.18 to VCF Automation 9.1.1](https://privatecloudarchitect.com/notes/aria-automation-8-18-to-vcf-automation-9-1-1),
section 07, the Orchestrator. Three scripts answer the question an admin team asks before the upgrade:
which of our workflows, actions and environments stop working on the release we are moving to, and
what do we change. One reads your content, one measures the runtimes, and one runs your own actions on
the runtime you are moving to, because an action written years ago and fine on every past release is
not proven on the one you are about to get.

| File | What it is |
|---|---|
| `upgrade_risk.py` | Read-only, stdlib Python. Reads every action environment, action, workflow definition, plug-in, plug-in host, scheduled task and policy on your Orchestrator and checks them against the release you are moving to (R1 to R12, below). With `--files` it runs the script checks on exported `.py`, `.ps1` and `.js` files, so content kept in source control is checked with no instance at all. With `--compare` it diffs two probe records. Exit 0 nothing at risk, 1 at least one finding, 2 a read failed, 5 unknown option. |
| `probe.py` | Measures what each runtime actually provides, on throwaway objects. Plan by default. With `--execute` it creates up to four action environments, five actions in a new action module and one workflow in a new folder, runs the workflow once, prints and records the Python version and distributions, the PowerShell version and modules (with an import test of the names older scripts use), which JavaScript constructs the engine accepts and what each returns, and what an environment on a selector the instance no longer offers does. Then it deletes every object it created and reads each one back. Exit 0 clean, 1 an object it created is still there (its id is printed), 2 a call failed, 5 unknown option. |
| `qualify.py` | Runs your own actions on the target runtime, on throwaway copies. Reads each named action from the source instance (script, inputs, its environment's packages), builds a throwaway environment on the target instance's newest runtime of that family with the same packages and reports whether the install settles, copies the actions there, compiles each one and resolves its imports on that runtime, runs the cases you give it, then deletes everything and reads each object back. Source and target can be one instance or two. `--without` and `--pin` try a candidate package set on the copies, never on the source. Plan by default. Exit 0 every action loaded and every case passed, 1 something did not or a throwaway survived, 2 a call failed, 5 unknown option. |
| `targets/9.1.1.json`, `targets/9.1.0.0400.json` | What each release was measured to offer on the reference estate on 2026-10-16: runtime selectors, default memory, plug-ins, the Python distributions, the PowerCLI modules and the JavaScript constructs. `upgrade_risk.py --target` reads one. For another release, run `probe.py` on an instance of it and build the file the same way, or point `--target-host` at that instance. |
| `records/` | The two probe records, the two scan records (counts only) and the two qualification records behind the tables below. |
| `examples/at-risk/`, `examples/fixed/` | Three scripts, a Python port check, a PowerCLI report and a JavaScript lookup, each as written for an older release and as fixed. `upgrade_risk.py --files` flags every at-risk one and clears the fixed ones. |
| `examples/cases.json` | The case file format `qualify.py --cases` reads, with the two cases the reference estate ran: an action's own input names, and the fields its result must hold. |
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
- **A package that installed on the old runtime can stop installing on the new one, and the
  environment reports it only in its status.** `qualify.py` rebuilt the reference estate's DNS actions'
  environment (`pykerberos` 1.2.4, `pywinrm` 0.5.0, `requests` 2.28.1, `urllib3` 1.26.15,
  `requests-credssp`) on Python 3.14: it settled at `STALE_BUNDLE` in 11 seconds and held it, so the
  actions never loaded. Split across throwaway environments, `pykerberos`, pinned or unpinned, stopped
  at `STALE_BUNDLE`, and the other four installed (`UP_TO_DATE` in 22 seconds). None of the four
  actions on that environment uses Kerberos (three connect over CredSSP, one over NTLM), so the remedy
  was that one package: `qualify.py --without pykerberos` loaded all four on Python 3.14.5, and the
  environment was then rebuilt on `python:3.14` without it. The same run on the
  scan-automation module (`requests` and `urllib3` unpinned) installed, and all 13 actions compiled and
  resolved their imports on Python 3.14.5, with both cases in `examples/cases.json` passing.
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

3. **Run your own actions on the target runtime, before the production upgrade.** After it, they
   are already running there. Point the target at a lab instance on the release you are moving to (or
   use one instance, if it is already there). `qualify.py` writes, on throwaway copies only. Give a case
   to every action whose inputs touch nothing outside the Orchestrator; the rest are load-checked.

   ```bash
   export VRO_TARGET_HOST=<lab-fqdn-on-the-target-release> VRO_TARGET_TOKEN=<bearer>
   python3 qualify.py --module com.example.dns                                   # plan: nothing is created
   python3 qualify.py --module com.example.dns --cases cases.json --execute --record q.json
   python3 qualify.py --module com.example.dns --without pykerberos --execute    # a candidate package set
   ```

4. **Measure the runtimes, if you have a lab instance on each side.** `probe.py` writes, on throwaway objects
   only. Run it once on each release, compare, and give the scan the source record so it can name
   JavaScript constructs the two engines answer differently.

   ```bash
   python3 probe.py                                   # plan: nothing is created
   python3 probe.py --execute --record probe-source.json
   python3 upgrade_risk.py --compare probe-source.json records/probe-9.1.1.json
   python3 upgrade_risk.py --target targets/9.1.1.json --source-probe probe-source.json
   ```

5. **After the upgrade, scan again with the same target.** Every R1 line should now be an R2 line:
   kept, flagged, and running on the new runtime. Repoint each one you qualified, and do not repoint one
   that failed: fix the code or the package first.

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

`qualify.py` reports per source environment the install it ended in (`UP_TO_DATE`, or the status it
settled in, such as `STALE_BUNDLE`), and per action `loads pass on <runtime>` or why not, then `behaves
pass`, `fail` with the expected and actual fields, or `no cases`.

## Patterns that fix what it finds

- **Qualify before the upgrade, repoint after it.** The upgrade runs your content on the new runtime
  the moment it completes, so the proof has to come first, on an instance already at the target
  release: `qualify.py` for what is on an instance, or the same three checks in your pipeline for what
  is in source control (the packages install on the new selector, the code compiles and its imports
  resolve there, its cases pass). After the upgrade, hold the subscriptions that start workflows, set
  each environment R1 named to the new selector (`PUT /vco/api/environments/{id}`, which answers 202
  and rebuilds the dependencies), read the environment's `status` until `UP_TO_DATE` (`STALE_BUNDLE` is
  a package that did not install), run one action per environment, then release the subscriptions. A
  scriptable task or an action with a runtime of its own is changed in its editor or re-imported.
- **Resolve the selector at deploy time, and admit it only on proof.** Content in source control that
  names `python:3.11` will name it forever, and resolving to the newest selector alone deploys code
  nobody has run there. Read `GET /vco/api/server-configuration/polyglot-runtimes` when you deploy,
  take the newest selector of the family, refuse when the family is missing, and refuse when this
  version of the content has no passing qualification on that selector.
- **Python: use what every Python 3 ships.** `socket` in place of `telnetlib`, `shlex.quote` in place
  of `pipes.quote` (see `examples/`). Pin dependencies to releases that publish builds for the
  target's Python, or leave them unpinned and record what the rebuild resolved. When one package has
  no build there, prove the set without it (`--without NAME`) or at another version
  (`--pin NAME==VERSION`) before you change the real environment, and change it by sending back the
  body you read with only the runtime and dependencies altered: on 9.1.1 a `PUT` that leaves
  `runtimeMemoryLimit` out resets it to 0 (measured on throwaway environments).
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
- `qualify.py` proves that an action loads on the target runtime (it compiles and every import outside a
  `try` resolves) for every action it copies, and that it behaves only where you gave it a case. A
  case runs the real action, so give one only to an action whose inputs reach nothing outside the
  Orchestrator. JavaScript actions have no runtime selector and are not copied; `probe.py` measures the
  engine. It installs the source environment's packages on the target, so the target needs a reachable
  package repository, as any rebuild does.
- `probe.py` installs no dependency, so it needs no package repository. It prints no token value:
  for getToken it records only whether a token came back and its type.
- `upgrade_risk.py` prints object names unless you pass `--redact`; `--record` writes counts only.
  A plug-in host is shown by its connection type and session mode, never its address or account.
