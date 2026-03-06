# Install rrecall hooks into Claude Code settings.
# Usage: .\install-hooks.ps1 [-Scope user|project]
# Compatible with Windows PowerShell 5.1+ and PowerShell Core 7+.

param(
    [ValidateSet("user", "project")]
    [string]$Scope = "user"
)

$ErrorActionPreference = "Stop"

if ($Scope -eq "user") {
    $homeDir = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
    $SettingsDir = Join-Path $homeDir ".claude"
} else {
    $SettingsDir = Join-Path (Get-Location) ".claude"
}

$SettingsFile = Join-Path $SettingsDir "settings.json"

if (-not (Test-Path $SettingsDir)) {
    New-Item -ItemType Directory -Path $SettingsDir -Force | Out-Null
}

# --- Helper: convert PSCustomObject (5.1) to ordered hashtable ---
function ConvertTo-Hashtable {
    param([Parameter(ValueFromPipeline)] $InputObject)
    process {
        if ($null -eq $InputObject) { return @{} }
        if ($InputObject -is [System.Collections.IDictionary]) { return $InputObject }
        if ($InputObject -is [PSCustomObject]) {
            $ht = [ordered]@{}
            foreach ($prop in $InputObject.PSObject.Properties) {
                $val = $prop.Value
                if ($val -is [PSCustomObject]) {
                    $val = ConvertTo-Hashtable $val
                } elseif ($val -is [System.Collections.IEnumerable] -and $val -isnot [string]) {
                    $val = @($val | ForEach-Object { ConvertTo-Hashtable $_ })
                }
                $ht[$prop.Name] = $val
            }
            return $ht
        }
        return $InputObject
    }
}

# Back up existing settings
if (Test-Path $SettingsFile) {
    $timestamp = Get-Date -Format "yyyyMMddHHmmss"
    Copy-Item $SettingsFile "$SettingsFile.bak.$timestamp"
    $raw = Get-Content $SettingsFile -Raw | ConvertFrom-Json
    $settings = ConvertTo-Hashtable $raw
} else {
    $settings = [ordered]@{}
}

if (-not $settings.Contains("hooks")) {
    $settings["hooks"] = [ordered]@{}
}

$hooks = $settings["hooks"]
if ($hooks -isnot [System.Collections.IDictionary]) {
    $hooks = ConvertTo-Hashtable $hooks
    $settings["hooks"] = $hooks
}

$sessionEndHook = [ordered]@{
    "hooks" = @(
        [ordered]@{
            "type" = "command"
            "command" = "rrecall hooks session-end"
        }
    )
}

$stopHook = [ordered]@{
    "hooks" = @(
        [ordered]@{
            "type" = "command"
            "command" = "rrecall hooks stop"
        }
    )
}

function Test-HasRrecallHook {
    param([array]$HookList, [string]$ModuleName)
    foreach ($entry in $HookList) {
        $entryHooks = if ($entry -is [PSCustomObject]) { $entry.hooks } else { $entry["hooks"] }
        foreach ($h in $entryHooks) {
            $cmd = if ($h -is [PSCustomObject]) { $h.command } else { $h["command"] }
            if ($cmd -and $cmd.Contains($ModuleName)) {
                return $true
            }
        }
    }
    return $false
}

if (-not $hooks.Contains("SessionEnd")) {
    $hooks["SessionEnd"] = @()
}
if (-not (Test-HasRrecallHook $hooks["SessionEnd"] "rrecall hooks session-end")) {
    $hooks["SessionEnd"] += $sessionEndHook
}

if (-not $hooks.Contains("Stop")) {
    $hooks["Stop"] = @()
}
if (-not (Test-HasRrecallHook $hooks["Stop"] "rrecall hooks stop")) {
    $hooks["Stop"] += $stopHook
}

$settings["hooks"] = $hooks
$json = $settings | ConvertTo-Json -Depth 10
Set-Content -Path $SettingsFile -Value $json -Encoding UTF8

Write-Host "rrecall hooks installed to $SettingsFile"
Write-Host "  Stop        -> rrecall hooks stop (updates markdown each turn)"
Write-Host "  SessionEnd  -> rrecall hooks session-end (final write + indexing)"
