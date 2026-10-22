# A Run job: an API client's token from the vault.
$token = Get-Secret -Vault jobs -Name backup-token
Connect-VIServer -Server vcenter.example.net -VcfApiToken $token -NotDefault
