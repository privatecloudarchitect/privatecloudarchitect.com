<#
.SYNOPSIS
New-JobCredential.ps1: store one job's vCenter credential once, readable only by the account that runs the job.

.DESCRIPTION
The Crawl step of field note 16's stair, on vCenter 8 with nothing new installed. Run it once, as the Windows account
the job's scheduled task runs as, on the host that runs the task. It prompts for the job's vCenter password
(Get-Credential, with the user name you give), writes the credential with Export-Clixml, which on Windows encrypts it
with the Windows Data Protection API so that only that account on that computer can read it back, then reads the file
back with Import-Clixml and compares the user name and the password's length, never its value. With -TaskName it first
compares the account running it with the task's own account and refuses a difference.

It refuses to run off Windows, where Export-Clixml writes a credential as plain text. It never takes a password as an
argument and never prints one.

Usage:
  pwsh -NoProfile -File .\New-JobCredential.ps1 -Path <file> -UserName <vCenter account> [-TaskName <task>] [-Force]
  powershell -NoProfile -File .\New-JobCredential.ps1 ...                  # the same on Windows PowerShell 5.1

Exit codes:
  0 the credential was written and read back
  2 refused before any write: not Windows, the file exists and -Force was not given, or the task runs as another account
  3 the write or the read-back failed, the task could not be read, or no credential was entered
  5 a usage error: an unknown option, a missing value, or -Path or -UserName not given
#>

# No param block: the script reads its own arguments, so every usage error exits 5.

function Write-StairLine {
    param([string]$Text)
    [Console]::Out.WriteLine($Text)
}

function Write-StairError {
    param([string]$Text)
    [Console]::Error.WriteLine($Text)
}

function Read-StairArgument {
    param([object[]]$Argv, [string[]]$Value = @(), [string[]]$Switch = @())
    $options = @{}
    $i = 0
    while ($i -lt $Argv.Count) {
        $token = [string]$Argv[$i]
        if (-not $token.StartsWith('-') -or $token.Length -lt 2) { throw "unexpected argument '$token'" }
        $name = $token.Substring(1)
        $key = @($Value + $Switch | Where-Object { $_ -ieq $name })
        if ($key.Count -ne 1) { throw "unknown option '$token'" }
        $key = $key[0]
        if ($options.ContainsKey($key)) { throw "-$key is given twice" }
        if ($Switch -contains $key) {
            $options[$key] = $true
            $i += 1
            continue
        }
        if ($i + 1 -ge $Argv.Count) { throw "-$key needs a value" }
        $next = $Argv[$i + 1]
        if ($next -is [array]) { $next = ($next | ForEach-Object { [string]$_ }) -join ',' }
        $next = [string]$next
        if ($next.StartsWith('-') -or $next -eq '') { throw "-$key needs a value" }
        $options[$key] = $next
        $i += 2
    }
    $options
}

function Test-StairWindow {
    if ($PSVersionTable.PSEdition -eq 'Desktop') { return $true }
    return [bool](Get-Variable -Name IsWindows -ValueOnly -ErrorAction SilentlyContinue)
}

function Get-StairCurrentAccount {
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
}

function Get-StairComputerName {
    return [System.Environment]::MachineName
}

function Test-StairSameAccount {
    # DOMAIN\user and user compare by the user part when either side names no domain
    param([string]$A, [string]$B)
    if ($A -ieq $B) { return $true }
    if ($A -notmatch '\\' -or $B -notmatch '\\') { return ($A -split '\\')[-1] -ieq ($B -split '\\')[-1] }
    return $false
}

function Invoke-NewJobCredential {
    param([object[]]$Argv = @())
    try {
        $o = Read-StairArgument -Argv $Argv -Value @('Path', 'UserName', 'TaskName') -Switch @('Force')
        foreach ($required in 'Path', 'UserName') { if (-not $o.ContainsKey($required)) { throw "-$required is required" } }
    } catch {
        Write-StairError "usage: $($_.Exception.Message)"
        Write-StairError 'usage: New-JobCredential.ps1 -Path <file> -UserName <vCenter account> [-TaskName <task>] [-Force]'
        return 5
    }
    try {
        if (-not (Test-StairWindow)) {
            Write-StairError 'REFUSED: off Windows, Export-Clixml writes a credential as plain text; run this on the Windows host that runs the job'
            return 2
        }
        if ((Test-Path -LiteralPath $o['Path']) -and -not $o['Force']) {
            Write-StairError "REFUSED: $($o['Path']) exists; give -Force to replace it"
            return 2
        }
        $account = Get-StairCurrentAccount
        if ($o.ContainsKey('TaskName')) {
            $task = Get-ScheduledTask -TaskName $o['TaskName'] -ErrorAction Stop
            $runsAs = [string]$task.Principal.UserId
            if (-not (Test-StairSameAccount -A $account -B $runsAs)) {
                Write-StairError "REFUSED: the task runs as $runsAs and this is $account; only the account that writes the file can read it"
                return 2
            }
        }
        $credential = Get-Credential -UserName $o['UserName'] -Message 'The job''s vCenter password, stored once for this Windows account on this computer'
        if (-not $credential) {
            Write-StairError 'NOT WRITTEN: no credential was entered'
            return 3
        }
        $credential | Export-Clixml -LiteralPath $o['Path'] -Force:([bool]$o['Force']) -ErrorAction Stop
        $back = Import-Clixml -LiteralPath $o['Path'] -ErrorAction Stop
        if ($back -isnot [System.Management.Automation.PSCredential] -or $back.UserName -ne $credential.UserName -or
            $back.Password.Length -ne $credential.Password.Length) {
            Write-StairError "NOT HELD: $($o['Path']) did not read back as the credential written"
            return 3
        }
        Write-StairLine "written: $($o['Path']) for $($credential.UserName)"
        Write-StairLine "readable only by $account on $(Get-StairComputerName)"
        return 0
    } catch {
        Write-StairError "NOT WRITTEN: $($_.Exception.Message)"
        return 3
    }
}

if ($MyInvocation.InvocationName -ne '.') { exit (Invoke-NewJobCredential -Argv $args) }
