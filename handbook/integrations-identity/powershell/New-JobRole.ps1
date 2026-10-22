<#
.SYNOPSIS
New-JobRole.ps1: one job's custom vCenter role, granted to the job's account on the one object it works on. Plan by
default.

.DESCRIPTION
The Crawl step of field note 16's stair: a custom role holding only the privileges the job uses, and one grant of it to
the job's account on one inventory object. It uses the PowerCLI connection you already opened to -Server
(Connect-VIServer, as an administrator), so it handles no credential itself.

The account is named with its domain (DOMAIN\account or account@domain) and is resolved, before anything is written, to
exactly one principal on the vCenter: Get-VIAccount (-User, or -Group with -Group) with that domain and that account as
its id, kept only where the principal's full name matches the one given, letter case aside. The grant is made on that
principal, never on a name for vCenter to search again. A name that matches no principal, or more than one, is refused;
the refusal gives the count, never the other names.

  plan (no flag)   resolves the account, reads the role and the grant, and prints what it would make; it changes
                   nothing
  -Execute         makes the role (New-VIRole) only if it is absent, and the grant (New-VIPermission) only if it is
                   absent, then reads both back; a re-run that finds both writes nothing

A custom role also holds three system privileges vCenter adds to every role (System.Anonymous, System.Read and
System.View), so the read-back compares the role with the privileges you name plus those three. It never edits a role
or a grant that exists: a role of that name with other privileges, or the account holding another role on that object,
is refused before anything is written. The grant propagates to the objects below unless -NoPropagate is given.

Usage:
  pwsh -NoProfile -File ./New-JobRole.ps1 -Server <vCenter> -Role <name> -Privilege <id>[,<id>...]
       -Principal <DOMAIN\account> -Entity <object name> [-Group] [-NoPropagate] [-Execute]
  (run it in the PowerShell session that holds your connection: & ./New-JobRole.ps1 ...)

Exit codes:
  0 the plan printed, or the run held on read-back (a re-run that found both writes nothing and exits 0)
  1 the run did not hold: a write was refused, or the read-back is not the role and the grant asked for
  2 refused before any write: the account matches no principal or more than one, the role exists with other privileges, the account holds another role on the object, the object name matches no object or more than one, or a privilege id is not known
  3 a read failed, or an error the script did not expect
  5 a usage error: an unknown option, a missing value, a required option not given, an account not named with its domain, or no open connection to -Server
#>

# No param block: the script reads its own arguments, so every usage error exits 5.

function Write-StairLine {
    param([string]$Text)
    [Console]::Out.WriteLine($Text)
}

function Write-StairError {
    param([string]$Text)
    [Console]::Error.WriteLine($Text)
}

function Read-StairArgument {
    param([object[]]$Argv, [string[]]$Value = @(), [string[]]$Switch = @())
    $options = @{}
    $i = 0
    while ($i -lt $Argv.Count) {
        $token = [string]$Argv[$i]
        if (-not $token.StartsWith('-') -or $token.Length -lt 2) { throw "unexpected argument '$token'" }
        $name = $token.Substring(1)
        $key = @($Value + $Switch | Where-Object { $_ -ieq $name })
        if ($key.Count -ne 1) { throw "unknown option '$token'" }
        $key = $key[0]
        if ($options.ContainsKey($key)) { throw "-$key is given twice" }
        if ($Switch -contains $key) {
            $options[$key] = $true
            $i += 1
            continue
        }
        if ($i + 1 -ge $Argv.Count) { throw "-$key needs a value" }
        $next = $Argv[$i + 1]
        if ($next -is [array]) { $next = ($next | ForEach-Object { [string]$_ }) -join ',' }
        $next = [string]$next
        if ($next.StartsWith('-') -or $next -eq '') { throw "-$key needs a value" }
        $options[$key] = $next
        $i += 2
    }
    $options
}

function Get-StairConnection {
    # PowerCLI keeps the default connections in the global DefaultVIServers variable
    param([string]$Server)
    $open = Get-Variable -Name DefaultVIServers -Scope Global -ValueOnly -ErrorAction SilentlyContinue
    return @($open | Where-Object { $_ -and $_.Name -ieq $Server -and $_.IsConnected })
}

$script:SystemPrivileges = @('System.Anonymous', 'System.Read', 'System.View')

function Test-StairSamePrivilege {
    param([string[]]$Have, [string[]]$Want)
    $a = @($Have | Sort-Object -Unique)
    $b = @(($Want + $script:SystemPrivileges) | Sort-Object -Unique)
    return (($a -join ',') -eq ($b -join ','))
}

function Split-StairPrincipal {
    # DOMAIN\account or account@domain, as (domain, name); nothing for a name without its domain
    param([string]$Principal)
    if ($Principal -match '^([^\\@\s]+)\\([^\\@\s]+)$') { return @($Matches[1], $Matches[2]) }
    if ($Principal -match '^([^\\@\s]+)@([^\\@\s]+)$') { return @($Matches[2], $Matches[1]) }
    return $null
}

function Test-StairSamePrincipal {
    # One principal's name, as vCenter writes it, against the domain and name given, letter case aside
    param([string]$Written, [string]$Domain, [string]$Name)
    return ($Written -ieq "$Domain\$Name") -or ($Written -ieq "$Name@$Domain")
}

function Test-StairPrincipalMatch {
    # A principal Get-VIAccount returned for the domain asked: its full name, or its bare id or name in that domain
    param($Found, [string]$Domain, [string]$Name)
    foreach ($written in @([string]$Found.Id, [string]$Found.Name)) {
        if (Test-StairSamePrincipal -Written $written -Domain $Domain -Name $Name) { return $true }
        if ($written -ieq $Name -and ([string]$Found.Domain -ieq $Domain -or -not [string]$Found.Domain)) { return $true }
    }
    return $false
}

function Resolve-StairPrincipal {
    # Every principal of that kind in that domain whose full name is exactly the one given: none, one, or more
    # (Get-VIAccount's Id set takes the domain; its Name set does not)
    param([string]$Domain, [string]$Name, [bool]$Group, $Server)
    if ($Group) {
        $found = @(Get-VIAccount -Group -Domain $Domain -Id $Name -Server $Server -ErrorAction Stop)
    } else {
        $found = @(Get-VIAccount -User -Domain $Domain -Id $Name -Server $Server -ErrorAction Stop)
    }
    return @($found | Where-Object { Test-StairPrincipalMatch -Found $_ -Domain $Domain -Name $Name })
}

function Get-StairGrant {
    # The grants set on the object itself (not inherited) for the principal, read for the object and matched here
    param($Entity, [string]$Domain, [string]$Name, $Server)
    return @(Get-VIPermission -Entity $Entity -Server $Server -ErrorAction Stop |
            Where-Object { $_.EntityId -eq $Entity.Id -and (Test-StairSamePrincipal -Written ([string]$_.Principal) -Domain $Domain -Name $Name) })
}

function Invoke-NewJobRole {
    param([object[]]$Argv = @())
    try {
        $o = Read-StairArgument -Argv $Argv -Value @('Server', 'Role', 'Privilege', 'Principal', 'Entity') -Switch @('Group', 'NoPropagate', 'Execute')
        foreach ($required in 'Server', 'Role', 'Privilege', 'Principal', 'Entity') {
            if (-not $o.ContainsKey($required)) { throw "-$required is required" }
        }
        $parts = Split-StairPrincipal -Principal $o['Principal']
        if (-not $parts) { throw "-Principal names the account with its domain: DOMAIN\account or account@domain" }
        $domain, $account = $parts
        $ids = @($o['Privilege'] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        if ($ids.Count -eq 0) { throw '-Privilege needs at least one privilege id' }
        $vc = @(Get-StairConnection -Server $o['Server'])
        if ($vc.Count -ne 1) { throw "no open connection to $($o['Server']): run Connect-VIServer -Server $($o['Server']) first, in this session" }
        $vc = $vc[0]
    } catch {
        Write-StairError "usage: $($_.Exception.Message)"
        Write-StairError 'usage: New-JobRole.ps1 -Server <vCenter> -Role <name> -Privilege <id>[,...] -Principal <DOMAIN\account> -Entity <object> [-Group] [-NoPropagate] [-Execute]'
        return 5
    }
    $propagate = -not [bool]$o['NoPropagate']
    $kind = if ($o['Group']) { 'group' } else { 'user' }
    try {
        $principal = @(Resolve-StairPrincipal -Domain $domain -Name $account -Group ([bool]$o['Group']) -Server $vc)
        if ($principal.Count -ne 1) {
            Write-StairError "REFUSED: $($o['Principal']) matches $($principal.Count) $kind principals on this vCenter; name exactly one"
            return 2
        }
        $principal = $principal[0]
        $entity = @(Get-Inventory -Name $o['Entity'] -Server $vc -ErrorAction SilentlyContinue)
        if ($entity.Count -ne 1) {
            Write-StairError "REFUSED: '$($o['Entity'])' names $($entity.Count) objects; name exactly one"
            return 2
        }
        $entity = $entity[0]
        $privileges = @(Get-VIPrivilege -Id $ids -Server $vc -ErrorAction SilentlyContinue)
        $knownIds = @($privileges | ForEach-Object { $_.Id })
        $unknown = @($ids | Where-Object { $knownIds -notcontains $_ })
        if ($unknown.Count -gt 0) {
            Write-StairError "REFUSED: not a privilege id on this vCenter: $($unknown -join ', ')"
            return 2
        }
        $role = @(Get-VIRole -Name $o['Role'] -Server $vc -ErrorAction SilentlyContinue)
        if ($role.Count -gt 0 -and -not (Test-StairSamePrivilege -Have $role[0].PrivilegeList -Want $ids)) {
            Write-StairError "REFUSED: the role $($o['Role']) exists with other privileges; this script never edits a role"
            return 2
        }
        $grant = @(Get-StairGrant -Entity $entity -Domain $domain -Name $account -Server $vc)
        if ($grant.Count -gt 0 -and $grant[0].Role -ne $o['Role']) {
            Write-StairError "REFUSED: $($o['Principal']) holds the role $($grant[0].Role) on $($o['Entity']); this script never changes a grant"
            return 2
        }
    } catch {
        Write-StairError "NOT READ: $($_.Exception.Message)"
        return 3
    }
    $roleState = if ($role.Count -gt 0) { 'exists' } else { 'to make' }
    $grantState = if ($grant.Count -gt 0) { 'exists' } else { 'to make' }
    Write-StairLine "account $($o['Principal']): resolves to one $kind principal"
    Write-StairLine "role   $($o['Role']): $roleState, privileges $($ids -join ', ')"
    Write-StairLine "grant  $($o['Principal']) on $($o['Entity']): $grantState, role $($o['Role']), propagate $(if ($propagate) { 'yes' } else { 'no' })"
    if (-not $o['Execute']) {
        Write-StairLine 'plan only: nothing was changed; add -Execute to make what is missing'
        return 0
    }
    try {
        if ($role.Count -eq 0) {
            New-VIRole -Name $o['Role'] -Privilege $privileges -Server $vc -ErrorAction Stop | Out-Null
            Write-StairLine "made the role $($o['Role'])"
        }
        if ($grant.Count -eq 0) {
            New-VIPermission -Entity $entity -Principal $principal -Role $o['Role'] -Propagate:$propagate -Server $vc -ErrorAction Stop | Out-Null
            Write-StairLine "made the grant on $($o['Entity'])"
        }
    } catch {
        Write-StairError "NOT HELD: a write was refused: $($_.Exception.Message)"
        return 1
    }
    try {
        $roleBack = @(Get-VIRole -Name $o['Role'] -Server $vc -ErrorAction Stop)
        $grantBack = @(Get-StairGrant -Entity $entity -Domain $domain -Name $account -Server $vc)
    } catch {
        Write-StairError "NOT READ: the read-back failed: $($_.Exception.Message)"
        return 3
    }
    if ($roleBack.Count -ne 1 -or -not (Test-StairSamePrivilege -Have $roleBack[0].PrivilegeList -Want $ids) -or
        $grantBack.Count -ne 1 -or $grantBack[0].Role -ne $o['Role'] -or [bool]$grantBack[0].Propagate -ne $propagate) {
        Write-StairError 'NOT HELD: the read-back is not the role and the grant asked for'
        return 1
    }
    Write-StairLine 'held: the role and the grant read back as asked'
    return 0
}

if ($MyInvocation.InvocationName -ne '.') { exit (Invoke-NewJobRole -Argv $args) }
