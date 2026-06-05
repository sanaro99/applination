# Start FastAPI + Next.js dev servers in parallel.
# Usage:  .\scripts\dev.ps1
$ErrorActionPreference = "Stop"

$root = (Resolve-Path "$PSScriptRoot\..").Path
$api  = Start-Process -PassThru -NoNewWindow -WorkingDirectory $root `
  -FilePath "python" -ArgumentList @("-m","uvicorn","server.app:app","--reload","--port","8000")

# Start-Process can't launch npm directly on Windows — npm is a .cmd shim, not a
# Win32 exe ("%1 is not a valid Win32 application"). Resolve npm.cmd via PATH.
$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npmCmd) { throw "npm.cmd not found on PATH" }
$web = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $root "web") `
  -FilePath $npmCmd -ArgumentList @("run","dev")

Write-Host "FastAPI pid=$($api.Id)  Next.js pid=$($web.Id)" -ForegroundColor Green
Write-Host "API   : http://127.0.0.1:8000"
Write-Host "Web   : http://127.0.0.1:3000"
Write-Host "Press Ctrl+C to stop both."

try {
  Wait-Process -Id $api.Id, $web.Id
} finally {
  if (!$api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
  if (!$web.HasExited) { Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue }
}
