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
  $env:CARGO_INSTALL_ROOT = $alefBinDir
  cargo install --git https://github.com/kreuzberg-dev/alef --locked --bin alef
  "$alefBinDir\bin" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
  exit 0
}

# Resolve "latest" — check alef.toml for a pinned version first, then fall back to GitHub
if ($alefVersion -eq "latest") {
  if (Test-Path "alef.toml") {
    # Read top-level version key (before any [section] header)
    $pinned = $null
    foreach ($line in Get-Content "alef.toml") {
      if ($line -match '^\[') { break }
      if ($line -match '^\s*version\s*=\s*"([^"]+)"') {
        $pinned = $Matches[1]; break
      }
    }
    if ($pinned) {
      Write-Output "Using pinned version from alef.toml: $pinned"
      $alefVersion = $pinned
    }
  }
  if ($alefVersion -eq "latest") {
    # Walk back through recent releases until we find a tag with a Windows
    # binary uploaded — covers the race window between tagging a new
    # release and the publish workflow finishing the binary build.
    $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/kreuzberg-dev/alef/releases?per_page=10"
    foreach ($rel in $releases) {
      $candidate = $rel.tag_name -replace '^v', ''
      $url = "https://github.com/kreuzberg-dev/alef/releases/download/v$candidate/alef-x86_64-pc-windows-gnu.zip"
      try {
        Invoke-WebRequest -Uri $url -Method Head -UseBasicParsing | Out-Null
        $alefVersion = $candidate
        Write-Output "Resolved latest installable version: $alefVersion"
        break
      } catch {
        Write-Output "Tag v$candidate has no Windows binary yet — trying previous release"
      }
    }
    if ($alefVersion -eq "latest") {
      throw "No recent alef release has a Windows binary"
    }
  }
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

if (-not (Test-Path $alefExe)) {
  throw "Failed to install alef.exe at $alefExe"
}
Write-Output "Alef installed at $alefExe"

"$alefBinDir" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
