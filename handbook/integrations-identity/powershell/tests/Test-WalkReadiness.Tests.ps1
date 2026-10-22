# Test-WalkReadiness.ps1: the job host's four reads, each mocked to ready and to something to do.
BeforeAll {
    . (Join-Path $PSScriptRoot 'Stubs.ps1')
    . (Join-Path $PSScriptRoot '..' 'Test-WalkReadiness.ps1')
    $script:Fixtures = Join-Path $PSScriptRoot 'fixtures'
}

Describe 'Test-WalkReadiness.ps1' {
    BeforeEach {
        $script:Out = [System.Collections.Generic.List[string]]::new()
        $script:Err = [System.Collections.Generic.List[string]]::new()
        Mock Write-StairLine { $script:Out.Add($Text) }
        Mock Write-StairError { $script:Err.Add($Text) }
        Mock Get-StairPowerShell { [pscustomobject]@{ Edition = 'Core'; Version = [version]'7.4.6' } }
        Mock Test-StairModule { $true }
        Mock Get-SecretInfo { @([pscustomobject]@{ Name = $Name; VaultName = $Vault }) }
        Mock Get-Secret { throw 'the readiness check must never read a secret''s value' }
        Mock Test-StairTaskScheduler { $false }
    }

    It 'is ready, exit 0, when PowerShell, VCF.PowerCLI, the vault''s secrets and the jobs all read ready' {
        Invoke-TestWalkReadiness -Argv @('-Vault', 'jobs', '-SecretName', 'backup,report', '-Path', (Join-Path $script:Fixtures 'clean')) | Should -Be 0
        Should -Invoke Get-SecretInfo -Times 2 -Exactly
        Should -Invoke Get-Secret -Times 0 -Exactly
    }

    It 'lists Windows PowerShell 5.1 or a PowerShell older than 7.0.13 as something to do, exit 1' {
        Mock Get-StairPowerShell { [pscustomobject]@{ Edition = 'Desktop'; Version = [version]'5.1.20348' } }
        Invoke-TestWalkReadiness -Argv @('-Path', (Join-Path $script:Fixtures 'clean')) | Should -Be 1
        Mock Get-StairPowerShell { [pscustomobject]@{ Edition = 'Core'; Version = [version]'7.0.12' } }
        Invoke-TestWalkReadiness -Argv @('-Path', (Join-Path $script:Fixtures 'clean')) | Should -Be 1
    }

    It 'lists VCF.PowerCLI not installed as something to do, exit 1' {
        Mock Test-StairModule { $false }
        Invoke-TestWalkReadiness -Argv @('-Path', (Join-Path $script:Fixtures 'clean')) | Should -Be 1
    }

    It 'lists a job secret missing from the vault by name, without reading any secret''s value, exit 1' {
        Mock Get-SecretInfo { @() }
        Invoke-TestWalkReadiness -Argv @('-Vault', 'jobs', '-SecretName', 'backup', '-Path', (Join-Path $script:Fixtures 'clean')) | Should -Be 1
        ($script:Out -join "`n") | Should -Match 'the secret backup is not in the vault jobs'
        Should -Invoke Get-Secret -Times 0 -Exactly
    }

    It 'lists jobs still to move, read the way Find-PassThroughJob.ps1 reads them, exit 1' {
        Invoke-TestWalkReadiness -Argv @('-Path', (Join-Path $script:Fixtures 'jobs')) | Should -Be 1
        ($script:Out -join "`n") | Should -Match 'job sign-in\(s\) to move'
    }

    It 'exits 3 when the vault cannot be read, or the jobs cannot be read with no Task Scheduler and no -Path' {
        Mock Get-SecretInfo { throw 'Unable to find a vault named jobs.' }
        Invoke-TestWalkReadiness -Argv @('-Vault', 'jobs', '-SecretName', 'backup', '-Path', (Join-Path $script:Fixtures 'clean')) | Should -Be 3
        Mock Get-SecretInfo { @([pscustomobject]@{ Name = $Name }) }
        Invoke-TestWalkReadiness -Argv @() | Should -Be 3
    }

    It 'exits 5 for an unknown option, a missing value, -Vault without -SecretName, or a path that does not exist' {
        Invoke-TestWalkReadiness -Argv @('-NoSuchOptionInAnyCompanion') | Should -Be 5
        Invoke-TestWalkReadiness -Argv @('-Path') | Should -Be 5
        Invoke-TestWalkReadiness -Argv @('-Vault', 'jobs') | Should -Be 5
        Invoke-TestWalkReadiness -Argv @('-Path', (Join-Path $TestDrive 'nowhere')) | Should -Be 5
    }
}
