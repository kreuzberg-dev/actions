# publish-scoop-manifests

Renders Scoop app manifests from per-app templates, substituting the release
version, tag, and the SHA256 of each Windows release asset, then writes them
into a checked-out Scoop bucket. The Windows counterpart of
`publish-homebrew-source-formulas`.

Scoop manifests point straight at the prebuilt `*-pc-windows-msvc.zip` release
assets, so a release only ever needs the version bumped and the hashes
recomputed — this action does both. Committing and pushing the bucket is the
calling workflow's job, because the bot identity is repo-specific.

Every rendered manifest is parsed as JSON before it is written; a template that
renders to malformed JSON fails the step rather than reaching the bucket, where
it would break `scoop update` for every app in it, not just the one being
published.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `bucket-dir` | yes | — | Path to a checked-out Scoop bucket repository. Must contain `bucket/`. |
| `config-file` | yes | — | Path, relative to the source repo, of the JSON config describing each manifest. |
| `tag` | yes | — | Git tag for the release (e.g. `v3.4.0-rc.42`). |
| `version` | yes | — | Semantic version (e.g. `3.4.0-rc.42`). Scoop versions carry no `v` prefix. |
| `github-repo` | yes | — | Source repository for `gh release download` (e.g. `xberg-io/html-to-markdown`). |
| `dry-run` | no | `false` | Tolerate a missing release or asset: substitute a zero-SHA placeholder and warn, so the rendered shape can be diffed before the release exists. |
| `token` | no | `${{ github.token }}` | GitHub token with read access for `gh release download`. |

## Outputs

| Name | Description |
|---|---|
| `manifests-changed` | Newline-separated list of manifest paths written into `bucket-dir/bucket/`. |

## Config schema

```json
{
  "manifests": [
    {
      "name": "html-to-markdown",
      "template": "scripts/publish/html-to-markdown.json.tmpl",
      "assets": {
        "win_x64_sha": "cli-x86_64-pc-windows-msvc.zip"
      }
    }
  ]
}
```

`name` becomes `bucket/<name>.json`. Each key under `assets` becomes a template
variable bound to that asset's SHA256; the value is the release-asset filename,
which may itself interpolate `${tag}` or `${version}`.

## Templates

Templates are rendered with Python's `string.Template`, so `${version}`,
`${tag}`, and each `assets` key are substituted.

Scoop's own `autoupdate` blocks contain a literal `$version` that Scoop expands
at update time. **Write those as `$$version`** — `string.Template` collapses
`$$` to a single `$`, so the published manifest keeps Scoop's placeholder. An
unescaped `$version` inside an `autoupdate` URL is replaced with the current
release's version and silently freezes autoupdate on it.

```json
{
  "version": "${version}",
  "architecture": {
    "64bit": {
      "url": "https://github.com/xberg-io/html-to-markdown/releases/download/${tag}/cli-x86_64-pc-windows-msvc.zip",
      "hash": "${win_x64_sha}",
      "extract_dir": "cli-x86_64-pc-windows-msvc"
    }
  },
  "bin": "html-to-markdown.exe",
  "autoupdate": {
    "architecture": {
      "64bit": {
        "url": "https://github.com/xberg-io/html-to-markdown/releases/download/v$$version/cli-x86_64-pc-windows-msvc.zip"
      }
    }
  }
}
```

Omit `extract_dir` when the zip has no wrapping directory.

## Usage

```yaml
- uses: xberg-io/actions/publish-scoop-manifests@v1
  with:
    bucket-dir: ${{ github.workspace }}/scoop-bucket
    config-file: scripts/publish/scoop.json
    tag: ${{ needs.prepare.outputs.tag }}
    version: ${{ needs.prepare.outputs.version }}
    github-repo: ${{ github.repository }}
    dry-run: ${{ needs.prepare.outputs.dry_run }}
```
