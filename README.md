# kreuzberg-dev/actions

Shared GitHub Actions composite actions and reusable workflows for the kreuzberg-dev polyrepo.

## Actions

### Setup

| Action | Description |
|--------|-------------|
| `setup-rust` | Rust toolchain with sccache, llvm-cov, cross-compilation targets |
| `setup-python-env` | Python environment with uv and caching |
| `setup-node-workspace` | Node.js workspace with pnpm |
| `setup-openssl` | Cross-platform OpenSSL (Linux, macOS, Windows) |
| `setup-maven` | Maven 3.x with settings.xml |
| `setup-go-cgo-env` | Go CGO environment for FFI builds |
| `setup-r` | R environment |
| `install-task` | [Task](https://taskfile.dev) runner |
| `install-wasi-sdk` | WASI SDK for WebAssembly |

### Build

| Action | Description |
|--------|-------------|
| `build-rust-ffi` | Rust FFI library (cdylib) with error diagnostics |
| `build-and-cache-binding` | Language binding build with intelligent caching |
| `build-python-wheels` | Python wheels via cibuildwheel/maturin |
| `build-node-napi` | Node.js NAPI-RS native modules |
| `build-ruby-gem` | Platform-specific Ruby gems |
| `build-php-extension` | PHP extensions |
| `build-wasm-package` | WebAssembly packages |
| `build-rust-cli` | Rust CLI binaries |
| `build-homebrew-bottle` | Homebrew bottle tarballs from CLI binaries |

### Publish

| Action | Description |
|--------|-------------|
| `publish-pypi` | Python packages to PyPI (with pypa/gh-action-pypi-publish) |
| `publish-npm` | npm packages (.tgz or directory mode) |
| `publish-crates` | Rust crates to crates.io (OIDC auth) |
| `publish-rubygems` | Ruby gems to RubyGems.org |
| `publish-maven` | Java artifacts to Maven Central |
| `publish-nuget` | .NET packages to NuGet |
| `publish-packagist` | PHP packages to Packagist |
| `publish-hex` | Elixir packages to Hex.pm |
| `publish-homebrew` | Homebrew formula updates with bottle hashes |
| `publish-github-release` | GitHub releases with artifact uploads |

### Release Infrastructure

| Action | Description |
|--------|-------------|
| `prepare-release-metadata` | Extract tag/version/ref/targets from workflow events |
| `validate-versions` | Cross-manifest version consistency checks |
| `retag-for-republish` | Delete and recreate Git tags for republishing |
| `generate-elixir-checksums` | RustlerPrecompiled NIF checksum generation |
| `check-registry` | Check if a package version exists on any registry |
| `wait-for-package` | Poll registries until a version becomes available |

### Utility

| Action | Description |
|--------|-------------|
| `free-disk-space-linux` | Free disk space on Linux runners |
| `cache-binding-artifact` | Generic artifact caching for compiled bindings |
| `cleanup-rust-cache` | Clean Rust build artifacts |
| `restore-cargo-cache` | Restore Cargo cache |
| `test-java-ffi` | Java Panama FFI test setup |

## Reusable Workflows

| Workflow | Description |
|----------|-------------|
| `reusable-validate-pr.yml` | PR title conventional commit validation |
| `reusable-validate-issues.yml` | Issue title validation |
| `reusable-check-registries.yml` | Matrix registry checks (replaces N separate check jobs) |
| `reusable-python-publish.yml` | Python package build and PyPI publish |
| `reusable-python-lint.yml` | Python linting via uv + prek |

## Usage

### Composite actions

```yaml
- uses: kreuzberg-dev/actions/setup-rust@v1
  with:
    use-sccache: "true"

- uses: kreuzberg-dev/actions/publish-npm@v1
  with:
    packages-dir: dist
    dry-run: "false"
```

### Reusable workflows

```yaml
jobs:
  validate-pr:
    uses: kreuzberg-dev/actions/.github/workflows/reusable-validate-pr.yml@main

  publish:
    uses: kreuzberg-dev/actions/.github/workflows/reusable-python-publish.yml@main
    with:
      package-name: my-package
```

## Development

```bash
# Install dependencies
task setup

# Run tests (281 tests)
task test

# Lint
task lint
```

All action scripts are Python 3.10+ with full pytest coverage, ruff linting, and mypy strict type checking.
