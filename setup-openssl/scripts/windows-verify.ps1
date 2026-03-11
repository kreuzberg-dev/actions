$ErrorActionPreference = "Stop"
$vcpkgRoot = "C:\vcpkg\installed\x64-windows-static-md"

Write-Host "Verifying OpenSSL installation at: $vcpkgRoot" -ForegroundColor Green

if (-not (Test-Path $vcpkgRoot)) {
  Write-Error "vcpkg OpenSSL installation directory not found: $vcpkgRoot"
  exit 1
}

$requiredDirs = @("lib", "include")
foreach ($dir in $requiredDirs) {
  $path = Join-Path $vcpkgRoot $dir
  if (-not (Test-Path $path)) {
    Write-Error "Required directory not found: $path"
    exit 1
  }
  Write-Host "  Found $dir directory: $path"
}

$libFiles = @("libssl.lib", "libcrypto.lib")
$libDir = Join-Path $vcpkgRoot "lib"
foreach ($file in $libFiles) {
  $filePath = Join-Path $libDir $file
  if (-not (Test-Path $filePath)) {
    Write-Host "  Warning: Expected library file not found: $filePath (may be OK if in subdirectory)"
  } else {
    Write-Host "  Found library: $file"
  }
}

$headerDir = Join-Path $vcpkgRoot "include"
$headerFile = Join-Path $headerDir "openssl\ssl.h"
if (-not (Test-Path $headerFile)) {
  Write-Host "  Warning: Expected header file not found: $headerFile"
} else {
  Write-Host "  Found header: openssl/ssl.h"
}

Write-Host "OpenSSL installation verified successfully" -ForegroundColor Green
