# Build the customized RustDesk client (Windows x64) from ..\rustdesk (branch "custom").
# Usage: powershell -ExecutionPolicy Bypass -File client\build.ps1 [-SkipBridge] [-SkipCargo]
# Output: release\rustdesk-custom-<version>.exe (single-file portable/installer, like the official exe).
#
# Toolchains live in D:\rustdesk-build (see client\README.md): Flutter 3.24.5 with the RustDesk
# engine, LLVM 15.0.6, vcpkg (deps installed for x64-windows-static), Rust 1.75 via rustup.
# (Kept ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less scripts as GBK.)
param(
    [switch]$SkipBridge,
    [switch]$SkipCargo,
    [string]$Tools = "D:\rustdesk-build",
    # Server baked into the client. Defaults come from client\.env (not committed, see .env.example).
    [string]$ServerHost = "",
    [string]$ServerKey = "",
    [string]$ApiServer = ""
)
$ErrorActionPreference = "Stop"

$clientEnv = @{}
$clientEnvPath = Join-Path $PSScriptRoot ".env"
if (Test-Path $clientEnvPath) {
    foreach ($line in Get-Content $clientEnvPath) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $clientEnv[$matches[1]] = $matches[2].Trim() }
    }
}
if (-not $ServerHost) { $ServerHost = $clientEnv["RD_HOST"] }
if (-not $ServerKey) { $ServerKey = $clientEnv["RD_KEY"] }
if (-not $ApiServer) { $ApiServer = $clientEnv["RD_API"] }
if (-not $ServerHost -or -not $ServerKey) { throw "Set RD_HOST and RD_KEY in client\.env (copy client\.env.example) or pass -ServerHost/-ServerKey" }

$src = (Resolve-Path (Join-Path $PSScriptRoot "..\rustdesk")).Path
$release = Join-Path $PSScriptRoot "..\release"
# The project venv goes first so build.py's pip3/python3 (portable packer) stay out of the system Python.
$venv = (Resolve-Path (Join-Path $PSScriptRoot "..\.venv\Scripts")).Path
$env:PATH = "$venv;$Tools\flutter\bin;$Tools\llvm\bin;$env:USERPROFILE\.cargo\bin;" + $env:PATH
$env:LIBCLANG_PATH = "$Tools\llvm\bin"
$env:VCPKG_ROOT = "$Tools\vcpkg"
$env:RUSTUP_TOOLCHAIN = "1.75"
# Mirrors for mainland China; harmless elsewhere.
$env:FLUTTER_STORAGE_BASE_URL = "https://storage.flutter-io.cn"
$env:PUB_HOSTED_URL = "https://pub.flutter-io.cn"
$env:RD_HOST = $ServerHost
$env:RD_KEY = $ServerKey
$env:RD_API = $ApiServer

function Run([string]$what, [scriptblock]$block) {
    Write-Host "==> $what"
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

Push-Location $src
try {
    if (-not $SkipBridge) {
        Run "flutter pub get" { Push-Location flutter; flutter pub get; $code = $LASTEXITCODE; Pop-Location; $global:LASTEXITCODE = $code }
        Run "generate flutter_rust_bridge" {
            flutter_rust_bridge_codegen --rust-input .\src\flutter_ffi.rs --dart-output .\flutter\lib\generated_bridge.dart --c-output .\flutter\macos\Runner\bridge_generated.h --llvm-path $Tools\llvm
        }
    }
    # build.py renames its output with os.rename, which cannot overwrite on Windows.
    Remove-Item "rustdesk-*-install.exe", "rustdesk_portable.exe" -ErrorAction SilentlyContinue
    $buildArgs = @("build.py", "--portable", "--flutter", "--hwcodec", "--vram")
    if ($SkipCargo) { $buildArgs += "--skip-cargo" }
    Run "build.py $($buildArgs -join ' ')" { python @buildArgs }
    $packed = Get-ChildItem "rustdesk-*-install.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $version = $packed.Name -replace '^rustdesk-(.+)-install\.exe$', '$1'
    New-Item -ItemType Directory -Force $release | Out-Null
    $out = Join-Path $release "rustdesk-custom-$version.exe"
    Copy-Item $packed.FullName $out -Force
    Write-Host "Done: $out"
}
finally {
    Pop-Location
}
