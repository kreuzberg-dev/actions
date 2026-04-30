# publish-swift

"Publish" a Swift Package to the Swift Package Index.

Swift Package Manager has no central registry — packages are consumed
directly from Git tags. This action validates that the package and tag
are well-formed and pings the Swift Package Index to expedite re-indexing.

## What this action does

1. Validates `Package.swift` (full parse if `swift` CLI is available; sanity
   check otherwise).
2. Verifies the Git tag is present on `origin`.
3. Pings https://swiftpackageindex.com/owner/repo to warm the SPI cache.

## What this action does NOT do

- **First-time submission to the Swift Package Index.** That requires a
  manual PR to https://github.com/SwiftPackageIndex/PackageList. After the
  initial submission, SPI auto-discovers new tags.
- **Push to a registry.** SPM has no central registry; consumers reference
  the Git tag directly via `.package(url: ..., from: "x.y.z")`.

## Usage

```yaml
jobs:
  publish-swift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: kreuzberg-dev/actions/publish-swift@v1
        with:
          working-directory: packages/swift
```

On a tag push (`refs/tags/v0.14.1`), the tag is auto-detected from
`GITHUB_REF_NAME`. For workflow_dispatch with a custom tag, pass it
explicitly:

```yaml
- uses: kreuzberg-dev/actions/publish-swift@v1
  with:
    tag: v0.14.1
    working-directory: packages/swift
```

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `working-directory` | no | `.` | Path to `Package.swift`. |
| `tag` | no | `${GITHUB_REF_NAME}` (when on a tag) | Git tag to validate. |
| `package-url` | no | `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}` | Canonical Git URL. |
| `ping-spi` | no | `true` | Whether to warm the SPI cache. |
| `setup-swift` | no | `false` | Install Swift via `swift-actions/setup-swift`. |
| `swift-version` | no | `5.10` | Swift version when `setup-swift=true`. |
| `dry-run` | no | `false` | Skip the SPI ping. |
