<#
.SYNOPSIS
Invoke-VcJob.ps1: run one PowerCLI job on its own identity, never typed: sign in, check the session, run the job,
disconnect.

.DESCRIPTION
The job wrapper of field note 16's stair. The scheduled task runs this script; the job is a script of yours that takes
the connection as -Server. One credential source, by stage:

  Crawl  -CredentialFile <file>                 the job account's credential, written once by New-JobCredential.ps1
                                                (Export-Clixml: DPAPI, so Windows only)
  Walk   -Vault <vault> -SecretName <name>      the job account's credential (a PSCredential) from a SecretManagement
                                                vault
  Run    -Vault <vault> -TokenSecretName <name> an API client's token (a SecureString) from the same vault, on a vCenter
                                                that authenticates through VCF single sign-on (VCF PowerCLI 9.1 or later)

With -VaultPasswordFile <file> it first unlocks a SecretStore vault with the store's password read from a DPAPI file,
Microsoft's pattern for unattended SecretStore (Windows only); another vault extension unlocks its own way.

Then, in this order: Connect-VIServer -NotDefault with -Credential or -VcfApiToken; the session's user read from the
SessionManager, and the run stopped if the session names no user (an empty answer from a lost session is not an empty
inventory); the job, run as  & <job> -Server <connection>, its output passed through; and Disconnect-VIServer -Force in
a finally block, because closing the PowerShell process does not close the server's session. It never prints the
credential, the token or the connection object, only the account the session reads and the job's own output.

Usage:
  pwsh -NoProfile -File ./Invoke-VcJob.ps1 -Server <vCenter> -Job <job.ps1> -CredentialFile <file>
  pwsh -NoProfile -File ./Invoke-VcJob.ps1 -Server <vCenter> -Job <job.ps1> -Vault <vault> -SecretName <name> [-VaultPasswordFile <file>]
  pwsh -NoProfile -File ./Invoke-VcJob.ps1 -Server <vCenter> -Job <job.ps1> -Vault <vault> -TokenSecretName <name> [-VaultPasswordFile <file>]

Exit codes:
  0 signed in, the session named its user, the job returned without an error, and the session was disconnected
  1 the job itself threw an error (the session was still disconnected)
  2 refused before signing in: a DPAPI file (-CredentialFile or -VaultPasswordFile) named off Windows, where it is not encrypted
  3 the credential or the token could not be read, the sign-in was refused, the session named no user, the disconnect failed, or an error the script did not expect
  5 a usage error: an unknown option, a missing value, no credential source or more than one, or a file that does not exist
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

function Get-StairFirstLine {
    param([string]$Text)
    return (([string]$Text) -split "`r?`n")[0]
}

function Invoke-VcJobMain {
    param([object[]]$Argv = @())
    try {
        $o = Read-StairArgument -Argv $Argv -Value @('Server', 'Job', 'CredentialFile', 'Vault', 'SecretName', 'TokenSecretName', 'VaultPasswordFile')
        foreach ($required in 'Server', 'Job') { if (-not $o.ContainsKey($required)) { throw "-$required is required" } }
        $sources = @('CredentialFile', 'SecretName', 'TokenSecretName' | Where-Object { $o.ContainsKey($_) })
        if ($sources.Count -ne 1) { throw 'give exactly one of -CredentialFile, -SecretName or -TokenSecretName' }
        $mode = $sources[0]
        if ($mode -eq 'CredentialFile' -and ($o.ContainsKey('Vault') -or $o.ContainsKey('VaultPasswordFile'))) {
            throw '-CredentialFile takes no vault'
        }
        if ($mode -ne 'CredentialFile' -and -not $o.ContainsKey('Vault')) { throw "-$mode needs -Vault" }
        foreach ($file in 'Job', 'CredentialFile', 'VaultPasswordFile') {
            if ($o.ContainsKey($file) -and -not (Test-Path -LiteralPath $o[$file] -PathType Leaf)) {
                throw "-$file names '$($o[$file])', which does not exist"
            }
        }
    } catch {
        Write-StairError "usage: $($_.Exception.Message)"
        Write-StairError 'usage: Invoke-VcJob.ps1 -Server <vCenter> -Job <job.ps1> (-CredentialFile <file> | -Vault <vault> -SecretName <name> | -Vault <vault> -TokenSecretName <name>) [-VaultPasswordFile <file>]'
        return 5
    }
    if (($o.ContainsKey('CredentialFile') -or $o.ContainsKey('VaultPasswordFile')) -and -not (Test-StairWindow)) {
        Write-StairError 'REFUSED: off Windows a file Export-Clixml wrote is not encrypted; keep the credential in a vault instead'
        return 2
    }
    $credential = $null
    $token = $null
    try {
        if ($mode -eq 'CredentialFile') {
            $credential = Import-Clixml -LiteralPath $o['CredentialFile'] -ErrorAction Stop
            if ($credential -isnot [System.Management.Automation.PSCredential]) { throw 'the file holds no credential' }
        } else {
            if ($o.ContainsKey('VaultPasswordFile')) {
                $vaultPassword = Import-Clixml -LiteralPath $o['VaultPasswordFile'] -ErrorAction Stop
                if ($vaultPassword -isnot [System.Security.SecureString]) { throw 'the vault password file holds no SecureString' }
                Unlock-SecretStore -Password $vaultPassword -ErrorAction Stop
                $vaultPassword = $null
            }
            if ($mode -eq 'SecretName') {
                $credential = Get-Secret -Vault $o['Vault'] -Name $o['SecretName'] -ErrorAction Stop
                if ($credential -isnot [System.Management.Automation.PSCredential]) { throw "the secret $($o['SecretName']) is not a credential" }
            } else {
                $token = Get-Secret -Vault $o['Vault'] -Name $o['TokenSecretName'] -ErrorAction Stop
                if ($token -isnot [System.Security.SecureString]) { throw "the secret $($o['TokenSecretName']) is not a SecureString" }
            }
        }
    } catch {
        Write-StairError "NOT READ: the credential: $(Get-StairFirstLine $_.Exception.Message)"
        return 3
    }
    $vc = $null
    try {
        if ($token) {
            $vc = Connect-VIServer -Server $o['Server'] -VcfApiToken $token -NotDefault -ErrorAction Stop
        } else {
            $vc = Connect-VIServer -Server $o['Server'] -Credential $credential -NotDefault -ErrorAction Stop
        }
    } catch {
        Write-StairError "NOT SIGNED IN: $(Get-StairFirstLine $_.Exception.Message)"
        return 3
    } finally {
        $credential = $null
        $token = $null
    }
    $code = 0
    try {
        try {
            $user = [string](Get-View SessionManager -Server $vc -ErrorAction Stop).CurrentSession.UserName
        } catch {
            $user = ''
        }
        if (-not $user) {
            Write-StairError 'NOT READ: the session names no user, so its answers cannot be trusted; the job did not run'
            $code = 3
        } else {
            Write-StairLine "signed in as $user"
            try {
                & $o['Job'] -Server $vc | ForEach-Object { Write-StairLine ([string]$_) }
            } catch {
                Write-StairError "JOB FAILED: $(Get-StairFirstLine $_.Exception.Message)"
                $code = 1
            }
        }
    } finally {
        try {
            Disconnect-VIServer -Server $vc -Force -Confirm:$false -ErrorAction Stop
            Write-StairLine 'disconnected'
        } catch {
            Write-StairError "NOT DISCONNECTED: $(Get-StairFirstLine $_.Exception.Message)"
            if ($code -eq 0) { $code = 3 }
        }
    }
    return $code
}

if ($MyInvocation.InvocationName -ne '.') { exit (Invoke-VcJobMain -Argv $args) }
