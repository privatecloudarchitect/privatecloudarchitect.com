# A Crawl job: its credential from the file New-JobCredential.ps1 wrote.
$credential = Import-Clixml -Path 'C:\jobs\backup.credential.xml'
Connect-VIServer -Server vcenter.example.net -Credential $credential
