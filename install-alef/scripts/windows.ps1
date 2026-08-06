$ErrorActionPreference = "Stop"


$installRef = $args[0]
if ([string]::IsNullOrWhiteSpace($installRef)) {
  throw "Usage: windows.ps1 <installRef>"
}

$alefBinDir = "$env:USERPROFILE\AppData\Local\alef"
New-Item -ItemType Directory -Force -Path $alefBinDir | Out-Null
$alefExe = "$alefBinDir\alef.exe"

function Ensure-Cargo {
  if (Get-Command cargo -ErrorAction SilentlyContinue) { return }
  Write-Output "cargo not found - bootstrapping minimal Rust toolchain via rustup..."
  $rustupInit = "$env:TEMP\rustup-init.exe"
  Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile $rustupInit
  & $rustupInit --default-toolchain stable --profile minimal -y --no-modify-path
  if ($LASTEXITCODE -ne 0) { throw "rustup-init failed with exit code $LASTEXITCODE" }
  $env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
}

function Build-FromSource {
  param([string] $ref)
  Ensure-Cargo
  $env:CARGO_INSTALL_ROOT = $alefBinDir
  if ($ref -eq "main") {
    Write-Output "Building alef from main branch via cargo install..."
    cargo install --git https://github.com/xberg-io/alef --branch main --locked --force alef
  } else {
    Write-Output "Building alef v$ref from source via cargo install --tag..."
    cargo install --git https://github.com/xberg-io/alef --tag "v$ref" --locked --force alef
    if ($LASTEXITCODE -ne 0) {
      Write-Output "Tag build failed; falling back to main branch..."
      cargo install --git https://github.com/xberg-io/alef --branch main --locked --force alef
    }
  }
  $built = "$alefBinDir\bin\alef.exe"
  if (Test-Path $built) {
    Move-Item -Force -Path $built -Destination $alefExe
  } elseif (-not (Test-Path $alefExe)) {
    throw "cargo install did not produce alef.exe at $built"
  }
}

function Install-FromRelease {
  param([string] $version)
  $zipPath = "$alefBinDir\alef.zip"
  # alef publishes the msvc target (its release matrix builds on windows-latest, whose default
  # toolchain is msvc); the -gnu name this used to request never existed, so every Windows run
  # fell through to the API lookup below. ~keep
  $directUrl = "https://github.com/xberg-io/alef/releases/download/v$version/alef-x86_64-pc-windows-msvc.zip"

  try {
    Invoke-WebRequest -Uri $directUrl -OutFile $zipPath
  } catch {
    $headers = @{}
    if ($env:GITHUB_TOKEN) {
      $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
      $headers["X-GitHub-Api-Version"] = "2022-11-28"
    }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/xberg-io/alef/releases/tags/v$version" -Headers $headers
    $asset = $release.assets | Where-Object { $_.name -match "windows.*\.zip" } | Select-Object -First 1
    if (-not $asset) {
      throw "Could not find Windows release for alef v$version"
    }
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
  }

  $extractDir = "$alefBinDir\extract"
  if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
  New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
  Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
  Remove-Item $zipPath

  $found = Get-ChildItem -Path $extractDir -Recurse -Filter "alef.exe" | Select-Object -First 1
  if (-not $found) {
    throw "alef.exe not found in extracted archive at $extractDir"
  }
  Move-Item -Force -Path $found.FullName -Destination $alefExe
  Remove-Item -Recurse -Force $extractDir
}

if ($installRef -eq "main") {
  Build-FromSource -ref "main"
} else {
  try {
    Install-FromRelease -version $installRef
  } catch {
    Write-Output "Release download failed: $_"
    Write-Output "Falling back to source build..."
    Build-FromSource -ref $installRef
  }
}

if (-not (Test-Path $alefExe)) {
  throw "Failed to install alef.exe at $alefExe"
}
Write-Output "Alef is ready at $alefExe"
