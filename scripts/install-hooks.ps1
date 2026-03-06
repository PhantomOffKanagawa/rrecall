# Install rrecall hooks into Claude Code settings.
# Usage: .\install-hooks.ps1 [-Scope user|project]

param(
    [ValidateSet("user", "project")]
    [string]$Scope = "user"
)

$ErrorActionPreference = "Stop"

if ($Scope -eq "user") {
    $SettingsDir = Join-Path $env:USERPROFILE ".claude"
} else {
    $SettingsDir = Join-Path (Get-Location) ".claude"
}

$SettingsFile = Join-Path $SettingsDir "settings.json"

if (-not (Test-Path $SettingsDir)) {
    New-Item -ItemType Directory -Path $SettingsDir -Force | Out-Null
}

# Back up existing settings
if (Test-Path $SettingsFile) {
    $timestamp = Get-Date -Format "yyyyMMddHHmmss"
    Copy-Item $SettingsFile "$SettingsFile.bak.$timestamp"
    $settings = Get-Content $SettingsFile -Raw | ConvertFrom-Json -AsHashtable
} else {
    $settings = @{}
}

if (-not $settings.ContainsKey("hooks")) {
    $settings["hooks"] = @{}
}

$hooks = $settings["hooks"]

$preCompactHook = @{
    "hooks" = @(
        @{
            "type" = "command"
            "command" = "python -m rrecall.hooks.pre_compact"
        }
    )
}

$sessionEndHook = @{
    "hooks" = @(
        @{
            "type" = "command"
            "command" = "python -m rrecall.hooks.session_end"
        }
    )
}

function Test-HasRrecallHook {
    param([array]$HookList, [string]$ModuleName)
    foreach ($entry in $HookList) {
        foreach ($h in $entry.hooks) {
            if ($h.command -and $h.command.Contains($ModuleName)) {
                return $true
            }
        }
    }
    return $false
}

if (-not $hooks.ContainsKey("PreCompact")) {
    $hooks["PreCompact"] = @()
}
if (-not (Test-HasRrecallHook $hooks["PreCompact"] "rrecall.hooks.pre_compact")) {
    $hooks["PreCompact"] += $preCompactHook
}

if (-not $hooks.ContainsKey("SessionEnd")) {
    $hooks["SessionEnd"] = @()
}
if (-not (Test-HasRrecallHook $hooks["SessionEnd"] "rrecall.hooks.session_end")) {
    $hooks["SessionEnd"] += $sessionEndHook
}

$settings["hooks"] = $hooks
$json = $settings | ConvertTo-Json -Depth 10
Set-Content -Path $SettingsFile -Value $json -Encoding UTF8

Write-Host "rrecall hooks installed to $SettingsFile"
Write-Host "  PreCompact  -> python -m rrecall.hooks.pre_compact"
Write-Host "  SessionEnd  -> python -m rrecall.hooks.session_end"
