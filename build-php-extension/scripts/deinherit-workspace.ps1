<#
.SYNOPSIS
Rewrites a crate manifest so it no longer inherits anything from a workspace root.

.DESCRIPTION
The PHP extension is built from a copy of the crate placed outside the workspace, so
every `workspace = true` in its manifest refers to a root cargo can no longer find
("failed to find a workspace root"). Inherited keys are replaced with the concrete
values from the workspace manifest rather than merely deleted, because keys such as
`version`, `edition` and `license` are required for the package to parse at all.

Three spellings of inheritance are recognised: the dotted form
(`version.workspace = true`, which is what cargo and alef emit), the inline-table form
(`version = { workspace = true }`), and the bare form (`workspace = true` under a table
such as `[lints]`, which has no key to resolve and is dropped).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CrateManifest,
    [Parameter(Mandatory = $true)][string]$WorkspaceManifest
)

$ErrorActionPreference = "Stop"

# ~keep `readme` and `license-file` name files that live beside the workspace manifest and
# are not copied into the out-of-workspace build directory, so inheriting their values
# would point cargo at paths that do not exist. They are publish-only metadata that this
# build does not need; drop them instead of resolving them.
$PathValuedPackageKeys = @("readme", "license-file")

$TableHeader = '^\s*\[([^\]]+)\]\s*$'
$Comment = '^\s*#'
$Assignment = '^\s*([A-Za-z0-9_.-]+)\s*=\s*(\S.*?)\s*$'
$DottedInherit = '^\s*([A-Za-z0-9_-]+)\s*\.\s*workspace\s*=\s*true\s*$'
$InlineInherit = '^\s*([A-Za-z0-9_-]+)\s*=\s*\{\s*workspace\s*=\s*true\s*,?\s*\}\s*$'
$BareInherit = '^\s*workspace\s*=\s*true\s*$'
$AnyInherit = 'workspace\s*=\s*true'
$DependencyTable = '(^|\.)(build-|dev-)?dependencies$'

function Read-TomlTable {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$TableName
    )

    $values = @{}
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        return $values
    }

    $inTable = $false
    foreach ($line in (Get-Content -LiteralPath $ManifestPath)) {
        if ($line -match $TableHeader) {
            $inTable = $Matches[1].Trim() -eq $TableName
            continue
        }
        if (-not $inTable -or $line -match $Comment) {
            continue
        }
        if ($line -match $Assignment) {
            $values[$Matches[1]] = $Matches[2]
        }
    }

    return $values
}

$packageValues = Read-TomlTable -ManifestPath $WorkspaceManifest -TableName "workspace.package"
$dependencyValues = Read-TomlTable -ManifestPath $WorkspaceManifest -TableName "workspace.dependencies"

$section = ""
$rewritten = New-Object System.Collections.Generic.List[string]

foreach ($line in (Get-Content -LiteralPath $CrateManifest)) {
    if ($line -match $TableHeader) {
        $section = $Matches[1].Trim()
        $rewritten.Add($line)
        continue
    }

    # ~keep Comments are copied verbatim and never inspected: alef-generated manifests
    # carry prose that mentions `workspace = true`, and treating that as inheritance
    # would fail the build on a comment.
    if ($line -match $Comment) {
        $rewritten.Add($line)
        continue
    }

    $key = $null
    if ($line -match $DottedInherit) {
        $key = $Matches[1]
    } elseif ($line -match $InlineInherit) {
        $key = $Matches[1]
    } elseif ($line -match $BareInherit) {
        continue
    } elseif ($line -match $AnyInherit) {
        throw "Cannot de-inherit '$($line.Trim())' in ${CrateManifest}: unsupported workspace inheritance form"
    }

    if ($null -eq $key) {
        $rewritten.Add($line)
        continue
    }

    if ($section -match $DependencyTable) {
        if (-not $dependencyValues.ContainsKey($key)) {
            throw "Dependency '$key' inherits from the workspace but [workspace.dependencies] in $WorkspaceManifest has no entry for it"
        }
        $rewritten.Add("$key = $($dependencyValues[$key])")
    } elseif ($PathValuedPackageKeys -contains $key) {
        continue
    } elseif ($packageValues.ContainsKey($key)) {
        $rewritten.Add("$key = $($packageValues[$key])")
    }
}

Set-Content -LiteralPath $CrateManifest -Value $rewritten
