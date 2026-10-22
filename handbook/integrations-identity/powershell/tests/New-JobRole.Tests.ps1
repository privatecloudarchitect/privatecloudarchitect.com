# New-JobRole.ps1, on a vCenter the tests describe: a role table and a grant table the mocked writes fill.
BeforeAll {
    . (Join-Path $PSScriptRoot 'Stubs.ps1')
    . (Join-Path $PSScriptRoot '..' 'New-JobRole.ps1')
    $script:Base = @('-Server', 'vcenter.example.net', '-Role', 'job-backup', '-Privilege', 'Folder.Create,VirtualMachine.State.PowerOn',
        '-Principal', 'EXAMPLE\svc-backup', '-Entity', 'backup-vms')
}

Describe 'New-JobRole.ps1' {
    BeforeEach {
        $script:Out = [System.Collections.Generic.List[string]]::new()
        $script:Err = [System.Collections.Generic.List[string]]::new()
        Mock Write-StairLine { $script:Out.Add($Text) }
        Mock Write-StairError { $script:Err.Add($Text) }
        $script:Roles = @{}
        $script:Grants = @()
        $script:Entity = [pscustomobject]@{ Name = 'backup-vms'; Id = 'Folder-group-v101' }
        Mock Get-StairConnection { @([pscustomobject]@{ Name = 'vcenter.example.net'; IsConnected = $true }) }
        Mock Get-Inventory { @($script:Entity) }
        Mock Get-VIPrivilege { @($Id | ForEach-Object { [pscustomobject]@{ Id = $_ } }) }
        Mock Get-VIRole { if ($script:Roles.ContainsKey($Name)) { [pscustomobject]@{ Name = $Name; PrivilegeList = $script:Roles[$Name] } } }
        Mock Get-VIPermission { $script:Grants }
        $script:Account = [pscustomobject]@{ Id = 'svc-backup'; Name = 'svc-backup'; Domain = 'EXAMPLE' }
        Mock Get-VIAccount { @($script:Account) }
        Mock New-VIRole { $script:Roles[$Name] = @($Privilege | ForEach-Object { $_.Id }) + @('System.Anonymous', 'System.Read', 'System.View') }
        # vCenter reads a grant back by the principal's full name; the stand-in writes it so from the account it was given
        Mock New-VIPermission { $script:Grants += [pscustomobject]@{ EntityId = $Entity.Id; Principal = "$($Principal.Domain)\$($Principal.Id)"; Role = $Role; Propagate = [bool]$Propagate } }
    }

    It 'plans by default: reads the role and the grant, prints what it would make, and writes nothing, exit 0' {
        Invoke-NewJobRole -Argv $script:Base | Should -Be 0
        Should -Invoke New-VIRole -Times 0 -Exactly
        Should -Invoke New-VIPermission -Times 0 -Exactly
        ($script:Out -join "`n") | Should -Match 'role\s+job-backup: to make'
        ($script:Out -join "`n") | Should -Match 'plan only: nothing was changed'
    }

    It 'resolves the account to exactly one principal, in the plan too, by its domain and id, a user unless -Group' {
        Invoke-NewJobRole -Argv $script:Base | Should -Be 0
        ($script:Out -join "`n") | Should -Match 'account EXAMPLE\\svc-backup: resolves to one user principal'
        Should -Invoke Get-VIAccount -Times 1 -Exactly -ParameterFilter { $User -and -not $Group -and $Domain -eq 'EXAMPLE' -and $Id -eq 'svc-backup' }
        Invoke-NewJobRole -Argv ($script:Base + '-Group') | Should -Be 0
        Should -Invoke Get-VIAccount -Times 1 -Exactly -ParameterFilter { $Group -and -not $User }
    }

    It 'grants to the resolved principal object, never to a name for vCenter to search again' {
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 0
        Should -Invoke New-VIPermission -Times 1 -Exactly -ParameterFilter { $Principal -isnot [string] -and $Principal.Id -eq 'svc-backup' }
    }

    It 'keeps only an exact match of the full name, letter case aside, among what the account search returns' {
        Mock Get-VIAccount { @(
                [pscustomobject]@{ Id = 'svc-backup-old'; Name = 'svc-backup-old'; Domain = 'EXAMPLE' },
                [pscustomobject]@{ Id = 'SVC-BACKUP'; Name = 'SVC-BACKUP'; Domain = 'example' },
                [pscustomobject]@{ Id = 'svc-backup'; Name = 'svc-backup'; Domain = 'OTHER' }) }
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 0
        Should -Invoke New-VIPermission -Times 1 -Exactly -ParameterFilter { $Principal.Id -eq 'SVC-BACKUP' }
    }

    It 'refuses before any write an account that matches no principal, exit 2, naming the count' {
        Mock Get-VIAccount { @() }
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 2
        Should -Invoke New-VIRole -Times 0 -Exactly
        Should -Invoke New-VIPermission -Times 0 -Exactly
        ($script:Err -join "`n") | Should -Match 'matches 0 user principals'
    }

    It 'refuses before any write an account that matches two principals, exit 2, naming the count and never the other names' {
        Mock Get-VIAccount { @(
                [pscustomobject]@{ Id = 'svc-backup'; Name = 'svc-backup'; Domain = 'EXAMPLE' },
                [pscustomobject]@{ Id = 'EXAMPLE\svc-backup'; Name = 'shadow-entry-name'; Domain = 'EXAMPLE' }) }
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 2
        Should -Invoke New-VIRole -Times 0 -Exactly
        Should -Invoke New-VIPermission -Times 0 -Exactly
        ($script:Err -join "`n") | Should -Match 'matches 2 user principals'
        ($script:Out + $script:Err) -join "`n" | Should -Not -Match 'shadow-entry-name'
    }

    It 'with -Execute makes the role and the grant once and reads both back, exit 0; a re-run writes nothing' {
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 0
        Should -Invoke New-VIRole -Times 1 -Exactly
        Should -Invoke New-VIPermission -Times 1 -Exactly
        $script:Grants[0].Propagate | Should -BeTrue
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 0
        Should -Invoke New-VIRole -Times 1 -Exactly
        Should -Invoke New-VIPermission -Times 1 -Exactly
    }

    It 'grants without propagation when -NoPropagate is given' {
        Invoke-NewJobRole -Argv ($script:Base + '-NoPropagate' + '-Execute') | Should -Be 0
        $script:Grants[0].Propagate | Should -BeFalse
    }

    It 'refuses before any write a role that exists with other privileges, exit 2' {
        $script:Roles['job-backup'] = @('Folder.Delete', 'System.Anonymous', 'System.Read', 'System.View')
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 2
        Should -Invoke New-VIRole -Times 0 -Exactly
        Should -Invoke New-VIPermission -Times 0 -Exactly
    }

    It 'refuses before any write an account that holds another role on the object, exit 2' {
        $script:Grants = @([pscustomobject]@{ EntityId = 'Folder-group-v101'; Principal = 'EXAMPLE\svc-backup'; Role = 'Admin'; Propagate = $true })
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 2
        Should -Invoke New-VIRole -Times 0 -Exactly
        Should -Invoke New-VIPermission -Times 0 -Exactly
    }

    It 'refuses an object name that matches no object or more than one, and an unknown privilege id, exit 2' {
        Mock Get-Inventory { @() }
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 2
        Mock Get-Inventory { @($script:Entity, $script:Entity) }
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 2
        Mock Get-Inventory { @($script:Entity) }
        Mock Get-VIPrivilege { @([pscustomobject]@{ Id = 'Folder.Create' }) }
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 2
        Should -Invoke New-VIRole -Times 0 -Exactly
    }

    It 'exits 1 when a write is refused or the read-back differs' {
        Mock New-VIPermission { throw 'Permission to perform this operation was denied.' }
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 1
        Mock New-VIPermission { $script:Grants += [pscustomobject]@{ EntityId = $Entity.Id; Principal = $Principal; Role = 'ReadOnly'; Propagate = $true } }
        $script:Grants = @()
        Invoke-NewJobRole -Argv ($script:Base + '-Execute') | Should -Be 1
    }

    It 'exits 3 when a read fails' {
        Mock Get-VIPermission { throw 'The operation is not allowed in the current state.' }
        Invoke-NewJobRole -Argv $script:Base | Should -Be 3
        Mock Get-VIPermission { $script:Grants }
        Mock Get-VIAccount { throw 'Could not find any of the objects specified by name.' }
        Invoke-NewJobRole -Argv $script:Base | Should -Be 3
    }

    It 'exits 5 for an unknown option, a missing value, a required option not given, an account without its domain, or no open connection' {
        Invoke-NewJobRole -Argv @('-NoSuchOptionInAnyCompanion') | Should -Be 5
        Invoke-NewJobRole -Argv ($script:Base + '-Server') | Should -Be 5
        Invoke-NewJobRole -Argv @('-Server', 'vcenter.example.net') | Should -Be 5
        $noDomain = @('-Server', 'vcenter.example.net', '-Role', 'job-backup', '-Privilege', 'Folder.Create', '-Principal', 'svc-backup', '-Entity', 'backup-vms')
        Invoke-NewJobRole -Argv $noDomain | Should -Be 5
        Should -Invoke Get-VIAccount -Times 0 -Exactly
        Mock Get-StairConnection { @() }
        Invoke-NewJobRole -Argv $script:Base | Should -Be 5
    }
}
