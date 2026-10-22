<#
.SYNOPSIS
Test-WalkReadiness.ps1: read whether a job host is ready for the Walk step and the 9.x upgrade.

.DESCRIPTION
The Walk step's pre-flight on the host that runs the jobs. It reads, and changes nothing:

  PowerShell   the jobs' PowerShell is 7.0.13 or later, the minimum VCF PowerCLI 9.1.1 supports
  PowerCLI     the VCF.PowerCLI module is installed
  vault        each job's secret named with -SecretName is in the vault named with -Vault (Get-SecretInfo: the
               secret's name only, never its value)
  jobs         no job still signs in by pass-through, with a password in its script or in its task, or through
               PowerCLI's credential store: Find-PassThroughJob.ps1's reading of -Path, or on Windows with no -Path,
               of the host's scheduled tasks

The vCenter's side is read by hand, in the vSphere Client or on the appliance: no identity source of the type
Active Directory (Integrated Windows Authentication), and the vCenter no longer joined to the domain.

Usage:
  pwsh -NoProfile -File ./Test-WalkReadiness.ps1 [-Vault <vault> -SecretName <name>[,<name>...]] [-Path <file or folder>[,...]] [-Recurse]

Exit codes:
  0 ready: every check read and none found anything to do
  1 something to do is listed (an older PowerShell, no VCF.PowerCLI, a secret not in the vault, a job still to move)
  3 a check could not be read (the vault, a task or a script, or the jobs where there is no Task Scheduler and no -Path), and nothing to do was found
  5 a usage error: an unknown option, a missing value, -Vault without -SecretName or the reverse, or a path that does not exist
#>

# No param block: the script reads its own arguments, so every usage error exits 5.

. (Join-Path -Path $PSScriptRoot -ChildPath 'Find-PassThroughJob.ps1')

function Get-StairPowerShell {
    return [pscustomobject]@{ Edition = [string]$PSVersionTable.PSEdition; Version = [version]$PSVersionTable.PSVersion.ToString().Split('-')[0] }
}

function Test-StairModule {
    param([string]$Name)
    return [bool](Get-Module -ListAvailable -Name $Name)
}

function Invoke-TestWalkReadiness {
    param([object[]]$Argv = @())
    try {
        $o = Read-StairArgument -Argv $Argv -Value @('Vault', 'SecretName', 'Path') -Switch @('Recurse')
        if ($o.ContainsKey('Vault') -ne $o.ContainsKey('SecretName')) { throw '-Vault and -SecretName go together' }
        $paths = @()
        if ($o.ContainsKey('Path')) {
            $paths = @($o['Path'] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            foreach ($p in $paths) { if (-not (Test-Path -LiteralPath $p)) { throw "the path '$p' does not exist" } }
        }
        if ($o.ContainsKey('Recurse') -and -not $o.ContainsKey('Path')) { throw '-Recurse goes with -Path' }
    } catch {
        Write-StairError "usage: $($_.Exception.Message)"
        Write-StairError 'usage: Test-WalkReadiness.ps1 [-Vault <vault> -SecretName <name>[,...]] [-Path <file or folder>[,...]] [-Recurse]'
        return 5
    }
    $todo = 0
    $unread = 0
    try {
        $ps = Get-StairPowerShell
        if ($ps.Edition -eq 'Desktop' -or $ps.Version -lt [version]'7.0.13') {
            Write-StairLine "to do     PowerShell $($ps.Version) ($($ps.Edition)): move the jobs to PowerShell 7.0.13 or later"
            $todo += 1
        } else {
            Write-StairLine "ready     PowerShell $($ps.Version)"
        }
        if (Test-StairModule -Name 'VCF.PowerCLI') {
            Write-StairLine 'ready     VCF.PowerCLI is installed'
        } else {
            Write-StairLine 'to do     VCF.PowerCLI is not installed'
            $todo += 1
        }
    } catch {
        Write-StairLine "not read  PowerShell and PowerCLI: $($_.Exception.Message)"
        $unread += 1
    }
    if ($o.ContainsKey('Vault')) {
        foreach ($name in @($o['SecretName'] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
            try {
                $info = @(Get-SecretInfo -Vault $o['Vault'] -Name $name -ErrorAction Stop)
                if ($info.Count -gt 0) {
                    Write-StairLine "ready     the secret $name is in the vault $($o['Vault'])"
                } else {
                    Write-StairLine "to do     the secret $name is not in the vault $($o['Vault'])"
                    $todo += 1
                }
            } catch {
                Write-StairLine "not read  the vault $($o['Vault']): $($_.Exception.Message)"
                $unread += 1
            }
        }
    }
    try {
        $sources = $null
        if ($paths.Count -gt 0) {
            $sources = @(Get-StairPathScript -Path $paths -Recurse ([bool]$o['Recurse']) | ForEach-Object {
                    [pscustomobject]@{ Task = $null; Source = $_; Findings = @(Read-StairScript -Path $_) } })
        } elseif (Test-StairTaskScheduler) {
            $sources = @(Read-StairTask)
        }
        if ($null -eq $sources) {
            Write-StairLine 'not read  the jobs: this system has no Task Scheduler; give -Path with the job scripts'
            $unread += 1
        } else {
            $move = @($sources | ForEach-Object { $_.Findings } | Where-Object { $_.Kind -notin @('unread', 'not-judged') })
            $notJudged = @($sources | ForEach-Object { $_.Findings } | Where-Object { $_.Kind -in @('unread', 'not-judged') })
            if ($move.Count -gt 0) {
                Write-StairLine "to do     $($move.Count) job sign-in(s) to move: run Find-PassThroughJob.ps1 for the list"
                $todo += 1
            }
            if ($notJudged.Count -gt 0) {
                Write-StairLine "not read  $($notJudged.Count) script(s) or call(s) not read or not judged: run Find-PassThroughJob.ps1 for the list"
                $unread += 1
            }
            if ($move.Count -eq 0 -and $notJudged.Count -eq 0) {
                Write-StairLine "ready     no job signs in by pass-through, a typed password or the credential store ($($sources.Count) source(s) read)"
            }
        }
    } catch {
        Write-StairLine "not read  the jobs: $($_.Exception.Message)"
        $unread += 1
    }
    if ($todo -gt 0) { return 1 }
    if ($unread -gt 0) { return 3 }
    return 0
}

if ($MyInvocation.InvocationName -ne '.') { exit (Invoke-TestWalkReadiness -Argv $args) }
