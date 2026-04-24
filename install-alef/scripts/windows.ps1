$ErrorActionPreference = "Stop"

$alefVersion = $args[0]
if ([string]::IsNullOrWhiteSpace($alefVersion)) {
  throw "Usage: windows.ps1 <alefVersion>"
}

$alefBinDir = "$env:USERPROFILE\AppData\Local\alef"
New-Item -ItemType Directory -Force -Path $alefBinDir | Out-Null

$alefExe = "$alefBinDir\alef.exe"

if (Test-Path $alefExe) {
  Write-Output "Alef already installed at $alefExe"
  "$alefBinDir" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
  exit 0
}

if ($alefVersion -eq "main") {
  Write-Output "Installing alef from main branch via cargo install..."
  if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "cargo not found - required for installing from main branch"
  }
  $env:CARGO_INSTALL_ROOT = "$alefBinDir\.."
  cargo install --git https://github.com/kreuzberg-dev/alef --locked --bin alef
  "$alefBinDir" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
  exit 0
}

# Resolve "latest" to actual version
if ($alefVersion -eq "latest") {
  $release = Invoke-RestMethod -Uri "https://api.github.com/repos/kreuzberg-dev/alef/releases/latest"
  $alefVersion = $release.tag_name -replace '^v', ''
  Write-Output "Resolved latest version: $alefVersion"
}

$zipPath = "$alefBinDir\alef.zip"
$directUrl = "https://github.com/kreuzberg-dev/alef/releases/download/v$alefVersion/alef-x86_64-pc-windows-gnu.zip"

try {
  Invoke-WebRequest -Uri $directUrl -OutFile $zipPath
} catch {
  $headers = @{}
  if ($env:GITHUB_TOKEN) {
    $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
    $headers["X-GitHub-Api-Version"] = "2022-11-28"
  }
  $release = Invoke-RestMethod -Uri "https://api.github.com/repos/kreuzberg-dev/alef/releases/tags/v$alefVersion" -Headers $headers
  $asset = $release.assets | Where-Object { $_.name -match "windows.*\.zip" } | Select-Object -First 1

  if (-not $asset) {
    throw "Could not find Windows release for alef v$alefVersion"
  }

  Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
}

Expand-Archive -Path $zipPath -DestinationPath $alefBinDir -Force
Remove-Item $zipPath

"$alefBinDir" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
