# A job as many teams wrote it: the scheduled task's Windows account signs it in.
Connect-VIServer -Server vcenter.example.net
Get-VM | Measure-Object
