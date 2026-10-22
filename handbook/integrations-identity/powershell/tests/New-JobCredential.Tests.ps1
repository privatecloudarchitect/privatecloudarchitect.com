# New-JobCredential.ps1. Off Windows the tests stand in for Windows (Test-StairWindow mocked), so Export-Clixml writes
# plain text into the test's own drive: a value made up for the test, removed with it.
BeforeAll {
    . (Join-Path $PSScriptRoot 'Stubs.ps1')
    . (Join-Path $PSScriptRoot '..' 'New-JobCredential.ps1')
}

Describe 'New-JobCredential.ps1' {
    BeforeEach {
        $script:Out = [System.Collections.Generic.List[string]]::new()
        $script:Err = [System.Collections.Generic.List[string]]::new()
        Mock Write-StairLine { $script:Out.Add($Text) }
        Mock Write-StairError { $script:Err.Add($Text) }
        Mock Get-StairCurrentAccount { 'EXAMPLE\svc-task' }
        Mock Get-StairComputerName { 'JOBHOST01' }
        Mock Get-Credential { [System.Management.Automation.PSCredential]::new('svc-backup@example.net', (New-StairSecureString 'made-up-for-the-test')) }
        $script:File = Join-Path $TestDrive ("job-{0}.credential.xml" -f [guid]::NewGuid())
    }

    It 'refuses off Windows before it prompts or writes, exit 2' {
        Mock Test-StairWindow { $false }
        Invoke-NewJobCredential -Argv @('-Path', $script:File, '-UserName', 'svc-backup@example.net') | Should -Be 2
        Should -Invoke Get-Credential -Times 0 -Exactly
        Test-Path -LiteralPath $script:File | Should -BeFalse
    }

    It 'writes with Export-Clixml, reads it back with Import-Clixml, and names the account and computer that can read it, exit 0' {
        Mock Test-StairWindow { $true }
        Invoke-NewJobCredential -Argv @('-Path', $script:File, '-UserName', 'svc-backup@example.net') | Should -Be 0
        (Import-Clixml -LiteralPath $script:File).UserName | Should -Be 'svc-backup@example.net'
        ($script:Out -join "`n") | Should -Match 'readable only by EXAMPLE\\svc-task on JOBHOST01'
        ($script:Out + $script:Err) -join "`n" | Should -Not -Match 'made-up-for-the-test'
    }

    It 'refuses a file that exists unless -Force is given, exit 2' {
        Mock Test-StairWindow { $true }
        Set-Content -LiteralPath $script:File -Value 'earlier'
        Invoke-NewJobCredential -Argv @('-Path', $script:File, '-UserName', 'svc-backup@example.net') | Should -Be 2
        Get-Content -LiteralPath $script:File | Should -Be 'earlier'
        Invoke-NewJobCredential -Argv @('-Path', $script:File, '-UserName', 'svc-backup@example.net', '-Force') | Should -Be 0
    }

    It 'refuses when -TaskName runs as another Windows account, exit 2, and proceeds when it is the same' {
        Mock Test-StairWindow { $true }
        Mock Get-ScheduledTask { [pscustomobject]@{ Principal = [pscustomobject]@{ UserId = 'EXAMPLE\someone-else' } } }
        Invoke-NewJobCredential -Argv @('-Path', $script:File, '-UserName', 'svc-backup@example.net', '-TaskName', 'backup') | Should -Be 2
        Should -Invoke Get-Credential -Times 0 -Exactly
        Mock Get-ScheduledTask { [pscustomobject]@{ Principal = [pscustomobject]@{ UserId = 'svc-task' } } }
        Invoke-NewJobCredential -Argv @('-Path', $script:File, '-UserName', 'svc-backup@example.net', '-TaskName', 'backup') | Should -Be 0
    }

    It 'exits 3 when no credential is entered or the task cannot be read' {
        Mock Test-StairWindow { $true }
        Mock Get-Credential { $null }
        Invoke-NewJobCredential -Argv @('-Path', $script:File, '-UserName', 'svc-backup@example.net') | Should -Be 3
        Mock Get-ScheduledTask { throw 'The system cannot find the file specified.' }
        Invoke-NewJobCredential -Argv @('-Path', $script:File, '-UserName', 'svc-backup@example.net', '-TaskName', 'nowhere') | Should -Be 3
    }

    It 'exits 5 for an unknown option, a missing value, or -Path or -UserName not given' {
        Invoke-NewJobCredential -Argv @('-NoSuchOptionInAnyCompanion') | Should -Be 5
        Invoke-NewJobCredential -Argv @('-Path') | Should -Be 5
        Invoke-NewJobCredential -Argv @('-Path', $script:File) | Should -Be 5
        Invoke-NewJobCredential -Argv @('-UserName', 'svc-backup@example.net') | Should -Be 5
    }
}
