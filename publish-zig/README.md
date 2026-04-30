# publish-zig

"Publish" a Zig package via Git tag.

Zig has no central package registry. Consumers reference packages via
`zig fetch --save <tarball-url>` against a Git tag tarball, with a
`hash` field in their `build.zig.zon`. This action validates the manifest,
verifies the tag, and computes the tarball SHA-256 for downstream consumers.

## Usage

```yaml
jobs:
  publish-zig:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: kreuzberg-dev/actions/publish-zig@v1
        with:
          working-directory: packages/zig
          update-release-notes: 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

When `update-release-notes: 'true'` and a `GH_TOKEN` is in scope, the
action appends a Zig fetch snippet to the GitHub release body so users
can copy-paste the URL + SHA into their own `build.zig.zon`.

## Outputs

| Name | Description |
|---|---|
| `tarball-url` | Canonical GitHub tag tarball URL |
| `tarball-sha256` | SHA-256 of the tarball, for `build.zig.zon` `hash` field |

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `working-directory` | no | `.` | Path to `build.zig.zon`. |
| `tag` | no | `${GITHUB_REF_NAME}` (when on a tag) | Git tag to validate. |
| `zig-version` | no | `0.13.0` | Zig version (`mlugg/setup-zig`). |
| `setup-zig` | no | `true` | Install Zig if not present. |
| `update-release-notes` | no | `false` | Append fetch snippet to GH release body. Requires `GH_TOKEN`. |
| `dry-run` | no | `false` | Skip release-notes update. |
