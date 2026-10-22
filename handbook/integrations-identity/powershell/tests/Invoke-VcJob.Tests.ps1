# Invoke-VcJob.ps1, with every PowerCLI and SecretManagement call mocked: the credential's three sources, the session
# check, the job, the disconnect on every path after a sign-in, and nothing secret in what it prints.
BeforeAll {
    . (Join-Path $PSScriptRoot 'Stubs.ps1')
    . (Join-Path $PSScriptRoot '..' 'Invoke-VcJob.ps1')
    $script:Job = Join-Path $TestDrive 'job.ps1'
    Set-Content -LiteralPath $script:Job -Value 'param($Server) "ran on $($Server.Name)"'
    $script:Thrower = Join-Path $TestDrive 'throws.ps1'
    Set-Content -LiteralPath $script:Thrower -Value 'param($Server) throw "the job failed on purpose"'
    $script:CredFile = Join-Path $TestDrive 'job.credential.xml'
    Set-Content -LiteralPath $script:CredFile -Value 'stand-in'
    $script:VaultPw = Join-Path $TestDrive 'vault.password.xml'
    Set-Content -LiteralPath $script:VaultPw -Value 'stand-in'
}

Describe 'Invoke-VcJob.ps1' {
    BeforeEach {
        $script:Out = [System.Collections.Generic.List[string]]::new()
        $script:Err = [System.Collections.Generic.List[string]]::new()
        Mock Write-StairLine { $script:Out.Add($Text) }
        Mock Write-StairError { $script:Err.Add($Text) }
        Mock Test-StairWindow { $true }
        $script:JobCredential = [System.Management.Automation.PSCredential]::new('svc-backup@example.net', (New-StairSecureString 'made-up-password-value'))
        $script:JobToken = New-StairSecureString 'made-up-token-value'
        Mock Import-Clixml { $script:JobCredential }
        Mock Get-Secret { if ($Name -like '*token*') { $script:JobToken } else { $script:JobCredential } }
        Mock Unlock-SecretStore { }
        Mock Connect-VIServer { [pscustomobject]@{ Name = 'vcenter.example.net'; User = 'job'; SessionSecret = 'made-up-session-secret' } }
        Mock Get-View { [pscustomobject]@{ CurrentSession = [pscustomobject]@{ UserName = 'EXAMPLE\svc-backup' } } }
        Mock Disconnect-VIServer { }
    }

    It 'signs in from a DPAPI file with -Credential and -NotDefault, checks the session, runs the job and disconnects, exit 0' {
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-CredentialFile', $script:CredFile) | Should -Be 0
        Should -Invoke Connect-VIServer -Times 1 -Exactly -ParameterFilter { $Credential -and -not $VcfApiToken -and $NotDefault }
        Should -Invoke Disconnect-VIServer -Times 1 -Exactly -ParameterFilter { $Force }
        $script:Out | Should -Contain 'signed in as EXAMPLE\svc-backup'
        $script:Out | Should -Contain 'ran on vcenter.example.net'
        $script:Out | Should -Contain 'disconnected'
    }

    It 'reads a PSCredential from the vault with -SecretName' {
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-Vault', 'jobs', '-SecretName', 'backup-credential') | Should -Be 0
        Should -Invoke Get-Secret -Times 1 -Exactly -ParameterFilter { $Vault -eq 'jobs' -and $Name -eq 'backup-credential' }
        Should -Invoke Connect-VIServer -Times 1 -Exactly -ParameterFilter { $Credential -and -not $VcfApiToken }
    }

    It 'signs in with the API client''s token from the vault as a SecureString, never with -Credential' {
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-Vault', 'jobs', '-TokenSecretName', 'backup-token') | Should -Be 0
        Should -Invoke Connect-VIServer -Times 1 -Exactly -ParameterFilter { $VcfApiToken -is [System.Security.SecureString] -and -not $Credential -and $NotDefault }
    }

    It 'unlocks SecretStore with the password from a DPAPI file before it reads the secret, with -VaultPasswordFile' {
        Mock Import-Clixml { New-StairSecureString 'made-up-vault-password' }
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-Vault', 'jobs', '-TokenSecretName', 'backup-token', '-VaultPasswordFile', $script:VaultPw) | Should -Be 0
        Should -Invoke Unlock-SecretStore -Times 1 -Exactly -ParameterFilter { $Password -is [System.Security.SecureString] }
    }

    It 'stops before the job when the session names no user, exit 3, and still disconnects' {
        Mock Get-View { [pscustomobject]@{ CurrentSession = $null } }
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-CredentialFile', $script:CredFile) | Should -Be 3
        $script:Out | Should -Not -Contain 'ran on vcenter.example.net'
        Should -Invoke Disconnect-VIServer -Times 1 -Exactly
    }

    It 'exits 1 when the job throws, and still disconnects' {
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Thrower, '-CredentialFile', $script:CredFile) | Should -Be 1
        Should -Invoke Disconnect-VIServer -Times 1 -Exactly
    }

    It 'exits 3 when the sign-in is refused, and has no session to disconnect' {
        Mock Connect-VIServer { throw 'Failed to retrieve SAML bearer token: Failed to issue OAuth2 access token.' }
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-Vault', 'jobs', '-TokenSecretName', 'backup-token') | Should -Be 3
        Should -Invoke Disconnect-VIServer -Times 0 -Exactly
    }

    It 'exits 3 when the credential cannot be read or is not the type asked for' {
        Mock Get-Secret { throw 'The secret backup-token was not found.' }
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-Vault', 'jobs', '-TokenSecretName', 'backup-token') | Should -Be 3
        Mock Get-Secret { 'a plain string' }
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-Vault', 'jobs', '-SecretName', 'backup-credential') | Should -Be 3
        Should -Invoke Connect-VIServer -Times 0 -Exactly
    }

    It 'exits 3 when the disconnect fails after a job that held' {
        Mock Disconnect-VIServer { throw 'The session is not authenticated.' }
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-CredentialFile', $script:CredFile) | Should -Be 3
    }

    It 'refuses a DPAPI file off Windows before reading it, exit 2' {
        Mock Test-StairWindow { $false }
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-CredentialFile', $script:CredFile) | Should -Be 2
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-Vault', 'jobs', '-SecretName', 'x', '-VaultPasswordFile', $script:VaultPw) | Should -Be 2
        Should -Invoke Import-Clixml -Times 0 -Exactly
        Should -Invoke Connect-VIServer -Times 0 -Exactly
    }

    It 'prints no password, no token and no session secret' {
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-Vault', 'jobs', '-TokenSecretName', 'backup-token') | Out-Null
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-CredentialFile', $script:CredFile) | Out-Null
        $all = ($script:Out + $script:Err) -join "`n"
        $all | Should -Not -Match 'made-up-password-value'
        $all | Should -Not -Match 'made-up-token-value'
        $all | Should -Not -Match 'made-up-session-secret'
        $all | Should -Not -Match 'SessionSecret'
    }

    It 'exits 5 for an unknown option, a missing value, no credential source or two, and a file that does not exist' {
        Invoke-VcJobMain -Argv @('-NoSuchOptionInAnyCompanion') | Should -Be 5
        Invoke-VcJobMain -Argv @('-Server') | Should -Be 5
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job) | Should -Be 5
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-CredentialFile', $script:CredFile, '-Vault', 'jobs', '-SecretName', 'x') | Should -Be 5
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', $script:Job, '-SecretName', 'x') | Should -Be 5
        Invoke-VcJobMain -Argv @('-Server', 'vcenter.example.net', '-Job', (Join-Path $TestDrive 'nowhere.ps1'), '-CredentialFile', $script:CredFile) | Should -Be 5
        Should -Invoke Connect-VIServer -Times 0 -Exactly
    }
}
