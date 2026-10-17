# Expected output

Transcripts from the reference estate on 2026-10-16: an embedded Orchestrator on VCF 9.1.1 (9.1.1.0.25643527, inside VCF Automation 9.1.1.0100) and a standalone Orchestrator one release behind (9.1.0.0400.25545107). Scan transcripts redact object names with `--redact`; the counts and selectors are the estate's own. The qualification transcripts name the actions, which are the reference estate's sample content.

## 1. probe.py on the 9.1.1 instance

`python3 probe.py --execute --record records/probe-9.1.1.json`. Every object it created was deleted and read back as gone. The `py_stale` and `ps_stale` lines are the measurement this folder is built on: an environment naming a selector the instance no longer offers is accepted, reports `MISSING_RUNTIME`, and runs on the instance's own runtime of that family.

```text
orchestrator 9.1.1.0.25643527
runtimes offered: node:24, powercli:9.1.1-powershell-7.6, powershell:7.6, python:3.14
default memory limits: {"node:24": 64000000, "powercli:9.1.1-powershell-7.6": 150000000, "powershell:7.6": 150000000, "python:3.14": 64000000}

creating, in this order:
  environment      pcaprobe_20261016175416_py_current  [python:3.14]
  environment      pcaprobe_20261016175416_py_stale  [python:3.11]
  environment      pcaprobe_20261016175416_powercli  [powercli:9.1.1-powershell-7.6]
  environment      pcaprobe_20261016175416_ps_stale  [powercli:9.0.0-powershell-7.4]
  action module    com.pcaprobe.p20261016175416
  action           com.pcaprobe.p20261016175416/probe_js  [javascript]
  action           com.pcaprobe.p20261016175416/probe_py_current  [python:3.14]
  action           com.pcaprobe.p20261016175416/probe_py_stale  [python:3.11]
  action           com.pcaprobe.p20261016175416/probe_powercli  [powercli:9.1.1-powershell-7.6]
  action           com.pcaprobe.p20261016175416/probe_ps_stale  [powercli:9.0.0-powershell-7.4]
  workflow folder  pcaprobe_20261016175416
  workflow         pcaprobe_20261016175416 upgrade probe
  environment py_current   [python:3.14] created; status UP_TO_DATE, validationMessage None
  environment py_stale     [python:3.11] created; status UP_TO_DATE, validationMessage 'MISSING_RUNTIME'
  environment powercli     [powercli:9.1.1-powershell-7.6] created; status UP_TO_DATE, validationMessage None
  environment ps_stale     [powercli:9.0.0-powershell-7.4] created; status UP_TO_DATE, validationMessage 'MISSING_RUNTIME'
  action probe_js           imported; validationMessage None
  action probe_py_current   imported; validationMessage None
  action probe_py_stale     imported; validationMessage None
  action probe_powercli     imported; validationMessage None
  action probe_ps_stale     imported; validationMessage None
  workflow run started; waiting up to 900s
  workflow run completed in 33s

cleanup:
  delete workflow               200  read back 404
  delete workflow folder        204  read back 404
  delete action probe_ps_stale  200  read back 404
  delete action probe_powercli  200  read back 404
  delete action probe_py_stale  200  read back 404
  delete action probe_py_current 200  read back 404
  delete action probe_js        200  read back 404
  delete action module          204  read back 404
  delete environment ps_stale   204  read back 404
  delete environment powercli   204  read back 404
  delete environment py_stale   204  read back 404
  delete environment py_current 204  read back 404
  residue: none

results:
  javascript engine unavailable: TypeError: getPackage is not a function, it is object.; 37 of 41 constructs accepted
    let_const              ok: 3
    let_loop_closure       ok: 2
    arrow_function         ok: 42
    template_literal       ok: hello vro
    class_declaration      FAIL: SyntaxError: identifier is a reserved word: class
    class_extends          FAIL: SyntaxError: identifier is a reserved word: class
    destructuring          ok: 10
    spread_array           ok: 3
    spread_object          ok: 2
    default_params         ok: 6
    rest_params            ok: 3
    for_of                 ok: 6
    map_set                ok: a2
    symbol                 ok: symbol
    generator              ok: 3
    promise                ok: function
    async_await            FAIL: SyntaxError: missing ; before statement
    optional_chaining      ok: true
    nullish_coalescing     ok: d
    exponent_operator      ok: 1024
    array_includes         ok: true
    object_entries         ok: 1
    string_padstart        ok: 005
    array_flat             ok: 2
    object_fromentries     ok: 1
    string_replaceall      ok: a+b+c
    array_at               ok: 3
    logical_assignment     ok: 7
    numeric_separator      ok: 1000
    bigint                 ok: bigint
    regex_named_groups     ok: 2026
    regex_lookbehind       ok: 1
    computed_property      ok: 1
    shorthand_method       ok: 1
    json_roundtrip         ok: 2
    e4x_xml_literal        ok: 1
    for_each_in            ok: 3
    define_getter          ok: 1
    proto_property         ok: true
    date_slash_format      ok: 2026
    java_system_property   FAIL: TypeError: getProperty is not a function, it is object.
  py_current  [python:3.14] ran on python 3.14.5, 4 distributions, getToken {"ok": false, "error": "URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1081)>"}
    context (dict) keys: basedir, environment, executionId, getToken, memoryLimit, returnType, runnerId, starter, timeout, vcoUrl
  py_stale    [python:3.11] ran on python 3.14.5, 4 distributions, getToken {"ok": false, "error": "URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1081)>"}
    context (dict) keys: basedir, environment, executionId, getToken, memoryLimit, returnType, runnerId, starter, timeout, vcoUrl
  powercli    [powercli:9.1.1-powershell-7.6] ran on powershell 7.6.2, 44 modules
    VCF.PowerCLI==9.1.1.25581542
    VMware.Sdk.Vcf.CloudBuilder==13.5.1.25581542
    VMware.Sdk.Vcf.Installer==13.5.1.25581542
    VMware.Sdk.Vcf.Ops==13.5.1.25581542
    VMware.Sdk.Vcf.SddcManager==13.5.1.25581542
    VMware.VimAutomation.Core==13.5.1.25581542
    Import-Module VMware.PowerCLI            FAIL: The specified module 'VMware.PowerCLI' was not loaded because no valid module file was found in any module directory.
    Import-Module PowerNSX                   FAIL: The specified module 'PowerNSX' was not loaded because no valid module file was found in any module directory.
    Import-Module PowervRA                   FAIL: The specified module 'PowervRA' was not loaded because no valid module file was found in any module directory.
    Import-Module VMware.VimAutomation.Core  ok in 0.0s
  ps_stale    [powercli:9.0.0-powershell-7.4] ran on powershell 7.6.2, 44 modules
    VCF.PowerCLI==9.1.1.25581542
    VMware.Sdk.Vcf.CloudBuilder==13.5.1.25581542
    VMware.Sdk.Vcf.Installer==13.5.1.25581542
    VMware.Sdk.Vcf.Ops==13.5.1.25581542
    VMware.Sdk.Vcf.SddcManager==13.5.1.25581542
    VMware.VimAutomation.Core==13.5.1.25581542
    Import-Module VMware.PowerCLI            FAIL: The specified module 'VMware.PowerCLI' was not loaded because no valid module file was found in any module directory.
    Import-Module PowerNSX                   FAIL: The specified module 'PowerNSX' was not loaded because no valid module file was found in any module directory.
    Import-Module PowervRA                   FAIL: The specified module 'PowervRA' was not loaded because no valid module file was found in any module directory.
    Import-Module VMware.VimAutomation.Core  ok in 0.0s

```

## 2. What changed between 9.1.0.0400 and 9.1.1

`python3 upgrade_risk.py --compare records/probe-9.1.0.0400.json records/probe-9.1.1.json`. Lines appear only where the two records differ: four JavaScript constructs the 9.1.1 engine accepts and the 9.1.0.0400 engine refused, nothing the other way, and every PowerCLI module renumbered from 101.0.0 to 13.5.1.

```text
9.1.0.0400.25545107  ->  9.1.1.0.25643527
runtimes: node:24, powercli:9.0.0-powershell-7.4, powershell:7.4, python:3.11  ->  node:24, powercli:9.1.1-powershell-7.6, powershell:7.6, python:3.14
javascript engine: 'unavailable: TypeError: Cannot call property getPackage in object [JavaPackage java.lang.Package]. It is not a function, it is "objec'  ->  'unavailable: TypeError: getPackage is not a function, it is object.'
  java_system_property   FAIL: TypeError: Cannot call property getProperty in object [JavaPackage java.lang.System]. It is not a function, it is "object". -> FAIL: TypeError: getProperty is not a function, it is object.
  regex_lookbehind       FAIL: SyntaxError: Invalid quantifier ?  -> ok: 1
  regex_named_groups     FAIL: SyntaxError: Invalid quantifier ?  -> ok: 2026
  spread_array           FAIL: SyntaxError: syntax error          -> ok: 3
  spread_object          FAIL: SyntaxError: invalid property id   -> ok: 2
py_current: python 3.11.13 -> 3.14.5; 4 -> 4 distributions
  changed  pip==24.3.1 -> 26.1.1
  changed  setuptools==69.0.3 -> 80.9.0
powercli: powershell 7.4.11 -> 7.6.2; 44 -> 44 modules
  changed  PSReadLine==2.3.6 -> 2.4.5
  changed  VCF.PowerCLI==9.0.0.25182333 -> 9.1.1.25581542
  changed  VMware.CloudServices==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.DeployAutomation==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.ImageBuilder==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.OpenAPI==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.Nsx.Policy==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.Nsx.Policy.GlobalInfra==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.Nsx.Policy.Infra==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.Nsx.Policy.Initialize==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.Srm==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.Vcf.CloudBuilder==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.Vcf.Installer==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.Vcf.Ops==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.Vcf.SddcManager==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.Vr==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Sdk.vSphere==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Vcf.SddcManager==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Vcf.Sso==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.Vim==9.0.0.25182333 -> 9.1.0.25581542
  changed  VMware.VimAutomation.Cis.Core==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Cloud==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Common==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Core==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Hcx==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.License==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Nsxt==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Sdk==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Security==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Srm==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Storage==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Vds==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Vmc==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.Vpc==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.WorkloadManagement==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VimAutomation.vROps==101.0.0.25182333 -> 13.5.1.25581542
  changed  VMware.VumAutomation==101.0.0.25182333 -> 13.5.1.25581542
```

## 3. The standalone instance, scanned against 9.1.1 before its upgrade

`python3 upgrade_risk.py --target targets/9.1.1.json --source-probe records/probe-9.1.0.0400.json --redact`. Exit 1: nothing breaks outright, and 39 objects need a check because their content will run on Python 3.14, PowerShell 7.6 and PowerCLI 9.1.1, unproven until qualified.

```text
orchestrator 9.1.0.0400.25545107 -> target VCF 9.1.1.0 (orchestrator 9.1.1.0.25643527)
runtimes here:  node:24, powercli:9.0.0-powershell-7.4, powershell:7.4, python:3.11
runtimes there: node:24, powercli:9.1.1-powershell-7.6, powershell:7.6, python:3.14
selectors that do not carry: powercli:9.0.0-powershell-7.4 -> powercli:9.1.1-powershell-7.6, powershell:7.4 -> powershell:7.6, python:3.11 -> python:3.14
read: 736 workflows (9 polyglot scriptable tasks), 724 actions (17 polyglot), 4 environments, 22 plug-ins, 0 scheduled tasks, 0 policies

CHECK  R1 a selector the target does not offer: kept, flagged, and run on the target's own runtime unproven: 8
  environment environment-2
      python:3.11 -> runs on python:3.14, unproven: qualify it there; 4 bound: action action-1, action action-2, action action-3, action action-4
  environment environment-3
      python:3.11 -> runs on python:3.14, unproven: qualify it there; 12 bound: action action-5, action action-6, action action-7, action action-8, action action-9, action action-10 ...
  environment environment-4
      python:3.11 -> runs on python:3.14, unproven: qualify it there
  scriptable task workflow-2 / Scriptable task
      python:3.11 -> runs on python:3.14, unproven: qualify it there
  scriptable task workflow-3 / Scriptable task
      powershell:7.4 -> runs on powershell:7.6, unproven: qualify it there
  scriptable task workflow-5 / Scriptable task
      python:3.11 -> runs on python:3.14, unproven: qualify it there
  scriptable task workflow-6 / Scriptable task
      python:3.11 -> runs on python:3.14, unproven: qualify it there
  scriptable task workflow-7 / prepare command
      python:3.11 -> runs on python:3.14, unproven: qualify it there

CHECK  R2 a selector this instance already does not offer: 5
  environment environment-1
      powercli:13-powershell-7.4 is not offered here (MISSING_RUNTIME); runs on powercli:9.0.0-powershell-7.4 here and powercli:9.1.1-powershell-7.6 there; 1 bound: scriptable task workflow-1 / Scriptable task
  action action-17
      python:3.10 is not offered here (MISSING_RUNTIME); runs on python:3.11 here and python:3.14 there
  scriptable task workflow-4 / Scriptable task
      python:3.10 is not offered here (MISSING_RUNTIME); runs on python:3.11 here and python:3.14 there
  scriptable task workflow-8 / Scriptable task
      python:3.7 is not offered here (MISSING_RUNTIME); runs on python:3.11 here and python:3.14 there
  scriptable task workflow-8 / Scriptable task
      python:3.7 is not offered here (MISSING_RUNTIME); runs on python:3.11 here and python:3.14 there

CHECK  R5 plug-ins the target does not ship, or deprecates: 1
  plug-in AutoDeploy
      documented deprecated since 9.0 and to be removed in a future release (VCF 9.1 docs, Using the Auto Deploy Plug-In)

CHECK  R6 environment dependencies to rebuild: 3
  environment environment-2
      rebuild on python:3.14 and read the install log; pinned: pywinrm==0.5.0, requests==2.28.1, urllib3==1.26.15; unpinned: requests-credssp
  environment environment-3
      rebuild on python:3.14 and read the install log; pinned: none; unpinned: requests, urllib3
  environment environment-4
      rebuild on python:3.14 and read the install log; pinned: pypsrp==0.9.0, pywinrm==0.5.0, requests-credssp==2.0.0; unpinned: none

CHECK  R12 scripts with characters outside ASCII: 22
  action action-5
      5 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-6
      3 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-7
      6 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-18
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-8
      5 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-9
      6 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-19
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-10
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-11
      12 distinct non-ASCII characters, including emoji or other characters beyond the BMP: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-12
      5 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-20
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-21
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-22
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-13
      5 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-23
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-14
      8 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-15
      2 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-16
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  scriptable task workflow-9 / Get VMs
      3 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  scriptable task workflow-10 / Generate Cleanup Summary
      2 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  scriptable task workflow-11 / Extract generate_vulnerability_report outputs
      4 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  scriptable task workflow-12 / Scriptable task
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package

summary: 0 BREAKS, 39 CHECK
```

## 4. The embedded instance, after its upgrade

`python3 upgrade_risk.py --target targets/9.1.1.json --redact` on the instance already on 9.1.1. The selectors 9.1.0 offered now appear under R2: kept as they were, flagged `MISSING_RUNTIME`, and running on the 9.1.1 runtimes.

```text
orchestrator 9.1.1.0.25643527 -> target VCF 9.1.1.0 (orchestrator 9.1.1.0.25643527)
runtimes here:  node:24, powercli:9.1.1-powershell-7.6, powershell:7.6, python:3.14
runtimes there: node:24, powercli:9.1.1-powershell-7.6, powershell:7.6, python:3.14
read: 742 workflows (9 polyglot scriptable tasks), 723 actions (18 polyglot), 4 environments, 22 plug-ins, 0 scheduled tasks, 0 policies

CHECK  R2 a selector this instance already does not offer: 13
  environment environment-1
      python:3.11 is not offered here (MISSING_RUNTIME); runs on python:3.14; 13 bound: action action-1, action action-2, action action-3, action action-4, action action-5, action action-6 ...
  environment environment-2
      powercli:13-powershell-7.4 is not offered here (MISSING_RUNTIME); runs on powercli:9.1.1-powershell-7.6; 1 bound: scriptable task workflow-1 / Scriptable task
  environment environment-3
      python:3.11 is not offered here (MISSING_RUNTIME); runs on python:3.14
  environment environment-4
      python:3.11 is not offered here (MISSING_RUNTIME); runs on python:3.14; 4 bound: action action-14, action action-15, action action-16, action action-17
  action action-18
      python:3.10 is not offered here (MISSING_RUNTIME); runs on python:3.14
  scriptable task workflow-2 / Scriptable task
      python:3.7 is not offered here (MISSING_RUNTIME); runs on python:3.14
  scriptable task workflow-2 / Scriptable task
      python:3.7 is not offered here (MISSING_RUNTIME); runs on python:3.14
  scriptable task workflow-3 / Scriptable task
      python:3.11 is not offered here (MISSING_RUNTIME); runs on python:3.14
  scriptable task workflow-4 / prepare command
      python:3.11 is not offered here (MISSING_RUNTIME); runs on python:3.14
  scriptable task workflow-5 / Scriptable task
      python:3.11 is not offered here (MISSING_RUNTIME); runs on python:3.14
  scriptable task workflow-6 / Scriptable task
      python:3.11 is not offered here (MISSING_RUNTIME); runs on python:3.14
  scriptable task workflow-7 / Scriptable task
      python:3.10 is not offered here (MISSING_RUNTIME); runs on python:3.14
  scriptable task workflow-8 / Scriptable task
      powershell:7.4 is not offered here (MISSING_RUNTIME); runs on powershell:7.6

CHECK  R5 plug-ins the target does not ship, or deprecates: 1
  plug-in AutoDeploy
      documented deprecated since 9.0 and to be removed in a future release (VCF 9.1 docs, Using the Auto Deploy Plug-In)

CHECK  R6 environment dependencies to rebuild: 3
  environment environment-1
      rebuild on python:3.14 and read the install log; pinned: none; unpinned: requests, urllib3
  environment environment-3
      rebuild on python:3.14 and read the install log; pinned: pypsrp==0.9.0, pywinrm==0.5.0, requests-credssp==2.0.0; unpinned: none
  environment environment-4
      rebuild on python:3.14 and read the install log; pinned: pykerberos==1.2.4, pywinrm==0.5.0, requests==2.28.1, urllib3==1.26.15; unpinned: requests-credssp

CHECK  R10 plug-in hosts to re-test: 3
  VM Apps host vm-apps-host-1
      {"connectionType": "vra-onprem", "sessionMode": "Per User Session"}; read how it authenticates: vIDM user credentials end at the identity cut-over, and an API token is the 9.1.1 alternative for shared and scheduled runs
  PowerShell host powershell-host-1
      {"transportProtocol": "HTTPS", "type": "WinRM"}; re-test a session on the target; a host that authenticates with Kerberos needs krb5.conf there
  SSH host ssh-host-1
      re-test with FIPS-compatible algorithms on the remote host

CHECK  R12 scripts with characters outside ASCII: 23
  action action-19
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-20
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-21
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-1
      8 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-2
      2 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-22
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-23
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-3
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-24
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-4
      5 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-5
      12 distinct non-ASCII characters, including emoji or other characters beyond the BMP: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-6
      5 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-7
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-8
      6 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-9
      5 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-10
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-11
      5 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-12
      6 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  action action-13
      3 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  scriptable task workflow-9 / Get VMs
      3 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  scriptable task workflow-10 / Extract generate_vulnerability_report outputs
      4 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  scriptable task workflow-11 / Scriptable task
      1 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package
  scriptable task workflow-12 / Extract generate_vulnerability_report outputs
      4 distinct non-ASCII characters: 9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package

summary: 0 BREAKS, 43 CHECK
```

## 5. Exported files, no instance needed

`python3 upgrade_risk.py --target targets/9.1.1.json --source-probe records/probe-9.1.0.0400.json --files examples/at-risk/*`, then the same on `examples/fixed/*`. The fixed set leaves one CHECK: any use of getToken is worth one run on the target.

```text
files: 3 read against VCF 9.1.1.0 (Python 3.14.5, PowerShell 7.6.2)

BREAKS R3 a Python module the target's Python removed: 1
  file examples/at-risk/port_check.py
      imports pipes (removed in Python 3.13), telnetlib (removed in Python 3.13); target Python 3.14

BREAKS R4 the Command scripting object: 1
  file examples/at-risk/lookup_host.js
      uses new Command(...); run the command over SSH or a polyglot action

BREAKS R7 Python that calls getToken: 2
  file examples/at-risk/port_check.py
      calls context.getToken(): the Python context is a dict, so this raises AttributeError; call context["getToken"]()
  [CHECK] file examples/at-risk/port_check.py
      uses getToken: run it on the target on a fresh token and again after the token refreshes; probe.py makes the same call

BREAKS R8 PowerShell modules by name and by version: 3
  file examples/at-risk/vm_report.ps1
      imports PowerNSX, which the target's PowerCLI runtime does not install
  file examples/at-risk/vm_report.ps1
      imports VMware.PowerCLI, which the target's PowerCLI runtime does not install
  [CHECK] file examples/at-risk/vm_report.ps1
      pins a module version; on the target VMware.VimAutomation.Core is 13.5.1.25581542: compare the pin with the target's modules

CHECK  R9 JavaScript that may answer differently on the target engine: 2
  file examples/at-risk/lookup_host.js
      reaches Java classes: the engine and its class access change between releases; run it on the target
  file examples/at-risk/lookup_host.js
      uses spread_array: here 'FAIL: SyntaxError: syntax error', on the target 'ok: 3'

summary: 5 BREAKS, 4 CHECK
```

```text
files: 4 read against VCF 9.1.1.0 (Python 3.14.5, PowerShell 7.6.2)

CHECK  R7 Python that calls getToken: 1
  file examples/fixed/port_check.py
      uses getToken: run it on the target on a fresh token and again after the token refreshes; probe.py makes the same call

summary: 0 BREAKS, 1 CHECK
```

## 6. qualify.py, the plan

`python3 qualify.py --module com.vmware.specialists.dns.utilities`. Reads the actions and the target's runtimes, groups the actions by the environment they share, and creates nothing.

```text
target orchestrator 9.1.1.0.25643527; runtimes node:24, powercli:9.1.1-powershell-7.6, powershell:7.6, python:3.14
  pythonWithLibs [python:3.11 here -> python:3.14 there], 5 package(s): com.vmware.specialists.dns.utilities/testPython, com.vmware.specialists.dns.utilities/MsDnsAddRemoveHost, com.vmware.specialists.dns.utilities/MsDnsAdddRemoveEntry

plan only: nothing created. Add --execute to copy, build, load, run and delete.
```

## 7. qualify.py, an environment whose packages no longer install

`python3 qualify.py --module com.vmware.specialists.dns.utilities --execute --record records/qualify-dns-9.1.1.json`. Exit 1. The environment these three actions share pins `pykerberos`, and on Python 3.14 its install settled at `STALE_BUNDLE`; the actions were never loaded. Split across throwaway environments, `pykerberos` alone, pinned or unpinned, settled at `STALE_BUNDLE` and the other four packages installed, so the remedy is that one package, not the runtime.

```text
target orchestrator 9.1.1.0.25643527; runtimes node:24, powercli:9.1.1-powershell-7.6, powershell:7.6, python:3.14
  pythonWithLibs [python:3.11 here -> python:3.14 there], 5 package(s): com.vmware.specialists.dns.utilities/testPython, com.vmware.specialists.dns.utilities/MsDnsAddRemoveHost, com.vmware.specialists.dns.utilities/MsDnsAdddRemoveEntry
  environment for pythonWithLibs: PENDING_DOWNLOAD after 0s
  environment for pythonWithLibs: STALE_BUNDLE after 11s

cleanup:
  delete environment 0          204  read back 404
  delete action module          204  read back 404
  residue: none

results:
  environment from pythonWithLibs on python:3.14: install STALE_BUNDLE
  com.vmware.specialists.dns.utilities/testPython: loads skipped; behaves -  (environment install STALE_BUNDLE)
  com.vmware.specialists.dns.utilities/MsDnsAddRemoveHost: loads skipped; behaves -  (environment install STALE_BUNDLE)
  com.vmware.specialists.dns.utilities/MsDnsAdddRemoveEntry: loads skipped; behaves -  (environment install STALE_BUNDLE)

```

## 8. qualify.py, a module that is ready

`python3 qualify.py --module com.broadcom.vcf.specialists.scan-automation.actions --cases examples/cases.json --execute --record records/qualify-scan-9.1.1.json`. Exit 0. The install settled, all 13 actions compiled and resolved their imports on Python 3.14.5, and both cases for `parse_cleanup_event` returned what they expect; the other 12 call out to a scanner and are load-checked only.

```text
target orchestrator 9.1.1.0.25643527; runtimes node:24, powercli:9.1.1-powershell-7.6, powershell:7.6, python:3.14
  scan_automation_python_3_11_runtime [python:3.11 here -> python:3.14 there], 2 package(s): com.broadcom.vcf.specialists.scan-automation.actions/evaluate_deployment_policy, com.broadcom.vcf.specialists.scan-automation.actions/generate_scan_summary, com.broadcom.vcf.specialists.scan-automation.actions/parse_domain_join_values, com.broadcom.vcf.specialists.scan-automation.actions/check_vm_customization_status, com.broadcom.vcf.specialists.scan-automation.actions/generate_vulnerability_report, com.broadcom.vcf.specialists.scan-automation.actions/delete_asset_from_site, com.broadcom.vcf.specialists.scan-automation.actions/parse_cleanup_event (+2 cases), com.broadcom.vcf.specialists.scan-automation.actions/get_asset_vulnerabilities, com.broadcom.vcf.specialists.scan-automation.actions/trigger_adhoc_scan, com.broadcom.vcf.specialists.scan-automation.actions/parse_provision_event, com.broadcom.vcf.specialists.scan-automation.actions/search_asset_by_ip, com.broadcom.vcf.specialists.scan-automation.actions/poll_scan_status, com.broadcom.vcf.specialists.scan-automation.actions/get_site_by_name
  environment for scan_automation_python_3_11_runtime: PENDING_DOWNLOAD after 0s
  environment for scan_automation_python_3_11_runtime: UP_TO_DATE after 11s

cleanup:
  delete workflow               200  read back 404
  delete workflow folder        204  read back 404
  delete action get_site_by_name 200  read back 404
  delete action poll_scan_status 200  read back 404
  delete action search_asset_by_ip 200  read back 404
  delete action parse_provision_event 200  read back 404
  delete action trigger_adhoc_scan 200  read back 404
  delete action get_asset_vulnerabilities 200  read back 404
  delete action parse_cleanup_event 200  read back 404
  delete action delete_asset_from_site 200  read back 404
  delete action generate_vulnerability_report 200  read back 404
  delete action check_vm_customization_status 200  read back 404
  delete action parse_domain_join_values 200  read back 404
  delete action generate_scan_summary 200  read back 404
  delete action evaluate_deployment_policy 200  read back 404
  delete action pcaqual_loader_0 200  read back 404
  delete environment 0          204  read back 404
  delete action module          204  read back 404
  residue: none

results:
  environment from scan_automation_python_3_11_runtime on python:3.14: install UP_TO_DATE
  com.broadcom.vcf.specialists.scan-automation.actions/evaluate_deployment_policy: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/generate_scan_summary: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/parse_domain_join_values: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/check_vm_customization_status: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/generate_vulnerability_report: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/delete_asset_from_site: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/parse_cleanup_event: loads pass on Python 3.14.5; behaves pass
  com.broadcom.vcf.specialists.scan-automation.actions/get_asset_vulnerabilities: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/trigger_adhoc_scan: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/parse_provision_event: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/search_asset_by_ip: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/poll_scan_status: loads pass on Python 3.14.5; behaves no cases
  com.broadcom.vcf.specialists.scan-automation.actions/get_site_by_name: loads pass on Python 3.14.5; behaves no cases

```

## 9. qualify.py, the same environment without the package that stopped it

`python3 qualify.py --actions com.vmware.specialists.dns.utilities/MsDnsAddRemoveHost com.vmware.specialists.dns.utilities/MsDnsAdddRemoveEntry com.vmware.specialists.dns.utilities/testPython com.vmware.specialists.powershell.utilities/runPowershellCommand --without pykerberos --execute --record qualify-dns-without-pykerberos.json`, the record kept here as `records/qualify-dns-9.1.1-without-pykerberos.json`. Exit 0. The four actions that share the environment from section 7 connect over CredSSP and NTLM, never Kerberos, so the run drops `pykerberos` from the copy and keeps the source as it is. The install settles at `UP_TO_DATE` and every action loads; with no cases given, behaves is not claimed.

```text
candidate packages for every copy: without pykerberos
target orchestrator 9.1.1.0.25643527; runtimes node:24, powercli:9.1.1-powershell-7.6, powershell:7.6, python:3.14
  pythonWithLibs [python:3.11 here -> python:3.14 there], 4 package(s): com.vmware.specialists.powershell.utilities/runPowershellCommand, com.vmware.specialists.dns.utilities/testPython, com.vmware.specialists.dns.utilities/MsDnsAddRemoveHost, com.vmware.specialists.dns.utilities/MsDnsAdddRemoveEntry
  environment for pythonWithLibs: PENDING_DOWNLOAD after 0s
  environment for pythonWithLibs: UP_TO_DATE after 11s

cleanup:
  delete workflow               200  read back 404
  delete workflow folder        204  read back 404
  delete action MsDnsAdddRemoveEntry 200  read back 404
  delete action MsDnsAddRemoveHost 200  read back 404
  delete action testPython      200  read back 404
  delete action runPowershellCommand 200  read back 404
  delete action pcaqual_loader_0 200  read back 404
  delete environment 0          204  read back 404
  delete action module          204  read back 404
  residue: none

results:
  environment from pythonWithLibs on python:3.14: install UP_TO_DATE
  com.vmware.specialists.powershell.utilities/runPowershellCommand: loads pass on Python 3.14.5; behaves no cases
  com.vmware.specialists.dns.utilities/testPython: loads pass on Python 3.14.5; behaves no cases
  com.vmware.specialists.dns.utilities/MsDnsAddRemoveHost: loads pass on Python 3.14.5; behaves no cases
  com.vmware.specialists.dns.utilities/MsDnsAdddRemoveEntry: loads pass on Python 3.14.5; behaves no cases

record written: qualify-dns-without-pykerberos.json
```

Loading proves the imports resolve, not that CredSSP works: pywinrm imports its CredSSP support only when that transport is built. A throwaway action that built the CredSSP and NTLM transports on the same package set returned both, and the reference estate's environment was then rebuilt on `python:3.14` without `pykerberos`, reaching `UP_TO_DATE` in 17 seconds with its memory limit and its four actions kept.
