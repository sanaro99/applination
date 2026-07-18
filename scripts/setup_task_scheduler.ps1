# setup_task_scheduler.ps1 — register a daily Windows Task Scheduler entry.
# Run once from PowerShell (as Administrator if needed).
# Re-running replaces the existing task safely.
#
# Cost note: DeepSeek (the default LLM provider) bills ~50% less during its
# off-peak window, 16:30-00:30 GMT. When -Time is omitted this script defaults
# to the local equivalent of 20:00 GMT (mid-window) so the daily run lands
# inside off-peak automatically. Pass -Time to override; pass -FullPrice to
# silence the warning when you deliberately pick a peak-hour time.

param(
    [string]$Time,
    [switch]$FullPrice,
    [string]$TaskName = "InternshipBot_Daily"
)

# DeepSeek off-peak window (UTC): 16:30 -> 00:30 (wraps midnight).
function Test-OffPeak([datetime]$LocalTime) {
    $utc = $LocalTime.ToUniversalTime()
    $mins = $utc.Hour * 60 + $utc.Minute
    # Inside if >= 16:30 (990) OR <= 00:30 (30).
    return ($mins -ge 990) -or ($mins -le 30)
}

# Default to the local equivalent of 20:00 GMT when no -Time was supplied.
if (-not $Time) {
    $utcTarget = [DateTime]::SpecifyKind((Get-Date).Date.AddHours(20), 'Utc')
    $Time = $utcTarget.ToLocalTime().ToString("HH:mm")
}

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
Write-Host "Run time   : $Time daily (local)"

# Report whether the chosen time lands in DeepSeek's off-peak window.
$ResolvedLocal = [datetime]::ParseExact($Time, "HH:mm", $null)
$SuggestedOffPeak = ([DateTime]::SpecifyKind((Get-Date).Date.AddHours(20), 'Utc')).ToLocalTime().ToString("HH:mm")
if (Test-OffPeak $ResolvedLocal) {
    Write-Host "Off-peak   : inside DeepSeek's 16:30-00:30 GMT window (~50% off)." -ForegroundColor Green
} elseif (-not $FullPrice) {
    Write-Warning "This time is outside DeepSeek's off-peak window (16:30-00:30 GMT) - LLM calls bill at full price."
    Write-Warning "For ~50% off, use -Time $SuggestedOffPeak (local = 20:00 GMT). Pass -FullPrice to silence this."
}
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
