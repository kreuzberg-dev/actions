# package-php-pie

Wraps `alef publish package --lang php` to produce a PIE-conventional pre-built
binary archive ready for distribution. All filename formatting and archive
construction logic lives in alef; this action is a thin orchestration wrapper
that validates inputs, invokes alef, locates the produced archive, and exposes
its path, name, and SHA-256 as step outputs.

## Prerequisites

Run [`kreuzberg-dev/actions/install-alef`](../install-alef/README.md) before
this action so the `alef` CLI is on `PATH`. The extension binary itself must
already be built — use
[`kreuzberg-dev/actions/build-php-extension`](../build-php-extension) for that.

## PIE filename convention

PIE (PHP Installer for Extensions) expects pre-built archives to follow a
predictable naming scheme so the installer can select the correct binary for
the running PHP environment:

- **Unix** — `php_{ext}-{version}_php{phpVer}-{arch}-{os}-{libc}-{ts}.tgz`
  (e.g. `php_html_to_markdown-0.3.0_php8.4-x86_64-linux-gnu-nts.tgz`)
- **Windows** — `php_{ext}-{version}-{phpVer}-{ts}-{compiler}-{arch}.zip`
  (e.g. `php_html_to_markdown-0.3.0-8.4-nts-vs17-x86_64.zip`)

A SHA-256 sidecar `{archive}.sha256` is always written alongside the archive by
alef and is read by this action to populate the `sha256` output without a
second hash pass.

For the full PIE specification see <https://github.com/php/pie>.

## `composer.json` — `download-url-method`

Consumers of the produced archives must declare `pre-packaged-binary` as their
`download-url-method` in their root `composer.json` so PIE knows to fetch
pre-built binaries from GitHub Releases rather than attempting to compile from
source:

```json
{
  "extra": {
    "php-ext": {
      "extension-name": "html_to_markdown",
      "download-url-method": "pre-packaged-binary"
    }
  }
}
```

## Usage

```yaml
jobs:
  package-php:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up PHP
        uses: shivammathur/setup-php@v2
        with:
          php-version: "8.4"

      - name: Set up Rust
        uses: kreuzberg-dev/actions/setup-rust@v1
        with:
          targets: x86_64-unknown-linux-gnu

      - name: Install alef
        uses: kreuzberg-dev/actions/install-alef@v1

      - name: Build PHP extension
        id: build
        uses: kreuzberg-dev/actions/build-php-extension@v1
        with:
          crate-name: html-to-markdown-php
          lib-name: html_to_markdown

      - name: Package as PIE archive
        id: package
        uses: kreuzberg-dev/actions/package-php-pie@v1
        with:
          php-version: "8.4"
          php-ts: "nts"
          target: x86_64-unknown-linux-gnu
          output-dir: dist/php-package

      - name: Upload archive
        uses: actions/upload-artifact@v4
        with:
          name: ${{ steps.package.outputs.archive-name }}
          path: ${{ steps.package.outputs.archive-path }}
```

### Windows example

```yaml
      - name: Package as PIE archive (Windows)
        uses: kreuzberg-dev/actions/package-php-pie@v1
        with:
          php-version: "8.4"
          php-ts: "nts"
          target: x86_64-pc-windows-msvc
          windows-compiler: vs17
          output-dir: dist/php-package
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `php-version` | yes | — | PHP minor version, e.g. `"8.4"` |
| `php-ts` | no | `nts` | Thread-safety mode: `nts` or `ts` |
| `target` | yes | — | Rust target triple, e.g. `x86_64-unknown-linux-gnu` |
| `windows-compiler` | no* | `""` | Windows compiler tag, e.g. `vs17`. Required when `target` contains `windows`. |
| `php-libc` | no | `""` | Linux libc override: `glibc` or `musl`. Auto-detected from target if absent. |
| `output-dir` | no | `dist/php-package` | Directory to place the archive in |
| `version` | no | `""` | Version string. Auto-detected from `Cargo.toml` if absent. |

## Outputs

| Output | Description |
|--------|-------------|
| `archive-path` | Full path to the produced `.tgz` or `.zip` archive |
| `archive-name` | Filename only (no directory component) |
| `sha256` | Hex-encoded SHA-256 of the archive |
