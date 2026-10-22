# Install the local deploy public key on the server. You type the server password once; later deploys use the key.
# Usage: powershell -ExecutionPolicy Bypass -File deploy\install-ssh-key.ps1 [-Server root@IP]
# (Kept ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less scripts as GBK.)
param(
    [string]$Server = "",
    [string]$KeyFile = "$env:USERPROFILE\.ssh\screen_mirroring_deploy.pub"
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


Write-Host "Installing deploy key on $Server. Please type the server password below (input is hidden):"
Get-Content $KeyFile | ssh -o StrictHostKeyChecking=accept-new $Server "mkdir -p ~/.ssh && chmod 700 ~/.ssh && tr -d '\r' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo KEY_INSTALLED"
