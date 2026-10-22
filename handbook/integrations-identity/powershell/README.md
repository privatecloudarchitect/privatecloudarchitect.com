# A scheduled PowerCLI job off Windows pass-through, one step at a time

Companion to field note 16
([privatecloudarchitect.com/notes/powercli-sign-in-without-a-password](https://privatecloudarchitect.com/notes/powercli-sign-in-without-a-password)):
five PowerShell scripts and an example job, one for each step of the note's stair. A job that signs in to vCenter 8 as
the Windows account running it is found (Today), given an account and a role of its own with its password stored once
(Crawl), moved to a vault before the 9.x upgrade (Walk), and, on VCF 9.1 with VCF single sign-on, signed in with an API
client's token from the same vault (Run). Stop at the step your platform reaches: the note's fork says which.

The scripts run on Windows PowerShell 5.1 and on PowerShell 7 (their syntax is checked against both); the Run step
needs VCF PowerCLI 9.1 or later, which runs on PowerShell 7. No script takes a password or a token as an argument, and
none prints one: they take file paths and secret names, and print account names, counts and file lines.

**One exit contract.** Like every identity companion, each script exits 0 when there is nothing for a person to act on,
3 when a read failed or a result is undetermined (an error a script did not expect is one, never a finding), and 5 on a
usage error. The other codes are each script's own, in its table below. The scripts read their own arguments rather
than declaring PowerShell parameters, because `pwsh -File` binds declared parameters before any line runs and ends a
missing value with exit 1, which a scheduler would read as a finding.

| Step | Plate | Script | What it does |
|---|---|---|---|
| Today | 01 | `Find-PassThroughJob.ps1` | Lists each job that signs in by pass-through, with a password typed in its script or its task, or through PowerCLI's credential store. Reads only. |
| Crawl | 02 | `New-JobCredential.ps1` | Stores one job's vCenter credential once, with `Export-Clixml`, for the Windows account that runs the job. Windows only. |
| Crawl | 02 | `New-JobRole.ps1` | One custom role and one grant of it on one object, for the job's account. Plan by default. |
| Crawl, Walk, Run | 02, 03, 05 | `Invoke-VcJob.ps1` | The job wrapper the scheduled task runs: the credential from a file or a vault, the sign-in, the session check, the job, the disconnect. |
| Walk | 03 | `Test-WalkReadiness.ps1` | The job host's pre-flight for the 9.x upgrade. Reads only. |
| any | | `Example-Job.ps1` | A job: it prints how many VMs its identity can see. Replace its body with your own. |

## Today: find the jobs

On each Windows host that runs PowerCLI jobs, as an account that can read its scheduled tasks:

```
pwsh -NoProfile -File .\Find-PassThroughJob.ps1
powershell -NoProfile -File .\Find-PassThroughJob.ps1          # Windows PowerShell 5.1
pwsh -NoProfile -File ./Find-PassThroughJob.ps1 -Path <folder of job scripts> -Recurse
```

On the test fixtures, from this folder:

```
credential-store     ./tests/fixtures/jobs/credential-store.ps1:2  New-VICredentialStoreItem
credential-store     ./tests/fixtures/jobs/credential-store.ps1:3  Connect-VIServer -SaveCredentials
pass-through         ./tests/fixtures/jobs/passthrough.ps1:2  Connect-VIServer names no credential
password-in-script   ./tests/fixtures/jobs/typed-password.ps1:2  Connect-VIServer -Password, given as text
read 5 source(s): 4 to move, 0 not read or not judged
```

Exit codes:

```
  0 nothing to move: every Connect-VIServer found names a credential
  1 at least one job to move is listed (pass-through, a password in a script or a task, the credential store)
  3 a task or a script could not be read or parsed, or a call was not judged, and nothing to move was found
  5 a usage error: an unknown option, a missing value, a path that does not exist, or no -Path where there is no Task Scheduler
```

## Crawl: an account, a role and a password stored once (vCenter 8, nothing new installed)

Store the job's credential once, as the Windows account its task runs as, on the host that runs the task. With
`-TaskName` the script compares the two accounts first:

```
pwsh -NoProfile -File .\New-JobCredential.ps1 -Path C:\jobs\backup.credential.xml -UserName <the job's vCenter account> -TaskName backup
```

```
  0 the credential was written and read back
  2 refused before any write: not Windows, the file exists and -Force was not given, or the task runs as another account
  3 the write or the read-back failed, the task could not be read, or no credential was entered
  5 a usage error: an unknown option, a missing value, or -Path or -UserName not given
```

Give the job's account a role of its own on the one object it works on. Connect as an administrator first, in the same
session, then plan, then make:

```
Connect-VIServer -Server <vCenter>
& ./New-JobRole.ps1 -Server <vCenter> -Role job-backup -Privilege <privilege id>,<privilege id> -Principal <DOMAIN\account> -Entity <object name>
& ./New-JobRole.ps1 -Server <vCenter> -Role job-backup -Privilege <privilege id>,<privilege id> -Principal <DOMAIN\account> -Entity <object name> -Execute
```

```
  0 the plan printed, or the run held on read-back (a re-run that found both writes nothing and exits 0)
  1 the run did not hold: a write was refused, or the read-back is not the role and the grant asked for
  2 refused before any write: the account matches no principal or more than one, the role exists with other privileges, the account holds another role on the object, the object name matches no object or more than one, or a privilege id is not known
  3 a read failed, or an error the script did not expect
  5 a usage error: an unknown option, a missing value, a required option not given, an account not named with its domain, or no open connection to -Server
```

The scheduled task's action, registered with the task's Windows password stored:

```
pwsh -NoProfile -File C:\jobs\Invoke-VcJob.ps1 -Server <vCenter> -Job C:\jobs\backup.ps1 -CredentialFile C:\jobs\backup.credential.xml
```

`Invoke-VcJob.ps1` exits:

```
  0 signed in, the session named its user, the job returned without an error, and the session was disconnected
  1 the job itself threw an error (the session was still disconnected)
  2 refused before signing in: a DPAPI file (-CredentialFile or -VaultPasswordFile) named off Windows, where it is not encrypted
  3 the credential or the token could not be read, the sign-in was refused, the session named no user, the disconnect failed, or an error the script did not expect
  5 a usage error: an unknown option, a missing value, no credential source or more than one, or a file that does not exist
```

## Walk: the password in your vault, before the 9.x upgrade (vCenter 8.0 Update 3)

Put the job's credential in the vault your organization runs, through PowerShell SecretManagement and that vault's
extension, then point the task at it:

```
pwsh -NoProfile -File C:\jobs\Invoke-VcJob.ps1 -Server <vCenter> -Job C:\jobs\backup.ps1 -Vault <vault> -SecretName backup-credential
```

With SecretStore as the vault on Windows, add `-VaultPasswordFile <file>`: the store's own password, written once with
`Export-Clixml` by the task's account, unlocks the store before the secret is read.

The job host's pre-flight:

```
pwsh -NoProfile -File .\Test-WalkReadiness.ps1 -Vault <vault> -SecretName backup-credential,report-credential
```

```
  0 ready: every check read and none found anything to do
  1 something to do is listed (an older PowerShell, no VCF.PowerCLI, a secret not in the vault, a job still to move)
  3 a check could not be read (the vault, a task or a script, or the jobs where there is no Task Scheduler and no -Path), and nothing to do was found
  5 a usage error: an unknown option, a missing value, -Vault without -SecretName or the reverse, or a path that does not exist
```

The vCenter's side is read by hand. In the vSphere Client, Administration ▸ Single Sign On ▸ Configuration ▸ Identity
Provider ▸ Identity Sources lists the identity sources, and none should be of the type Active Directory (Integrated
Windows Authentication); Administration ▸ Single Sign On ▸ Configuration ▸ Identity Provider ▸ Active Directory Domain
shows whether the vCenter is still joined to a domain, and on the appliance, as root,
`/opt/likewise/bin/domainjoin-cli query` reads the join.

## Run: an API client's token in the same vault (VCF 9.1 with VCF single sign-on)

Make the job's API client with `api_client.py` in the folder above this one, put its token in the vault, and point the
task at it:

```
Set-Secret -Vault <vault> -Name backup-token -SecureStringSecret (Read-Host -AsSecureString)
pwsh -NoProfile -File C:\jobs\Invoke-VcJob.ps1 -Server <vCenter> -Job C:\jobs\backup.ps1 -Vault <vault> -TokenSecretName backup-token
```

## What ran

Every script here is parse-checked with PowerShell's own parser, analysed with PSScriptAnalyzer (its syntax held to
both Windows PowerShell 5.1 and PowerShell 7) and unit-tested with Pester, with every PowerCLI, SecretManagement and
Task Scheduler command replaced by a stand-in. `New-JobRole.ps1` has also run against vCenter 9.1.1, not vCenter 8,
for a throwaway local account and a throwaway folder: its plan wrote nothing, `-Execute` made the role and its grant
and read both back, and a second `-Execute` wrote nothing. It resolves the account to exactly one principal before
any write, so a name that matches several principals is refused before a role is made. The others have not run
against a vCenter: `Find-PassThroughJob.ps1`, `New-JobCredential.ps1`, `Invoke-VcJob.ps1` and
`Test-WalkReadiness.ps1`. DPAPI and Windows pass-through need a Windows host, and the reference lab has no vCenter 8.

## Tests

The scripts' behaviour is held by Pester tests under `tests/`, with every PowerCLI, SecretManagement and Task
Scheduler command replaced by a stand-in (`tests/Stubs.ps1`), so they reach no vCenter and no vault. With Pester 5 or
later and PSScriptAnalyzer installed for your account:

```
Install-Module Pester -Scope CurrentUser -MinimumVersion 5.5.0 -SkipPublisherCheck
Install-Module PSScriptAnalyzer -Scope CurrentUser
Invoke-Pester -Path ./tests
Get-ChildItem -Filter *.ps1 | ForEach-Object { Invoke-ScriptAnalyzer -Path $_.FullName -Settings ./PSScriptAnalyzerSettings.psd1 }
```
