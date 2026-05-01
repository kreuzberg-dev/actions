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
| `package-php-pie` | PIE-conventional binary archive from a built PHP extension |

### Publish

All publish actions are idempotent: re-running on an already-published version
exits 0 (output `skipped=true` where applicable). Most accept `dry-run: 'true'`
to print the command without executing.

| Action | Target | Auth | Description |
|--------|--------|------|-------------|
| `publish-pypi` | PyPI | OIDC trusted publisher | Python packages via `pypa/gh-action-pypi-publish` |
| `publish-npm` | npm | `NPM_TOKEN` | `.tgz` files from a directory or direct `package-dir`; supports `npm-tag` (`latest`/`next`/`rc`) |
| `publish-crates` | crates.io | OIDC (`rust-lang/crates-io-auth-action`) | Rust crates with dependency-ordered publishing |
| `publish-rubygems` | RubyGems.org | `GEM_HOST_API_KEY` or trusted publisher | Ruby gems |
| `publish-maven` | Maven Central | `MAVEN_USERNAME` + `MAVEN_PASSWORD` + GPG | Java / `pom.xml` projects via `mvn deploy` |
| `publish-maven-gradle` | Maven Central | same as `publish-maven` | Kotlin / Java-Gradle via `gradle publishAndReleaseToMavenCentral` (or any task); imports GPG into the agent |
| `publish-nuget` | NuGet.org | OIDC trusted publisher (preferred) or `NUGET_API_KEY` | .NET `.nupkg` files |
| `publish-packagist` | Packagist | `PACKAGIST_API_TOKEN` | Triggers re-index for PHP packages auto-discovered from Git tags |
| `publish-hex` | Hex.pm | `HEX_API_KEY` | Elixir packages via `mix hex.publish` |
| `publish-gleam` | Hex.pm | `HEX_API_KEY` | Gleam packages via `gleam publish`; reuses the same `HEX_API_KEY` as `publish-hex` |
| `publish-pub` | pub.dev | OIDC trusted publisher | Dart packages; requires a one-time pub.dev claim of the package |
| `publish-swift` | Swift Package Index | none | Validates `Package.swift` + tag, pings SPI to expedite re-index |
| `publish-zig` | Git tag | none | Validates `build.zig.zon` + tag; emits the tarball SHA-256 downstream consumers need for `build.zig.zon`'s `hash` field; can append a fetch snippet to the GH release notes |
| `publish-homebrew` | Homebrew tap | `HOMEBREW_TOKEN` | Formula updates with bottle hashes |
| `publish-github-release` | GitHub Releases | `GITHUB_TOKEN` | Release-asset uploads |

**Idempotency contract.** Each `publish-*` action either:

1. Detects "already published" output from the underlying tool (case-insensitive grep) and exits 0 with `skipped=true`, **or**
2. Has no side effect to be idempotent about — `publish-swift` and `publish-zig` are Git-tag-only and re-running them is naturally a no-op.

Pair with `check-registry` to skip the publish step entirely when the version
is already live (pre-flight gate; faster than relying on publish-time
idempotency, since the build/auth steps are skipped too). `check-registry`
covers `pypi`, `npm`, `wasm`, `rubygems`, `hex`, `maven`, `nuget`, `cratesio`,
`packagist`, `homebrew`, and `github-release` (the last for `swift`/`zig`
tag-based publishes).

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
