# Installer for the always-show Claude Code context gauge tweak (Windows).
#
#   * applies the patch to every installed claude-code version
#   * registers a Scheduled Task that re-applies it whenever VSCode rewrites
#     %USERPROFILE%\.vscode\extensions\extensions.json (i.e. after each update)
#
# Run from an elevated-or-normal PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
# Undo with:  powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1 -Uninstall

param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$repo   = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo "scripts\patch_gauge.py"
$python = (Get-Command python3 -ErrorAction SilentlyContinue) ?? (Get-Command python -ErrorAction SilentlyContinue)
$taskName = "ClaudeCodeContextGauge"

if (-not $python) { throw "python3/python not found on PATH. Install Python 3 and retry." }

if ($Uninstall) {
  Write-Host ">> Removing scheduled task and restoring the gate..."
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  & $python.Source $script --restore
  Write-Host ">> Uninstalled. Reload the VSCode window to revert."
  return
}

Write-Host ">> Applying the patch to currently-installed versions..."
& $python.Source $script

# Trigger when extensions.json changes, via a file-system watcher schedule.
# Scheduled Tasks can't watch a single file directly, so we use an event trigger
# on the registry-file change through a logon trigger + a 5-minute repetition as a
# safety net. The patch is idempotent, so frequent runs are harmless.
$action  = New-ScheduledTaskAction -Execute $python.Source -Argument "`"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration ([TimeSpan]::MaxValue)).Repetition
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Re-apply always-show Claude Code context gauge" -Force | Out-Null

Write-Host ">> Scheduled task '$taskName' registered (runs at logon + every 5 min, idempotent)."
Write-Host ">> Done. Reload the VSCode window (Ctrl+Shift+P -> 'Reload Window')."
