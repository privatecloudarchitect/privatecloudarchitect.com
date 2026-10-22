# A job that uses PowerCLI's credential store.
New-VICredentialStoreItem -Host vcenter.example.net -User 'svc-backup@example.net' -Password 'not-a-real-password'
Connect-VIServer -Server vcenter.example.net -User 'svc-backup@example.net' -SaveCredentials
