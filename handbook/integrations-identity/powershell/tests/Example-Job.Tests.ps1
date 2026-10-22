# Example-Job.ps1: it reads through the connection it is given, and prints only a count.
BeforeAll {
    . (Join-Path $PSScriptRoot 'Stubs.ps1')
    $script:JobPath = Join-Path $PSScriptRoot '..' 'Example-Job.ps1'
}

Describe 'Example-Job.ps1' {
    It 'counts the VMs through the connection it is given as -Server' {
        $connection = [pscustomobject]@{ Name = 'vcenter.example.net' }
        Mock Get-VM { @(1, 2, 3) }
        & $script:JobPath -Server $connection | Should -Be 'vms=3'
        Should -Invoke Get-VM -Times 1 -Exactly -ParameterFilter { $Server.Name -eq 'vcenter.example.net' }
    }
}
