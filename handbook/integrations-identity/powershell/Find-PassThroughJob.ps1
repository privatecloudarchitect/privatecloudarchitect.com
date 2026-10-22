<#
.SYNOPSIS
Find-PassThroughJob.ps1: list the PowerCLI jobs that still sign in to vCenter as the Windows account running them.

.DESCRIPTION
The first step of field note 16's stair (Today). On a Windows host with no -Path, it reads every scheduled task's
actions, and for each action that starts powershell or pwsh, the script it runs (-File) or the command it carries
(-Command). With -Path it reads the scripts in those files or folders instead (-Recurse for subfolders), on any system.
Each script is parsed with PowerShell's own parser, and the script lists, by file, line and parameter name only:

  pass-through          a Connect-VIServer that names no -User, -Password, -Credential, -Session,
                        -SamlSecurityContext, -VcfApiToken or -VcfOAuthSecurityContext: PowerCLI then looks in its
                        credential store and tries SSPI, the Windows session's own sign-in
  password-in-script    a Connect-VIServer given -Password as text typed into the script
  password-in-task      a scheduled task whose arguments carry -Password
  credential-store      New-VICredentialStoreItem, Get-VICredentialStoreItem or -SaveCredentials: PowerCLI's credential
                        store, which PowerCLI 13.3 does not support on PowerShell 6 and later
  not-judged            a Connect-VIServer whose parameters come from splatting, so its credential cannot be read

It never prints a line of the script, so a password typed into a job is never copied to the output. It writes nothing.

Usage:
  pwsh -NoProfile -File ./Find-PassThroughJob.ps1                      # a Windows host's scheduled tasks
  pwsh -NoProfile -File ./Find-PassThroughJob.ps1 -Path <file or folder>[,<file or folder>...] [-Recurse]
  powershell -NoProfile -File .\Find-PassThroughJob.ps1                # the same on Windows PowerShell 5.1

Exit codes:
  0 nothing to move: every Connect-VIServer found names a credential
  1 at least one job to move is listed (pass-through, a password in a script or a task, the credential store)
  3 a task or a script could not be read or parsed, or a call was not judged, and nothing to move was found
  5 a usage error: an unknown option, a missing value, a path that does not exist, or no -Path where there is no Task Scheduler
#>

# No param block: the script reads its own arguments, so every usage error exits 5 (pwsh -File binds a param block
# before any line of the script runs, and a missing value would exit 1).

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

function Test-StairWindow {
    # Windows PowerShell 5.1 is Windows; PowerShell 6 and later say so in $IsWindows
    if ($PSVersionTable.PSEdition -eq 'Desktop') { return $true }
    return [bool](Get-Variable -Name IsWindows -ValueOnly -ErrorAction SilentlyContinue)
}

function Test-StairTaskScheduler {
    return [bool](Get-Command -Name Get-ScheduledTask -ErrorAction SilentlyContinue)
}

$script:CredentialSources = @('User', 'Password', 'Credential', 'Session', 'SamlSecurityContext', 'VcfApiToken',
    'VcfOAuthSecurityContext')

function Resolve-StairParameter {
    # PowerShell takes any unambiguous prefix of a parameter's name: -Cred is -Credential
    param([string]$Given, [string[]]$Known)
    $hit = @($Known | Where-Object { $_ -like "$Given*" })
    if ($hit.Count -ge 1 -and $Given.Length -ge 2) { return $hit[0] }
    return $null
}

function Find-StairInAst {
    # The findings in one parsed script: objects with Kind, Line and Detail (parameter names only, never text)
    param($Ast)
    $found = @()
    $commands = $Ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)
    foreach ($command in $commands) {
        $name = $command.GetCommandName()
        if (-not $name) { continue }
        $line = $command.Extent.StartLineNumber
        if ($name -ieq 'New-VICredentialStoreItem' -or $name -ieq 'Get-VICredentialStoreItem') {
            $found += [pscustomobject]@{ Kind = 'credential-store'; Line = $line; Detail = $name }
            continue
        }
        if ($name -ine 'Connect-VIServer') { continue }
        $elements = @($command.CommandElements)
        $splatted = @($elements | Where-Object {
                $_ -is [System.Management.Automation.Language.VariableExpressionAst] -and $_.Splatted })
        $named = @()
        $passwordText = $false
        for ($k = 1; $k -lt $elements.Count; $k++) {
            $element = $elements[$k]
            if ($element -isnot [System.Management.Automation.Language.CommandParameterAst]) { continue }
            $known = Resolve-StairParameter -Given $element.ParameterName -Known ($script:CredentialSources + 'SaveCredentials')
            if (-not $known) { continue }
            $named += $known
            if ($known -eq 'Password') {
                $argument = $element.Argument
                if (-not $argument -and $k + 1 -lt $elements.Count) { $argument = $elements[$k + 1] }
                if ($argument -is [System.Management.Automation.Language.StringConstantExpressionAst] -or
                    $argument -is [System.Management.Automation.Language.ExpandableStringExpressionAst]) {
                    $passwordText = $true
                }
            }
        }
        if ($named -contains 'SaveCredentials') {
            $found += [pscustomobject]@{ Kind = 'credential-store'; Line = $line; Detail = 'Connect-VIServer -SaveCredentials' }
        }
        if ($passwordText) {
            $found += [pscustomobject]@{ Kind = 'password-in-script'; Line = $line; Detail = 'Connect-VIServer -Password, given as text' }
            continue
        }
        $sources = @($named | Where-Object { $script:CredentialSources -contains $_ })
        if ($sources.Count -gt 0) { continue }
        if ($splatted.Count -gt 0) {
            $found += [pscustomobject]@{ Kind = 'not-judged'; Line = $line; Detail = 'Connect-VIServer with splatted parameters' }
            continue
        }
        $found += [pscustomobject]@{ Kind = 'pass-through'; Line = $line; Detail = 'Connect-VIServer names no credential' }
    }
    $found
}

function Read-StairScript {
    # One script file, parsed: its findings, or one unread entry when it cannot be read or parsed
    param([string]$Path)
    $tokens = $null
    $errors = $null
    try {
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    } catch {
        return @([pscustomobject]@{ Kind = 'unread'; Line = 0; Detail = 'the script could not be read' })
    }
    if ($errors -and $errors.Count -gt 0) {
        return @([pscustomobject]@{ Kind = 'unread'; Line = 0; Detail = 'the script does not parse' })
    }
    return @(Find-StairInAst -Ast $ast)
}

function Read-StairCommandText {
    param([string]$Text)
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($Text, [ref]$tokens, [ref]$errors)
    if ($errors -and $errors.Count -gt 0) {
        return @([pscustomobject]@{ Kind = 'unread'; Line = 0; Detail = 'the command does not parse' })
    }
    return @(Find-StairInAst -Ast $ast)
}

function Get-StairPathScript {
    # The scripts under -Path: files as given, folders' .ps1 files (-Recurse for subfolders)
    param([string[]]$Path, [bool]$Recurse)
    $files = @()
    foreach ($p in $Path) {
        $item = Get-Item -LiteralPath $p -ErrorAction Stop
        if ($item.PSIsContainer) {
            $files += @(Get-ChildItem -LiteralPath $item.FullName -Filter '*.ps1' -File -Recurse:$Recurse |
                    Sort-Object -Property FullName | ForEach-Object { $_.FullName })
        } else {
            $files += $item.FullName
        }
    }
    $files
}

function Format-StairPath {
    # A script under the current folder is shown by its relative path, any other by its full path
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $Path }
    $relative = Resolve-Path -LiteralPath $Path -Relative -ErrorAction SilentlyContinue
    if ($relative -and -not ([string]$relative).StartsWith('..')) { return [string]$relative }
    return $Path
}

function Read-StairTask {
    # Each scheduled task's PowerShell actions: (Task, Source, Findings) for its script or its inline command
    $out = @()
    $tasks = @(Get-ScheduledTask -ErrorAction Stop)
    foreach ($task in $tasks) {
        $label = "$($task.TaskPath)$($task.TaskName)"
        foreach ($action in @($task.Actions)) {
            $execute = ([string]$action.Execute).Trim('"', ' ')
            if ($execute -notmatch '(?i)(^|[\\/])(pwsh|powershell)(\.exe)?$') { continue }
            $arguments = [string]$action.Arguments
            if ($arguments -match '(?i)(^|\s)-Password(\s|:|$)') {
                $out += [pscustomobject]@{ Task = $label; Source = 'the task''s arguments'; Findings = @(
                        [pscustomobject]@{ Kind = 'password-in-task'; Line = 0; Detail = 'the task''s arguments carry -Password' }) }
            }
            if ($arguments -match '(?i)(^|\s)-File\s+(?:"([^"]+)"|''([^'']+)''|(\S+))') {
                $file = @($Matches[2], $Matches[3], $Matches[4]) | Where-Object { $_ } | Select-Object -First 1
                if (-not [System.IO.Path]::IsPathRooted($file) -and $action.WorkingDirectory) {
                    $file = Join-Path -Path $action.WorkingDirectory -ChildPath $file
                }
                if (Test-Path -LiteralPath $file -PathType Leaf) {
                    $out += [pscustomobject]@{ Task = $label; Source = $file; Findings = @(Read-StairScript -Path $file) }
                } else {
                    $out += [pscustomobject]@{ Task = $label; Source = $file; Findings = @(
                            [pscustomobject]@{ Kind = 'unread'; Line = 0; Detail = 'the task''s script was not found' }) }
                }
            } elseif ($arguments -match '(?i)(^|\s)-(Command|c)\s+(.+)$') {
                $text = $Matches[3].Trim()
                if ($text.Length -ge 2 -and $text[0] -eq '"' -and $text[-1] -eq '"') { $text = $text.Substring(1, $text.Length - 2) }
                $out += [pscustomobject]@{ Task = $label; Source = 'the task''s command'; Findings = @(Read-StairCommandText -Text $text) }
            }
        }
    }
    $out
}

function Invoke-FindPassThroughJob {
    param([object[]]$Argv = @())
    try {
        $o = Read-StairArgument -Argv $Argv -Value @('Path') -Switch @('Recurse')
        $paths = @()
        if ($o.ContainsKey('Path')) {
            $paths = @($o['Path'] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            foreach ($p in $paths) { if (-not (Test-Path -LiteralPath $p)) { throw "the path '$p' does not exist" } }
        } elseif (-not (Test-StairTaskScheduler)) {
            throw 'this system has no Task Scheduler: give -Path <file or folder> with the job scripts'
        }
        if ($o.ContainsKey('Recurse') -and -not $o.ContainsKey('Path')) { throw '-Recurse goes with -Path' }
    } catch {
        Write-StairError "usage: $($_.Exception.Message)"
        Write-StairError 'usage: Find-PassThroughJob.ps1 [-Path <file or folder>[,...]] [-Recurse]'
        return 5
    }
    try {
        $sources = @()
        if ($paths.Count -gt 0) {
            foreach ($file in @(Get-StairPathScript -Path $paths -Recurse ([bool]$o['Recurse']))) {
                $sources += [pscustomobject]@{ Task = $null; Source = $file; Findings = @(Read-StairScript -Path $file) }
            }
        } else {
            $sources = @(Read-StairTask)
        }
        $move = 0
        $unjudged = 0
        foreach ($source in $sources) {
            foreach ($f in @($source.Findings)) {
                $shown = Format-StairPath -Path $source.Source
                $where = if ($f.Line -gt 0) { "$($shown):$($f.Line)" } else { $shown }
                $task = if ($source.Task) { "  task $($source.Task)" } else { '' }
                Write-StairLine ('{0,-20} {1}  {2}{3}' -f $f.Kind, $where, $f.Detail, $task)
                if ($f.Kind -in @('unread', 'not-judged')) { $unjudged += 1 } else { $move += 1 }
            }
        }
        Write-StairLine ("read {0} source(s): {1} to move, {2} not read or not judged" -f $sources.Count, $move, $unjudged)
        if ($move -gt 0) { return 1 }
        if ($unjudged -gt 0) { return 3 }
        return 0
    } catch {
        Write-StairError "NOT READ: $($_.Exception.Message)"
        return 3
    }
}

if ($MyInvocation.InvocationName -ne '.') { exit (Invoke-FindPassThroughJob -Argv $args) }
