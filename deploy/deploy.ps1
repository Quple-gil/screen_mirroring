# Upload the server code to the server and (re)start it with docker compose.
# Usage: powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 [-Server root@IP] [-Dir /opt/screen_mirroring]
# Needs deploy\.env (copy from deploy\.env.example) and the SSH key installed by install-ssh-key.ps1.
# (Kept ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less scripts as GBK.)
param(
    [string]$Server = "",
    [string]$Dir = "/opt/screen_mirroring",
    [string]$Key = "$env:USERPROFILE\.ssh\screen_mirroring_deploy"
)

# Defaults come from deploy\.env (not committed), so no server address lives in the repo.
function Read-DotEnv([string]$path) {
    $values = @{}
    if (Test-Path $path) {
        foreach ($line in Get-Content $path) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $values[$matches[1]] = $matches[2].Trim() }
        }
    }
    return $values
}
if (-not $Server) {
    $envFile = Read-DotEnv (Join-Path $PSScriptRoot ".env")
    if (-not $envFile["PUBLIC_IP"]) { throw "Pass -Server root@IP or set PUBLIC_IP in deploy\.env" }
    $Server = "root@" + $envFile["PUBLIC_IP"]
}

$ErrorActionPreference = "Stop"

if (-not $Dir.StartsWith("/") -or $Dir.Length -lt 5) { throw "Refusing suspicious remote dir: $Dir" }
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$root\deploy\.env")) { throw "deploy\.env not found: copy deploy\.env.example to deploy\.env and fill it in first" }

$archive = Join-Path $env:TEMP "screen_mirroring_deploy.tar.gz"
if (-not (Test-Path "$root\deploy\rustdesk\bin\hbbs")) { throw "deploy\rustdesk\bin\hbbs not found: download rustdesk-server-linux-amd64.zip (see README) and put hbbs/hbbr there" }
tar -czf $archive --exclude=__pycache__ -C $root Dockerfile requirements.txt server deploy/docker-compose.yml deploy/rustdesk deploy/.env
if ($LASTEXITCODE -ne 0) { throw "tar failed" }

Write-Host "Uploading to $Server ..."
scp -i $Key -q $archive "${Server}:/tmp/screen_mirroring_deploy.tar.gz"
if ($LASTEXITCODE -ne 0) { throw "upload failed" }
Remove-Item $archive

Write-Host "Building and starting containers (first build takes a few minutes) ..."
ssh -i $Key $Server "set -e; mkdir -p $Dir; rm -rf $Dir/server; tar -xzf /tmp/screen_mirroring_deploy.tar.gz -C $Dir; rm /tmp/screen_mirroring_deploy.tar.gz; cd $Dir/deploy; docker compose up -d --build --remove-orphans; docker compose ps"
if ($LASTEXITCODE -ne 0) { throw "remote deploy failed" }
Write-Host "Done."
