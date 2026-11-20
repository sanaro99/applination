# Start Applination with Docker: database, API and web app in one go.
# Usage:  .\scripts\start.ps1   (or double-click scripts\start.cmd)
#
# Needs only Docker Desktop. The first start builds the images, which takes a
# few minutes; later starts take seconds. Run it again after `git pull` to pick
# up changes. Stop with .\scripts\stop.ps1 (your data is kept).
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "Docker was not found. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and start it, then re-run."
}
$prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
docker info *> $null
$dockerOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prev
if (-not $dockerOk) {
  throw "Docker is installed but not running. Start Docker Desktop, wait for it to say it is running, then re-run."
}

$port = 3000
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
  $m = Select-String -Path $envFile -Pattern '^\s*WEB_PORT\s*=\s*(\d+)' | Select-Object -First 1
  if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
}

Push-Location $root
try {
  Write-Host "Building and starting Applination (the first run takes a few minutes)..." -ForegroundColor Cyan
  docker compose up -d --build
  if ($LASTEXITCODE -ne 0) { throw "docker compose up failed; see the output above." }
} finally { Pop-Location }

$url = "http://localhost:$port"
Write-Host "Waiting for the app to answer at $url ..."
$deadline = (Get-Date).AddMinutes(3)
$ready = $false
while ((Get-Date) -lt $deadline) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "$url/api/health"
    if ($r.StatusCode -eq 200) { $ready = $true; break }
  } catch { }
  Start-Sleep -Seconds 2
}

if ($ready) {
  Write-Host "Applination is running at $url" -ForegroundColor Green
  Start-Process $url
} else {
  Write-Host "The app did not answer within 3 minutes. Recent API logs:" -ForegroundColor Red
  Push-Location $root
  try { docker compose logs --tail=60 api } finally { Pop-Location }
}
