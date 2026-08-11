# Start FastAPI + Next.js dev servers in parallel.
# Usage:  .\scripts\dev.ps1
$ErrorActionPreference = "Stop"

# A prior run that didn't shut down cleanly (e.g. window closed instead of
# Ctrl+C) can leave a stale server holding these ports, which then fails the
# new one with "WinError 10013 access forbidden" instead of a clear
# port-in-use error. Clear them first.
foreach ($port in 8000, 3000) {
  Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
      Write-Host "Killing stale process on port $port (pid=$_)" -ForegroundColor Yellow
      Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
}

$root = (Resolve-Path "$PSScriptRoot\..").Path

# Always use the project's venv interpreter — plain "python" resolves to
# whatever's first on PATH, which may be an unrelated global install missing
# this project's dependencies.
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }

# Scope the reload watcher to backend source only. Without --reload-dir,
# uvicorn watches the whole repo root (Path.cwd()), which includes
# web/.next (rewritten continuously by the Next.js dev server), output/,
# and data/ — none of which are in watchfiles' default ignore list. That
# caused uvicorn to restart the entire FastAPI process on every frontend
# navigation (Next writing to its own build cache), stalling in-flight API
# calls and making every page nav feel sluggish.
$api  = Start-Process -PassThru -NoNewWindow -WorkingDirectory $root `
  -FilePath $pythonExe -ArgumentList @("-m","uvicorn","server.app:app","--reload","--reload-dir","server","--reload-dir","src","--port","8000")

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
