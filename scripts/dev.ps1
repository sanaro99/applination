# Start FastAPI + Next.js dev servers in parallel.
# Usage:  .\scripts\dev.ps1   (or double-click scripts\dev.cmd)
# Safe on a fresh clone: it installs what is missing on the first run.
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

# --- First-run setup ---------------------------------------------------------
# Everything below is idempotent, so the same command works on a fresh clone
# and every day after: it creates the venv, installs Python and npm packages
# only when their lockfiles changed since the last install, and creates the
# encryption key once.

# Run a native command with its stderr discarded. Windows PowerShell 5.1 turns
# redirected native stderr into a terminating error under
# $ErrorActionPreference = "Stop", so relax it for the call. $LASTEXITCODE
# still reports the command's own result.
function Invoke-Quiet([scriptblock]$cmd) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try { & $cmd 2>$null | Out-Null } finally { $ErrorActionPreference = $prev }
}

function Get-FileHashText([string]$path) {
  if (Test-Path $path) { (Get-FileHash -Algorithm SHA256 $path).Hash } else { "" }
}

# Always use the project's venv interpreter — plain "python" resolves to
# whatever's first on PATH, which may be an unrelated global install missing
# this project's dependencies.
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  $basePython = (Get-Command py -ErrorAction SilentlyContinue).Source
  $pyArgs = @("-3")
  if (-not $basePython) {
    $basePython = (Get-Command python -ErrorAction SilentlyContinue).Source
    $pyArgs = @()
  }
  if (-not $basePython) {
    throw "Python 3.11+ was not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH'), then re-run."
  }
  Write-Host "Creating the Python virtual environment (.venv)..." -ForegroundColor Yellow
  & $basePython @pyArgs -m venv (Join-Path $root ".venv")
  if ($LASTEXITCODE -ne 0) { throw "Could not create .venv" }
}
$pythonExe = $venvPython

$reqHash = Get-FileHashText (Join-Path $root "requirements.txt")
$reqStamp = Join-Path $root ".venv\.requirements.sha256"
if ((Get-Content $reqStamp -ErrorAction SilentlyContinue) -ne $reqHash) {
  Write-Host "Installing Python packages (first run, or requirements.txt changed)..." -ForegroundColor Yellow
  & $pythonExe -m pip install --disable-pip-version-check -q -r (Join-Path $root "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
  Set-Content -Path $reqStamp -Value $reqHash
}

$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npmCmd) {
  throw "npm was not found. Install Node.js 20+ from https://nodejs.org/, then re-run."
}
$webDir = Join-Path $root "web"
$lockHash = Get-FileHashText (Join-Path $webDir "package-lock.json")
$lockStamp = Join-Path $webDir "node_modules\.package-lock.sha256"
if ((Get-Content $lockStamp -ErrorAction SilentlyContinue) -ne $lockHash) {
  Write-Host "Installing web packages (first run, or package-lock.json changed)..." -ForegroundColor Yellow
  Push-Location $webDir
  try { & $npmCmd install --no-audit --no-fund } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
  Set-Content -Path $lockStamp -Value $lockHash
}

# Optional settings from .env (KEY=VALUE lines). Variables already set in the
# shell win, so a one-off override still works.
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
  foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
      $name = $Matches[1]
      $value = $Matches[2].Trim().Trim('"').Trim("'")
      if (-not [Environment]::GetEnvironmentVariable($name)) {
        [Environment]::SetEnvironmentVariable($name, $value)
      }
    }
  }
}

# The encryption key for stored provider keys. Without it the app cannot save
# an API key, which used to be a manual step that was easy to miss. The file is
# the same one the Docker setup uses, under the gitignored data/ folder.
if (-not $env:APPLINATION_SECRET_KEY) {
  $keyFile = Join-Path $root "data\secret.key"
  if (-not "$(Get-Content $keyFile -Raw -ErrorAction SilentlyContinue)".Trim()) {
    New-Item -ItemType Directory -Force (Split-Path $keyFile) | Out-Null
    $newKey = & $pythonExe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    Set-Content -Path $keyFile -Value $newKey -NoNewline
    Write-Host "Created an encryption key at data\secret.key. Back it up with your data." -ForegroundColor Yellow
  }
  $env:APPLINATION_SECRET_KEY = "$(Get-Content $keyFile -Raw)".Trim()
}

# --- Postgres ---------------------------------------------------------------
# Persistence moved from a SQLite file to Postgres. Bring up a local dev
# instance if one isn't already listening, but never block the dev servers on
# it — print what to do and carry on, so a Docker outage doesn't stop frontend
# work.
$dbPort = 5432
$startedDb = $false
$dbUp = [bool](Get-NetTCPConnection -LocalPort $dbPort -State Listen -ErrorAction SilentlyContinue)
if (-not $env:DATABASE_URL -and -not $dbUp) {
  $docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
  if ($docker) {
    Write-Host "Postgres not listening on $dbPort - starting applination-postgres-dev" -ForegroundColor Yellow
    # `docker start` on an existing container, else create it.
    Invoke-Quiet { docker start applination-postgres-dev }
    if ($LASTEXITCODE -ne 0) {
      Invoke-Quiet {
        docker run -d --name applination-postgres-dev `
          -e POSTGRES_USER=applination -e POSTGRES_DB=applination `
          -e POSTGRES_PASSWORD=applination `
          -p "${dbPort}:5432" postgres:18-alpine
      }
    }
    $startedDb = ($LASTEXITCODE -eq 0)
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Could not start Postgres automatically. Start one yourself, then re-run:" -ForegroundColor Red
      Write-Host "  docker run -d --name applination-postgres-dev -e POSTGRES_USER=applination -e POSTGRES_DB=applination -e POSTGRES_PASSWORD=applination -p 5432:5432 postgres:18-alpine"
    }
  } else {
    Write-Host "Postgres is not running and docker was not found on PATH." -ForegroundColor Red
    Write-Host "Set DATABASE_URL to an existing Postgres, or install Docker Desktop."
  }
}

# A container that was just started needs a few seconds before it accepts
# connections; migrating straight away failed on every first run.
if ($startedDb) {
  $deadline = (Get-Date).AddSeconds(45)
  do {
    Start-Sleep -Seconds 1
    Invoke-Quiet { docker exec applination-postgres-dev pg_isready -q -U applination -d applination }
  } while ($LASTEXITCODE -ne 0 -and (Get-Date) -lt $deadline)
}

# Apply migrations before the API starts, so a schema change pulled from git
# doesn't surface as a confusing 500 on the first request.
Push-Location $root
try {
  & $pythonExe -m alembic upgrade head
  if ($LASTEXITCODE -ne 0) {
    Write-Host "alembic upgrade failed - the API will refuse to start. Fix the database first." -ForegroundColor Red
  }
} finally { Pop-Location }

# Scope the reload watcher to backend source only. Without --reload-dir,
# uvicorn watches the whole repo root (Path.cwd()), which includes
# web/.next (rewritten continuously by the Next.js dev server), output/,
# and data/ — none of which are in watchfiles' default ignore list. That
# caused uvicorn to restart the entire FastAPI process on every frontend
# navigation (Next writing to its own build cache), stalling in-flight API
# calls and making every page nav feel sluggish.
$api  = Start-Process -PassThru -NoNewWindow -WorkingDirectory $root `
  -FilePath $pythonExe -ArgumentList @("-m","uvicorn","server.app:app","--reload","--reload-dir","server","--reload-dir","src","--port","8000")

# ($npmCmd was resolved during first-run setup.)
# Start-Process can't launch npm directly on Windows — npm is a .cmd shim, not a
# Win32 exe ("%1 is not a valid Win32 application"). Resolve npm.cmd via PATH.
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
