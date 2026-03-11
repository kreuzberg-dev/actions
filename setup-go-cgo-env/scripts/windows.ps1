$ErrorActionPreference = "Stop"

function ConvertTo-Msys2Path {
  param([string]$WindowsPath)
  $normalized = $WindowsPath -replace '\\', '/'
  if ($normalized -match '^([A-Za-z]):(.*)$') {
    $drive = $matches[1].ToLower()
    $path = $matches[2]
    return "/$drive$path"
  }
  return $normalized
}

$ffiLibDir = $args[0]
if ([string]::IsNullOrWhiteSpace($ffiLibDir)) { $ffiLibDir = "target/release" }

$ffiCrateDir = $args[1]
if ([string]::IsNullOrWhiteSpace($ffiCrateDir)) { $ffiCrateDir = "crates/kreuzberg-ffi" }

$ffiLibName = $args[2]
if ([string]::IsNullOrWhiteSpace($ffiLibName)) { $ffiLibName = "kreuzberg_ffi" }

$ffiHeaderPath = $args[3]

$repoRoot = $env:GITHUB_WORKSPACE
$ffiPath = Join-Path $repoRoot $ffiLibDir

$gnuTargetPath = Join-Path $repoRoot "target/x86_64-pc-windows-gnu/release"
if (Test-Path $gnuTargetPath) {
  $ffiPath = $gnuTargetPath
  Write-Host "Using Windows GNU target path: $ffiPath"
} elseif (-not (Test-Path $ffiPath)) {
  throw "Error: FFI library directory not found: $ffiPath"
}

$msys2RepoRoot = ConvertTo-Msys2Path $repoRoot
$pkgConfigDir = "$msys2RepoRoot/$ffiCrateDir"

if ([string]::IsNullOrWhiteSpace($env:PKG_CONFIG_PATH)) {
  $pkgConfigPath = $pkgConfigDir
} else {
  $pkgConfigPath = "${pkgConfigDir}:$($env:PKG_CONFIG_PATH)"
}

$env:PATH = "${ffiPath};$($env:PATH)"

if (Test-Path $ffiPath) {
  Add-Content -Path $env:GITHUB_PATH -Value $ffiPath -Encoding utf8
}

$msys2FfiPath = ConvertTo-Msys2Path $ffiPath
$msys2IncludePath = "$msys2RepoRoot/$ffiCrateDir/include"

# Verify FFI header if path specified
if (-not [string]::IsNullOrWhiteSpace($ffiHeaderPath)) {
  $headerFullPath = Join-Path $repoRoot $ffiHeaderPath
  if (-not (Test-Path $headerFullPath)) {
    Write-Host "Warning: FFI header not found at $headerFullPath"
  } else {
    Write-Host "FFI header verified at $ffiHeaderPath"
  }
}

$mingwBin = "C:\msys64\mingw64\bin"
if (Test-Path (Join-Path $mingwBin "x86_64-w64-mingw32-gcc.exe")) {
  $env:PATH = "${mingwBin};$($env:PATH)"
  Add-Content -Path $env:GITHUB_PATH -Value $mingwBin -Encoding utf8
  $env:CC = "x86_64-w64-mingw32-gcc"
  $env:CXX = "x86_64-w64-mingw32-g++"
  $env:AR = "x86_64-w64-mingw32-ar"
  $env:RANLIB = "x86_64-w64-mingw32-ranlib"
  Write-Host "Using MinGW64 toolchain: $mingwBin"
}

$cgoEnabled = "1"
$cgoCflags = "-I$msys2IncludePath"
$cgoLdflags = "-L$msys2FfiPath"

Add-Content -Path $env:GITHUB_ENV -Value "PKG_CONFIG_PATH=$pkgConfigPath"
Add-Content -Path $env:GITHUB_ENV -Value "CGO_ENABLED=$cgoEnabled"
Add-Content -Path $env:GITHUB_ENV -Value "CGO_CFLAGS=$cgoCflags"
if ($env:CC) { Add-Content -Path $env:GITHUB_ENV -Value "CC=$env:CC" }
if ($env:CXX) { Add-Content -Path $env:GITHUB_ENV -Value "CXX=$env:CXX" }
if ($env:AR) { Add-Content -Path $env:GITHUB_ENV -Value "AR=$env:AR" }
if ($env:RANLIB) { Add-Content -Path $env:GITHUB_ENV -Value "RANLIB=$env:RANLIB" }

@"
CGO_LDFLAGS=$cgoLdflags
"@ | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding UTF8

Write-Host "Go cgo environment configured (Windows)"
Write-Host "  FFI Library Path: $ffiPath"
Write-Host "  CGO_LDFLAGS: $cgoLdflags"
