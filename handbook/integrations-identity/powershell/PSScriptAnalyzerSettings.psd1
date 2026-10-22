# PSScriptAnalyzer settings for the stair's scripts: every rule at Error and Warning, and the syntax held to both
# Windows PowerShell 5.1 and PowerShell 7, since a vCenter 8 job host may run either.
@{
    Severity     = @('Error', 'Warning')
    IncludeDefaultRules = $true
    Rules        = @{
        PSUseCompatibleSyntax = @{
            Enable         = $true
            TargetVersions = @('5.1', '7.0')
        }
    }
}
