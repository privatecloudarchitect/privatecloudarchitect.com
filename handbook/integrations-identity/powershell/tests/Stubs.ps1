# Stand-ins for the PowerCLI, SecretManagement, SecretStore and ScheduledTasks commands the scripts call, so the tests
# run on any system without those modules and without loading them: a function of the same name is found before a
# cmdlet, and each test mocks the stand-in with the answer it needs. None of them reaches a vCenter or a vault.

function Connect-VIServer { [CmdletBinding()] param($Server, $Credential, $VcfApiToken, [switch]$NotDefault) }
function Disconnect-VIServer { [CmdletBinding(SupportsShouldProcess)] param($Server, [switch]$Force) }
function Get-View { [CmdletBinding()] param([Parameter(Position = 0)]$VIObject, $Server) }
function Get-VM { [CmdletBinding()] param($Server) }
function Get-Inventory { [CmdletBinding()] param($Name, $Server) }
function Get-VIPrivilege { [CmdletBinding()] param($Id, $Server) }
function Get-VIRole { [CmdletBinding()] param($Name, $Server) }
function Get-VIPermission { [CmdletBinding()] param($Entity, $Principal, $Server) }
function Get-VIAccount { [CmdletBinding()] param([switch]$User, [switch]$Group, $Domain, $Id, $Server) }
function New-VIRole { [CmdletBinding(SupportsShouldProcess)] param($Name, $Privilege, $Server) }
function New-VIPermission { [CmdletBinding(SupportsShouldProcess)] param($Entity, $Principal, $Role, [switch]$Propagate, $Server) }
function Get-Secret { [CmdletBinding()] param($Vault, $Name) }
function Get-SecretInfo { [CmdletBinding()] param($Vault, $Name) }
function Unlock-SecretStore { [CmdletBinding()] param($Password) }
function Get-ScheduledTask { [CmdletBinding()] param($TaskName) }

function New-StairSecureString {
    # A SecureString built from characters, for tests only; the scripts never build one from text
    param([string]$Text)
    $s = New-Object -TypeName System.Security.SecureString
    foreach ($c in $Text.ToCharArray()) { $s.AppendChar($c) }
    $s.MakeReadOnly()
    $s
}
