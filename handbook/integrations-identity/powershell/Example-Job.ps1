<#
.SYNOPSIS
Example-Job.ps1: a job for Invoke-VcJob.ps1. It takes the connection as -Server and prints how many VMs the job's
identity can see there.

.DESCRIPTION
Replace the body with your job's own work; keep the -Server parameter, and pass -Server to every PowerCLI call, since
Invoke-VcJob.ps1 signs in with -NotDefault and the connection is not PowerCLI's default one.
#>
param($Server)

$count = @(Get-VM -Server $Server -ErrorAction Stop).Count
"vms=$count"
