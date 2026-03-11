$ErrorActionPreference = "Stop"
Write-Host "Attempting to locate vcpkg executable..." -ForegroundColor Green

$vcpkg = $null
try {
  $vcpkg = (Get-Command vcpkg -ErrorAction SilentlyContinue)?.Source
} catch {
  Write-Host "vcpkg not in PATH, checking standard locations..."
}

if (-not $vcpkg) {
  $candidate = "C:\vcpkg\vcpkg.exe"
  if (Test-Path $candidate) {
    $vcpkg = $candidate
    Write-Host "Found vcpkg at: $vcpkg"
  }
}

if (-not $vcpkg) {
  Write-Error "vcpkg not found. Expected in PATH or at C:\vcpkg\vcpkg.exe"
  exit 1
}

if (-not (Test-Path $vcpkg)) {
  Write-Error "vcpkg executable not accessible at: $vcpkg"
  exit 1
}

Write-Host "Using vcpkg from: $vcpkg" -ForegroundColor Green
Write-Host "vcpkg version:" -ForegroundColor Green
& $vcpkg --version

Write-Host "Installing OpenSSL via vcpkg..." -ForegroundColor Green
& $vcpkg install openssl:x64-windows-static-md

if ($LASTEXITCODE -ne 0) {
  Write-Error "vcpkg installation failed with exit code: $LASTEXITCODE"
  exit $LASTEXITCODE
}

Write-Host "OpenSSL installation completed successfully" -ForegroundColor Green
