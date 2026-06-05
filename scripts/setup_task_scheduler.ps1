# setup_task_scheduler.ps1 — register a daily Windows Task Scheduler entry.
# Run once from PowerShell (as Administrator if needed).
# Re-running replaces the existing task safely.

param(
    [string]$Time = "08:00",
    [string]$TaskName = "InternshipBot_Daily"
)

$RepoDir = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoDir ".venv\Scripts\python.exe"
$SystemPython = (Get-Command python -ErrorAction SilentlyContinue)?.Source

# Prefer venv python
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} elseif ($SystemPython) {
    $PythonExe = $SystemPython
} else {
    Write-Error "Python not found. Install Python or create a venv at $RepoDir\.venv"
    exit 1
}

Write-Host "Repository : $RepoDir"
Write-Host "Python     : $PythonExe"
Write-Host "Task name  : $TaskName"
Write-Host "Run time   : $Time daily"
Write-Host ""

$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m src.main" `
    -WorkingDirectory $RepoDir

$Trigger = New-ScheduledTaskTrigger -Daily -At $Time

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -StartWhenAvailable

# Remove old task if it exists
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Daily internship application bot run" | Out-Null

Write-Host "Task '$TaskName' registered successfully."
Write-Host "Verify with: Get-ScheduledTask -TaskName '$TaskName'"
