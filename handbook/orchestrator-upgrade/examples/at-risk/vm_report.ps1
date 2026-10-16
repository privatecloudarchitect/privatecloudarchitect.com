# A VM report written against an older PowerCLI runtime. On the 9.1.1 PowerCLI runtime neither
# VMware.PowerCLI nor PowerNSX is installed, so both imports fail; and the version pin names 101.0.0,
# the numbering 9.1.0.0400 installs, where 9.1.1 installs 13.5.1.
#Requires -Modules @{ ModuleName = 'VMware.VimAutomation.Core'; ModuleVersion = '101.0.0' }
function Handler($context, $inputs) {
    Import-Module VMware.PowerCLI
    Import-Module PowerNSX
    $server = Connect-VIServer -Server $inputs.vcenter -User $inputs.user -Password $inputs.password
    $vms = Get-VM -Server $server | Select-Object Name, PowerState
    Disconnect-VIServer -Server $server -Confirm:$false
    return ($vms | ConvertTo-Json -Compress)
}
