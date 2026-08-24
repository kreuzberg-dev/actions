<#
.SYNOPSIS
Removes residual relative `path = "..."` keys from an out-of-workspace crate manifest.

.DESCRIPTION
The extension is built from a copy of the binding crate alone; sibling crates it depends
on by path are not copied. A surviving `path = "../<core>"` therefore resolves against the
build directory rather than the workspace and cargo bails with "failed to read
<build-dir>/<core>/Cargo.toml". Dropping the key while keeping `version` lets the same
dependency resolve from the registry instead.

This is a no-op once `rewrite-native-deps` has already rewritten the path-deps, and it is
scoped to dependency tables so `[lib]`/`[[bin]]` paths are left alone.

This mirrors `strip_internal_paths` in `build-out-of-workspace.sh`, which covers the
Linux/macOS branch of the same action.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CrateManifest
)

$ErrorActionPreference = "Stop"

$AnyHeader = '^\s*\['
$DependencyHeader = '^\s*\[(build-|dev-)?dependencies(\.[^\]]+)?\]\s*$'
$TargetDependencyHeader = '^\s*\[target\.[^\]]+\.(build-|dev-)?dependencies(\.[^\]]+)?\]\s*$'

# ~keep Only relative paths are matched: a value starting with `.` or containing a `/`.
# An absolute registry-style value has no `path` key to begin with, and a bare `path`
# without a separator is not a sibling reference.
$RelativePath = '(,\s*)?path\s*=\s*"(\.[^"]*|[^"]*/[^"]*)"(\s*,)?'

# ~keep A stripped key between two others leaves the surrounding commas orphaned, so the
# separator is kept only when the match consumed one on each side.
$DropPath = [System.Text.RegularExpressions.MatchEvaluator] {
    param([System.Text.RegularExpressions.Match]$RegexMatch)
    if ($RegexMatch.Groups[1].Success -and $RegexMatch.Groups[3].Success) { "," } else { "" }
}

$inDependencies = $false
$rewritten = New-Object System.Collections.Generic.List[string]

foreach ($line in (Get-Content -LiteralPath $CrateManifest)) {
    if ($line -match $AnyHeader) {
        $inDependencies = ($line -match $DependencyHeader) -or ($line -match $TargetDependencyHeader)
    }

    if ($inDependencies -and $line.Contains("path")) {
        $rewritten.Add([regex]::Replace($line, $RelativePath, $DropPath))
        continue
    }

    $rewritten.Add($line)
}

Set-Content -LiteralPath $CrateManifest -Value $rewritten
