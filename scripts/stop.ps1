# Stop Applination's Docker containers. Your accounts, documents and database
# are kept and come back with .\scripts\start.ps1.
$root = (Resolve-Path "$PSScriptRoot\..").Path
Push-Location $root
try { docker compose --profile tunnel down } finally { Pop-Location }
