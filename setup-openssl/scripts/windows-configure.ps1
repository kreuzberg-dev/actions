$ErrorActionPreference = "Stop"
$vcpkgRoot = "C:\vcpkg\installed\x64-windows-static-md"

Write-Host "Configuring OpenSSL environment variables..." -ForegroundColor Green

if (-not (Test-Path $vcpkgRoot)) {
  Write-Error "vcpkg OpenSSL installation not found at: $vcpkgRoot"
  exit 1
}

$envVars = @{
  "VCPKG_ROOT"          = "C:\vcpkg"
  "OPENSSL_DIR"         = $vcpkgRoot
  "OPENSSL_ROOT_DIR"    = $vcpkgRoot
  "OPENSSL_LIB_DIR"     = "$vcpkgRoot\lib"
  "OPENSSL_INCLUDE_DIR" = "$vcpkgRoot\include"
  "OPENSSL_STATIC"      = "1"
}

foreach ($key in $envVars.Keys) {
  $value = $envVars[$key]
  Write-Host "  Setting $key=$value"
  Add-Content -Path $env:GITHUB_ENV -Value "$key=$value"
}

$opensslBin = "$vcpkgRoot\bin"
if (Test-Path $opensslBin) {
  Write-Host "  Adding $opensslBin to GITHUB_PATH"
  Add-Content -Path $env:GITHUB_PATH -Value $opensslBin -Encoding utf8
}

Write-Host "OpenSSL environment configuration completed" -ForegroundColor Green
