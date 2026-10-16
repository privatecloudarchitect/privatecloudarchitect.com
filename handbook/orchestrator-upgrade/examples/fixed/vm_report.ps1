# The same report, loading only the module it uses, by name and with no version pin, so it runs on
# the PowerCLI runtime of either release. NSX work goes through VMware.Sdk.Nsx.Policy, which both
# runtimes install, rather than PowerNSX.
function Handler($context, $inputs) {
    Import-Module VMware.VimAutomation.Core
    $server = Connect-VIServer -Server $inputs.vcenter -User $inputs.user -Password $inputs.password
    $vms = Get-VM -Server $server | Select-Object Name, PowerState
    Disconnect-VIServer -Server $server -Confirm:$false
    return ($vms | ConvertTo-Json -Compress)
}
