# Find-PassThroughJob.ps1, held on the fixtures under fixtures/ and on scheduled tasks the tests describe.
BeforeAll {
    . (Join-Path $PSScriptRoot 'Stubs.ps1')
    . (Join-Path $PSScriptRoot '..' 'Find-PassThroughJob.ps1')
    $script:Fixtures = Join-Path $PSScriptRoot 'fixtures'
}

Describe 'Find-PassThroughJob.ps1' {
    BeforeEach {
        $script:Out = [System.Collections.Generic.List[string]]::new()
        $script:Err = [System.Collections.Generic.List[string]]::new()
        Mock Write-StairLine { $script:Out.Add($Text) }
        Mock Write-StairError { $script:Err.Add($Text) }
    }

    It 'lists a Connect-VIServer with no credential as pass-through, by file and line, and exits 1' {
        $code = Invoke-FindPassThroughJob -Argv @('-Path', (Join-Path $script:Fixtures 'jobs'))
        $code | Should -Be 1
        ($script:Out | Where-Object { $_ -match '^pass-through\s+.*passthrough\.ps1:2\s' }).Count | Should -Be 1
    }

    It 'lists a password typed into a script by its parameter name and never prints the script''s text' {
        Invoke-FindPassThroughJob -Argv @('-Path', (Join-Path $script:Fixtures 'jobs')) | Out-Null
        ($script:Out | Where-Object { $_ -match '^password-in-script\s+.*typed-password\.ps1:2\s+Connect-VIServer -Password' }).Count | Should -Be 1
        ($script:Out + $script:Err) -join "`n" | Should -Not -Match 'not-a-real-password'
        ($script:Out + $script:Err) -join "`n" | Should -Not -Match 'svc-backup'
    }

    It 'lists PowerCLI''s credential store, New-VICredentialStoreItem and -SaveCredentials' {
        Invoke-FindPassThroughJob -Argv @('-Path', (Join-Path $script:Fixtures 'jobs')) | Out-Null
        ($script:Out | Where-Object { $_ -match '^credential-store\s+.*credential-store\.ps1:2\s+New-VICredentialStoreItem' }).Count | Should -Be 1
        ($script:Out | Where-Object { $_ -match '^credential-store\s+.*credential-store\.ps1:3\s+Connect-VIServer -SaveCredentials' }).Count | Should -Be 1
    }

    It 'passes a job that signs in with -Credential or -VcfApiToken, and exits 0 when nothing is left to move' {
        $code = Invoke-FindPassThroughJob -Argv @('-Path', (Join-Path $script:Fixtures 'clean'))
        $code | Should -Be 0
        ($script:Out | Where-Object { $_ -match '^(pass-through|password-in|credential-store)' }).Count | Should -Be 0
    }

    It 'exits 3 for a script that does not parse and a splatted call it cannot judge, when nothing is to move' {
        $code = Invoke-FindPassThroughJob -Argv @('-Path', (Join-Path $script:Fixtures 'unjudged'))
        $code | Should -Be 3
        ($script:Out | Where-Object { $_ -match '^unread\s+.*broken\.ps1' }).Count | Should -Be 1
        ($script:Out | Where-Object { $_ -match '^not-judged\s+.*splatted\.ps1:3' }).Count | Should -Be 1
    }

    It 'reads the scheduled tasks'' PowerShell actions, their -File scripts and a -Password in their arguments' {
        Mock Test-StairTaskScheduler { $true }
        $jobs = Join-Path $script:Fixtures 'jobs'
        Mock Get-ScheduledTask {
            @(
                [pscustomobject]@{ TaskPath = '\Jobs\'; TaskName = 'backup'; Actions = @(
                        [pscustomobject]@{ Execute = 'C:\Program Files\PowerShell\7\pwsh.exe'; Arguments = '-NoProfile -File passthrough.ps1'; WorkingDirectory = $jobs }) },
                [pscustomobject]@{ TaskPath = '\Jobs\'; TaskName = 'report'; Actions = @(
                        [pscustomobject]@{ Execute = 'powershell.exe'; Arguments = '-NoProfile -File "' + (Join-Path $jobs 'credential.ps1') + '" -Password x'; WorkingDirectory = '' }) },
                [pscustomobject]@{ TaskPath = '\'; TaskName = 'defrag'; Actions = @(
                        [pscustomobject]@{ Execute = 'defrag.exe'; Arguments = '/C'; WorkingDirectory = '' }) }
            )
        }
        $code = Invoke-FindPassThroughJob -Argv @()
        $code | Should -Be 1
        ($script:Out | Where-Object { $_ -match '^pass-through\s+.*passthrough\.ps1:2\s.*task \\Jobs\\backup$' }).Count | Should -Be 1
        ($script:Out | Where-Object { $_ -match '^password-in-task\s.*task \\Jobs\\report$' }).Count | Should -Be 1
        ($script:Out | Where-Object { $_ -match 'defrag' }).Count | Should -Be 0
    }

    It 'judges a task''s inline -Command as it judges a script' {
        Mock Test-StairTaskScheduler { $true }
        Mock Get-ScheduledTask {
            @([pscustomobject]@{ TaskPath = '\'; TaskName = 'inline'; Actions = @(
                        [pscustomobject]@{ Execute = 'pwsh'; Arguments = '-NoProfile -Command "Connect-VIServer -Server vcenter.example.net; Get-VM"'; WorkingDirectory = '' }) })
        }
        Invoke-FindPassThroughJob -Argv @() | Should -Be 1
        ($script:Out | Where-Object { $_ -match '^pass-through\s+the task''s command:1\s.*task \\inline$' }).Count | Should -Be 1
    }

    It 'changes nothing: it calls no command that writes' {
        Mock New-VIRole { }
        Mock New-VIPermission { }
        Invoke-FindPassThroughJob -Argv @('-Path', (Join-Path $script:Fixtures 'jobs')) | Out-Null
        Should -Invoke New-VIRole -Times 0 -Exactly
        Should -Invoke New-VIPermission -Times 0 -Exactly
    }

    It 'exits 5 for an unknown option, a missing value, a path that does not exist, and no -Path without a Task Scheduler' {
        Mock Test-StairTaskScheduler { $false }
        Invoke-FindPassThroughJob -Argv @('-NoSuchOptionInAnyCompanion') | Should -Be 5
        Invoke-FindPassThroughJob -Argv @('-Path') | Should -Be 5
        Invoke-FindPassThroughJob -Argv @('-Path', (Join-Path $TestDrive 'nowhere')) | Should -Be 5
        Invoke-FindPassThroughJob -Argv @() | Should -Be 5
    }

    It 'exits 3 when the Task Scheduler cannot be read' {
        Mock Test-StairTaskScheduler { $true }
        Mock Get-ScheduledTask { throw 'Access is denied.' }
        Invoke-FindPassThroughJob -Argv @() | Should -Be 3
    }
}
