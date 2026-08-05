$ErrorActionPreference = "Stop"

$taskVersion = $args[0]
if ([string]::IsNullOrWhiteSpace($taskVersion)) {
  $taskVersion = "latest"
}

$taskBinDir = $args[1]
if ([string]::IsNullOrWhiteSpace($taskBinDir)) {
  $taskBinDir = Join-Path $env:RUNNER_TEMP "task-bin"
}
New-Item -ItemType Directory -Force -Path $taskBinDir | Out-Null

$taskExe = "$taskBinDir\task.exe"

$headers = @{
  "X-GitHub-Api-Version" = "2022-11-28"
}
if ($env:GITHUB_TOKEN) {
  $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
}

# ~keep Unauthenticated api.github.com allows 60 requests/hour per source IP, shared by every job
# on that runner, so resolving "latest" through the API fails outright often enough to be a routine
# CI flake. Fall back to the /releases/latest redirect: a plain github.com request under a separate,
# far higher limit that needs no credentials.
function Resolve-LatestTag {
  try {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/go-task/task/releases/latest" -Headers $headers
    return $release.tag_name
  } catch {
    Write-Host "GitHub API lookup failed ($($_.Exception.Message)); falling back to the releases/latest redirect"
  }

  $response = Invoke-WebRequest -Uri "https://github.com/go-task/task/releases/latest" `
    -MaximumRedirection 0 -SkipHttpErrorCheck
  $location = $response.Headers["Location"]
  if ($location) {
    $tag = ([string]($location | Select-Object -First 1)).Split("/")[-1]
    if ($tag) {
      return $tag
    }
  }

  throw "Could not resolve the latest Task release"
}

if ($taskVersion -eq "latest") {
  $resolvedVersion = Resolve-LatestTag
} else {
  $resolvedVersion = $taskVersion
  if (-not $resolvedVersion.StartsWith("v")) {
    $resolvedVersion = "v$resolvedVersion"
  }
}

Write-Host "Installing Task $resolvedVersion"

# The asset name is stable across releases, so the download itself needs no API call. ~keep
$downloadUrl = "https://github.com/go-task/task/releases/download/$resolvedVersion/task_windows_amd64.zip"
$zipPath = "$taskBinDir\task.zip"

$maxAttempts = 3
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
  try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath
    break
  } catch {
    if ($attempt -eq $maxAttempts) {
      throw "Failed to download $downloadUrl after $maxAttempts attempts: $($_.Exception.Message)"
    }
    $wait = [Math]::Pow(2, $attempt)
    Write-Host "Download attempt $attempt failed; retrying in ${wait}s"
    Start-Sleep -Seconds $wait
  }
}

Expand-Archive -Path $zipPath -DestinationPath $taskBinDir -Force
Remove-Item $zipPath

if (-not (Test-Path $taskExe)) {
  throw "Task binary not found at $taskExe"
}

& $taskExe --version
"$taskBinDir" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
