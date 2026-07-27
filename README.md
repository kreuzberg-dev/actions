# xberg-io/actions

Shared GitHub Actions composite actions and reusable workflows for the xberg-io polyrepo.

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
| `setup-php` | PHP runtime setup |
| `setup-elixir` | Elixir / Erlang runtime setup |
| `setup-r` | R environment |
| `setup-chrome` | Chrome-compatible browser via `browser-actions/setup-chrome` (or aptmium on linux-arm64) |
| `setup-chromium` | Non-snap Chromium for headless e2e tests; uses Playwright browser installer; outputs `chromium-path` for direct binary use |
| `install-task` | [Task](https://taskfile.dev) runner, installed from the official Task release installer (`latest` by default) |
| `install-alef` | Alef CLI installation |
| `install-wasi-sdk` | WASI SDK for WebAssembly |
| `install-homebrew-linux` | Linuxbrew (Homebrew for Linux) for runners that need to build bottles |
| `setup-textlint` | textlint + the xberg-io standard rule set in one batched npm install |
| `setup-onnx-runtime-gpu` | Download and stage the GPU/CUDA build of ONNX Runtime; exports `ORT_DYLIB_PATH` + `LD_LIBRARY_PATH` |
| `configure-maven-gpg` | Prefer `gpg2` (shimmed as `gpg`) and patch legacy `--pinentry-mode loopback` two-arg form in `pom.xml` |

### Build

| Action | Description |
|--------|-------------|
| `build-rust-ffi` | Rust FFI library (cdylib) with error diagnostics |
| `build-and-cache-binding` | Language binding build with intelligent caching |
| `build-python-wheels` | Python wheels via cibuildwheel/maturin |
| `build-python-sdist` | Python sdist via maturin, with baked-in path-dep → registry rewrite for source installs |
| `build-node-napi` | Node.js NAPI-RS native modules |
| `build-ruby-gem` | Platform-specific Ruby gems |
| `build-php-extension` | PHP extensions |
| `build-wasm-package` | WebAssembly packages |
| `build-rust-cli` | Rust CLI binaries |
| `build-go-ffi` | Build the FFI crate for one Rust target and bundle lib + header into a tar.gz for Go cgo |
| `build-java-natives` | Build the FFI crate for one Rust target, stage at Panama FFM `native/{classifier}/` layout |
| `build-csharp-natives` | Build the FFI crate for one Rust target, stage at NuGet `runtimes/{rid}/native/` layout |
| `build-elixir-natives` | Cross-compile a Rustler NIF for one Rust target, package as RustlerPrecompiled tar.gz |
| `build-dart-package` | flutter_rust_bridge codegen + cargo build for the Dart package's Rust crate |
| `build-swift-package` | cargo build + sync swift-bridge generated headers/sources into the Swift package |
| `build-zig-package` | cargo build the FFI crate + `zig build` smoke check |
| `homebrew-build-bottles` | Real Homebrew bottles for one or more formulas via `brew install --build-bottle` + `brew bottle --json`; uploads tarballs to the GH release and saves bottle JSONs for the merge step |
| `homebrew-merge-bottles` | Aggregates per-platform bottle JSON manifests into formula `bottle do ... end` blocks (jq-driven, no brew needed on the runner); emits cellar values as Ruby symbols |
| `package-php-pie` | PIE-conventional binary archive from a built PHP extension |
| `rewrite-native-deps` | Rewrite a source package's workspace path-deps → registry version-deps via `alef publish prepare --require-registry` (embedded in `build-ruby-gem`/`build-php-extension`/`build-elixir-natives`/`build-python-sdist`) |
| `build-gpu-test-binary` | `cargo test --no-run` + JSON message parse to extract the executable for cross-runner GPU CI |

### Docs

| Action | Description |
|--------|-------------|
| `lint-docs` | Link check (lychee) + prose lint (textlint), with optional `alef snippets` validation of code examples. When `validate-snippets: "true"`, installs the `alef` CLI via `install-alef@v1` and runs `task docs:snippets:validate` (or falls back to `alef snippets validate --snippets docs/snippets --level syntax` when `task` is unavailable). Pin alef via the `alef-ref` input (defaults to `main`). |
| `build-docs` | Build the documentation site with [zensical](https://zensical.org). Sets up Python via `setup-python-env`, then runs `task docs:build:strict` (or `zensical build --strict --clean` as a fallback). `python-version` defaults to `3.13`; `strict` defaults to `true`. `docs-group` selects the uv dependency group containing the docs builder (default `doc`; pass `docs` for repos that use the plural name). |

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
| `publish-zig` | Git tag | none | Validates `build.zig.zon` + tag; emits the tarball SHA-256 downstream consumers need for `build.zig.zon`'s `hash` field; can append a fetch snippet to the GH release notes. Optional `multi-platform-ffi-dir` bundles per-RID FFI libs + rewrites `build.zig` so a single tarball serves all supported targets |
| `publish-homebrew-source-formulas` | Homebrew tap | `HOMEBREW_TOKEN` | Render source formulas from release assets |
| `publish-github-release` | GitHub Releases | `GITHUB_TOKEN` | Release-asset uploads |
| `publish-helm-chart` | OCI registry (GHCR, GAR, ECR, …) | username + password / token | Stamps `version`/`appVersion`, runs `helm dependency build` + `package` + `push`; idempotent on re-publish |

**Idempotency contract.** Each `publish-*` action either:

1. Detects "already published" output from the underlying tool (case-insensitive grep) and exits 0 with `skipped=true`, **or**
2. Has no registry side effect to be idempotent about — `publish-zig` is Git-tag-only and re-running it is naturally a no-op.

Pair with `check-registry` to skip the publish step entirely when the version
is already live (pre-flight gate; faster than relying on publish-time
idempotency, since the build/auth steps are skipped too). `check-registry`
covers `pypi`, `npm`, `wasm`, `rubygems`, `hex`, `maven`, `nuget`, `cratesio`,
`packagist`, `homebrew`, and `github-release`.

### Release Infrastructure

| Action | Description |
|--------|-------------|
| `prepare-release-metadata` | Extract tag/version/ref/targets from workflow events (alef-backed; emits 19 `release_*` flags incl. dart/swift/gleam/zig/kotlin) |
| `validate-versions` | Cross-manifest version consistency checks |
| `retag-for-republish` | Delete and recreate Git tags for republishing |
| `generate-elixir-checksums` | RustlerPrecompiled NIF checksum generation |
| `check-registry` | Check if a package version exists on any registry |
| `wait-for-package` | Poll registries until a version becomes available |
| `upload-release-assets` | Generic GH Release uploader; glob-expand a list of paths/patterns and upload with `--clobber` |
| `verify-release-assets` | Verify the GH Release contains every expected asset (fnmatch patterns, optional min size) |
| `finalize-release` | Edit GH Release from draft → published, set/clear prerelease, optionally create Go module tag |
| `render-runtime-json` | Render a NuGet `runtime.json` from a `runtime.json.template`, substituting the release version for the `{{VERSION}}` token before `dotnet pack` |
| `announce-release-discord` | Post a release announcement to Discord (skips RC tags, dedup via release-asset marker) |

### Test

| Action | Description |
|--------|-------------|
| `run-test-apps` | Generate and run e2e fixture suite via `alef test-apps` for a published binding version. Used post-publish to validate bindings against their registry-installed versions. Handles alef-cli install, language toolchain setup, version pin override in `alef.toml`, and captures logs. |
| `test-java-ffi` | Java Panama FFI test setup |
| `run-api-contract-tests` | Run schemathesis property-based contract tests against a containerised API |

### Utility

| Action | Description |
|--------|-------------|
| `free-disk-space-linux` | Free disk space on Linux runners |
| `cache-binding-artifact` | Generic artifact caching for compiled bindings |
| `cleanup-rust-cache` | Clean Rust build artifacts |
| `restore-cargo-cache` | Restore Cargo cache |
| `check-docker-image-size` | Inspect a locally-loaded image, warn or fail on size threshold, write step summary |
| `pack-source-bundle` | Tar+zstd a set of paths into a release-ready bundle with sha256 sidecar |

## Reusable Workflows

| Workflow | Description |
|----------|-------------|
| `reusable-validate-pr.yml` | PR title conventional commit validation |
| `reusable-validate-issues.yml` | Issue title validation |
| `reusable-check-registries.yml` | Matrix registry checks (replaces N separate check jobs) |
| `reusable-python-publish.yml` | Python package build and PyPI publish |
| `reusable-python-lint.yml` | Python linting via uv + prek |
| `reusable-docs-deploy.yml` | Build an Astro Starlight docs site and deploy it to GitHub Pages |

## Repository Workflows

| Workflow | Description |
|----------|-------------|
| `test-unit.yml` | Unit test suite for helper scripts |
| `test-integration.yml` | Integration tests for selected composite actions |
| `test-install-task.yml` | Cross-platform smoke test for `install-task` |
| `test-free-disk-space.yml` | Smoke test for disk cleanup |
| `test-publish-actions.yml` | Publish action test workflow |
| `test-setup-maven.yml` | Smoke test for Maven setup |
| `test-setup-node-workspace.yml` | Smoke test for Node workspace setup |
| `test-setup-openssl.yml` | Smoke test for OpenSSL setup |
| `test-setup-python-env.yml` | Smoke test for Python setup |
| `test-setup-rust.yml` | Smoke test for Rust setup |
| `test-validate.yml` | Validation workflow tests |
| `validate-pr.yml` | Repository PR validation |
| `validate-issues.yml` | Repository issue validation |

## Usage

### Composite actions

```yaml
- uses: xberg-io/actions/setup-rust@v1
  with:
    use-sccache: "true"

- uses: xberg-io/actions/install-task@v1
  with:
    version: latest

- uses: xberg-io/actions/publish-npm@v1
  with:
    packages-dir: dist
    dry-run: "false"

- uses: xberg-io/actions/run-test-apps@v1
  with:
    language: python
    version: 0.3.0
    alef-version: latest
```

Matrix usage for post-publish e2e validation:

```yaml
jobs:
  test-bindings:
    strategy:
      matrix:
        language: [python, node, ruby, php, go, java, csharp, dart, swift]
      fail-fast: false
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: xberg-io/actions/run-test-apps@v1
        with:
          language: ${{ matrix.language }}
          version: ${{ github.ref_name }}
          alef-version: latest
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-logs-${{ matrix.language }}
          path: /tmp/test-apps-*.log
```

### Reusable workflows

```yaml
jobs:
  validate-pr:
    uses: xberg-io/actions/.github/workflows/reusable-validate-pr.yml@main

  publish:
    uses: xberg-io/actions/.github/workflows/reusable-python-publish.yml@main
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
