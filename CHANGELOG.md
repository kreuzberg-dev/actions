# Changelog

All notable changes to xberg-io/actions are documented in this file.

## [Unreleased]

### Changed

- **BREAKING: `install-alef` no longer silently builds `main` when the pinned version has no release.**
  When the release archive was missing, the action fell back to `cargo install --tag v$version`, and when
  that failed too it fell back to `--branch main` with only an informational log line. Any repo pinning a
  version that was never tagged therefore got an unpinned `main` build while every downstream freshness
  gate reported success — the pin examined nothing. The tag build is still attempted (it covers the
  tag-vs-binary-upload race), but a failure now fails the job with a `::error::` naming the version.
  The old behaviour is available per-call via the new `allow-unreleased: true` input, which builds `main`
  and emits a `::warning::` that the binary is not the requested version.
  (`install-alef/action.yml`, `install-alef/scripts/unix.sh`, `install-alef/scripts/windows.ps1`)

### Added

- **`reusable-validate` can enforce fixture-backed documentation snippets.** Callers can opt in with
  `check-fixture-snippets: true`; the job installs `alef` through `install-alef@v1` (using the new
  `alef-version` input, default `latest`), generates configured E2E fixture snippets, fails on tracked
  drift, and runs `alef snippets check --strict --cache off`.
  (`.github/workflows/reusable-validate.yml`)

### Fixed

- **`fetch-test-documents` no longer re-downloads the entire corpus whenever `corpus.lock.json` changes.**
  The `actions/cache` step had an exact `key` and no `restore-keys`, so a one-document manifest edit
  invalidated every cache and every job in every consuming repo re-pulled the full selection from the
  bucket — measured at ~420 GiB of GCS egress across ten days and five lock-file edits. The key is now
  `fetch-test-documents-v1-<include-hash>-<manifest-hash>` (include hash leading, so caches stay scoped
  per `include` selection rather than a narrow job restoring and re-saving the whole corpus), with
  `restore-keys` falling back to the include-hash prefix. `fetch.sh` already skipped objects present and
  hash-verified, so a manifest bump is now a delta fetch. New `restore-prefix` output on the cache-key
  step. (`fetch-test-documents/action.yml`, `fetch-test-documents/scripts/compute-cache-key.sh`)

- **`build-php-extension` no longer corrupts its own `extension-path` output.** The build script's
  stdout is read straight into `$GITHUB_OUTPUT`, but on any crate that inherits `workspace = true`
  it also printed `Stripped workspace inheritance from binding crate Cargo.toml` there. The output
  value then spanned two lines, the second carried no `=`, and the runner rejected the entire file
  command (`Unable to process file command 'output' successfully` / `Invalid format '<path>'`),
  failing every matrix leg of the PHP build. The progress line and the build commands' stdout now
  go to stderr, and the caller keeps only the last stdout line and writes it with the heredoc
  delimiter form, so a stray line can no longer break the write.
  (`build-php-extension/action.yml`, `build-php-extension/scripts/build-out-of-workspace.sh`)

- **`build-python-sdist` split-layout isolation keeps the manifest's README.** The isolated
  single-member workspace copied only the python package dir and the binding crate, so a crate
  carrying `readme.workspace = true` (or a crate-relative `readme = "../../README.md"`) pointed at
  a file that did not exist in the temp tree and maturin failed the whole build with
  `Failed to read Readme specified in Cargo.toml`. The referenced file is now materialized at the
  path the isolated manifest resolves to — inherited paths relative to the workspace root, literal
  paths relative to the crate — so the sdist keeps its real long_description instead of failing or
  shipping an empty description. Nothing is copied when the manifest declares no readme.
  (`build-python-sdist/scripts/build-out-of-workspace.sh`)

- **`wait-for-package` verifies maven against repo1 and accepts `group:artifact`.** The maven check
  queried `search.maven.org/solrsearch`, whose index lags the repository by hours, and it required
  the group as a separate `maven-group-id` — so a caller passing `package: io.xberg:html-to-markdown`
  with no group id burned every attempt reporting "not yet available" for an artifact that was
  already downloadable from Maven Central. The check now resolves the coordinate from either form
  and asks `repo1.maven.org/maven2/<group>/<artifact>/<version>/` directly, which is what consumers
  actually resolve against.
  (`wait-for-package/action.yml`, `wait-for-package/scripts/wait.py`)

- **`wait-for-package` supports the hex, nuget and packagist registries.** All three are passed by
  the generated publish workflows, none had a handler, and the action answered a successful publish
  with `Error: Unsupported registry` and a failed job. `hex` reads `hex.pm/api/packages/<name>`,
  `nuget` the v3 flat container, and `packagist` the `repo.packagist.org` metadata endpoint that
  Composer itself resolves against (accepting both `1.2.3` and `v1.2.3` tags).
  (`wait-for-package/action.yml`, `wait-for-package/scripts/wait.py`)

- **`build-php-extension` and `build-python-sdist` no longer die on macOS runners when the
  binding crate inherits workspace metadata.** Both isolation scripts read `[workspace.package]`
  with `sed -n '/.../,/^\[/p' | head -n -1`. A negative `head` count is a GNU extension; BSD
  `head` answers `head: illegal line count -- -1` and exits 1, which under `set -euo pipefail`
  killed the whole build (seen as every `macos-arm64` PHP job failing while the linux matrix
  passed). Both now use the POSIX `sed '$d'`, which drops the same trailing section header.
  The existing test fixture declared a bare `[workspace]` with no `[workspace.package]`, so the
  affected branch never executed under test; a fixture that does declare it has been added,
  along with a repo-wide guard against `head -n -N` in any shell script.

## [1.8.133] - 2026-08-15

### Added

- **`verify-platform-packages` action.** Asserts that every platform package a napi-style parent
  manifest declares in `optionalDependencies` actually exists: `mode: binaries` (pre-publish) requires
  each declared platform directory to hold a non-empty `*.node` and carry the parent's version, and
  `mode: registry` (post-publish) requires each declared package to resolve on the registry at the
  parent version, reusing `wait-for-package`'s polling and backoff for every name rather than a
  hardcoded subset. The declared set comes from `optionalDependencies` and the expected cardinality
  from `napi.targets` (or an `expected-count` override), so both failure modes behind
  html-to-markdown#459 — `napi create-npm-dirs` materialising a directory for every configured target
  regardless of which build legs ran, and a post-publish gate that named only 2 of 8 packages — fail
  the step. Examined counts are printed on every run, and an empty `optionalDependencies`, a platform
  glob that matches nothing, a declared/discovered set mismatch, or any count mismatch is a hard
  failure rather than a silent pass. (`verify-platform-packages/`,
  `.github/workflows/test-verify-platform-packages.yml`, `tests/test_verify_platform_packages.py`)

## [1.8.124] - 2026-08-07

### Fixed

- **`fetch-test-documents` works on Windows runners.** The action invoked its scripts via
  `${{ github.action_path }}` inlined into a bash `run:` body; on Windows that expands to
  `D:\a\_actions\...`, whose `\a` and `\_` bash reads as escape sequences, collapsing the path and
  failing with exit 127. It now passes `$GITHUB_ACTION_PATH` through the environment and converts it
  (and `runner.temp`, which has the same problem) with `cygpath` where available.
  (`fetch-test-documents/`)

## [1.8.123] - 2026-08-07

### Added

- **`fetch-test-documents` action.** Materialises binary fixtures from the public
  `xberg-test-documents` GCS bucket into a checked-out `test_documents` submodule, replacing
  `git lfs pull` as the corpus moves to content-addressed storage. Selects a subset via `include`
  glob patterns matched against `corpus.lock.json`, dedupes matched entries by sha256, downloads
  each unique object in parallel (`concurrency`, default 8), verifies every download's checksum,
  and writes it to every path that references it — needing no credentials since the bucket is
  public. Caches the object store via `actions/cache` keyed on the manifest content and normalised
  include patterns, and is safe to run twice in the same job. Adds `test-fetch-test-documents.yml`,
  which exercises the live bucket with no credentials configured so a reintroduced auth requirement
  fails in CI rather than only on fork PRs. (`fetch-test-documents/`,
  `.github/workflows/test-fetch-test-documents.yml`)

## [1.8.122] - 2026-08-06

### Fixed

- **The title validators guide outside contributors instead of failing them.** A non-conforming issue
  or PR title produced a red X and no feedback in the thread itself, and because `apply-label` and
  `add-to-project` both `needs:` the title job, an outside contributor's issue was dropped from
  labeling and off the project board entirely. The hard failure now applies only when
  `author_association` is `OWNER`, `MEMBER` or `COLLABORATOR`; anyone else gets a single guidance
  comment (created once, updated thereafter via a hidden marker), a `needs-triage` label, and a green
  run. Every mutation is best-effort, since a fork PR runs with a read-only `GITHUB_TOKEN` in exactly
  this case and a failed courtesy comment must not restore the red X.
  (`.github/workflows/reusable-validate-issues.yml`, `.github/workflows/reusable-validate-pr.yml`)

## [1.8.121] - 2026-08-06

### Fixed

- **`install-alef` requests the msvc Windows archive.** alef builds its Windows release on
  `windows-latest`, whose default toolchain is msvc, so the `-gnu` asset name this asked for has
  never existed — every Windows run 404'd and fell through to the slower release-API lookup.
  (`install-alef/scripts/windows.ps1`)

## [1.8.120] - 2026-08-06

### Fixed

- **`reusable-validate` resolves the Elixir binding's deps.** poly delegates Elixir formatting to
  `mix format`, which reads the project's `.formatter.exs` — and `import_deps: [:rustler]` there
  needs the deps on disk. Without them `mix format` errors, poly logs a warning and treats the file
  as unchanged, so Elixir drift passes CI unnoticed. Adds a best-effort `mix deps.get` and an
  `elixir-working-directory` input (default `packages/elixir`), mirroring the existing `dart pub get`
  and `uv sync` steps. (`.github/workflows/reusable-validate.yml`)

## [1.8.119] - 2026-08-06

### Fixed

- **`publish-npm` no longer reports a failed publish as a success.** `ALREADY_PUBLISHED_PATTERN`
  matched a bare `already exists`, which also matches Sigstore/Rekor's `entry already exists` and
  other unrelated errors; the skip branch then discarded npm's output, so the real failure left no
  trace. `@xberg-io/html-to-markdown` 3.10.5 and 3.10.6 were both logged as "Package already
  published, skipping" while the registry stayed on 3.10.4 — every platform sub-package advanced
  and the umbrella package did not. The pattern is now limited to npm's version-conflict wording,
  the npm output is always printed on the skip path, and both publish modes confirm the version is
  retrievable from `registry.npmjs.org` before reporting success.
  (`publish-npm/scripts/publish.py`)
- **`reusable-validate` installs the pinned clang-format.** The workflow set up Rust, Python, Java,
  Go, Ruby, Dart, and Elixir but never a C toolchain, so `poly fmt --check` used the runner image's
  clang-format 18 — the exact version 1.8.118 pinned away from. crawlberg's CI Lint failed on three
  generated C# files that are correct under the pinned 22.1.8. Installed unconditionally: an absent
  formatter makes poly skip those files silently, which is how drift reaches `main`.
  (`.github/workflows/reusable-validate.yml`)
- **`publish-gleam` defaults to Gleam 1.18.** `gleam new` resolves `gleam_stdlib` at its latest
  release, which requires a newer compiler than the pinned 1.6 — `gleam build` failed with
  "Incompatible Gleam version", and the dry-run test has been red since at least 2026-08-05.
  (`publish-gleam/action.yml`, `.github/workflows/test-publish-actions.yml`)

### Added

- **`setup-c-cpp-tools` gains an `install-cppcheck` input** (default `true`). Jobs that only need
  clang-format can skip cppcheck, whose Linux path builds from source on a version miss.
  (`setup-c-cpp-tools/action.yml`, `setup-c-cpp-tools/scripts/{linux,macos}.sh`)

## [1.8.118] - 2026-08-05

### Fixed

- **`setup-c-cpp-tools`: clang-format is pinned to one version on every platform.** It came from
  `apt` on Linux and `brew` on macOS, which currently ship 18 and 22. Those disagree about C#
  nullable types — 18 rewrites `object? inner;` to `object ? inner;` — and clang-format's output is
  what `poly fmt --check` compares against, so a tree formatted on macOS failed CI on Linux with no
  way to reproduce it locally (seen on crawlberg, whose CI Lint failed on three generated C# files
  that were already correct). Both platforms now install the PyPI `clang-format` wheel at a pinned
  `clang-format-version` (default `22.1.8`) into a venv, which also avoids PEP 668 on the runners'
  system python. cppcheck was already pinned this way; clang-format was the outlier.
  (`setup-c-cpp-tools/action.yml`, `setup-c-cpp-tools/scripts/{clang-format,linux,macos}.sh`)

### Added

- `test-setup-c-cpp-tools` workflow: asserts both runners resolve the pinned clang-format and that
  a C# nullable type survives a format round-trip.

## [1.8.117] - 2026-08-05

### Fixed

- **`install-task`: resolving `latest` no longer fails on the anonymous API rate limit.** The action
  never passed a token, so `api.github.com` was called unauthenticated at 60 requests/hour per
  runner IP — shared by every job on it. On Windows that was fatal: the script had no retry and no
  fallback, so `Install Task` died with `API rate limit exceeded` (hit on an html-to-markdown Node
  build). A `github-token` input (default `${{ github.token }}`) now authenticates the lookup on
  both platforms, and the Windows script falls back to the credential-free `/releases/latest`
  redirect, downloads the stable asset URL directly instead of reading it from release metadata,
  and retries the download. (`install-task/action.yml`, `install-task/scripts/windows.ps1`)
- **`install-task`: a pinned `version` works on Unix.** `version: "3.51.1"` was passed through
  verbatim, but taskfile.dev's installer and the release URLs both want the git tag, so all six
  attempts failed with `unable to find '3.51.1'`. Only `latest` worked, because resolving it
  already yields a v-prefixed tag. The version is now normalised the same way the Windows script
  has always done. (`install-task/scripts/unix.sh`)

## [1.8.116] - 2026-08-05

### Fixed

- **`setup-rust`: the musl `CC`/linker export no longer defeats zig cross-compilation.** For any
  `*-unknown-linux-musl` target the action exported `CC_<target>`, `AR_<target>` and
  `CARGO_TARGET_<TARGET>_LINKER=musl-gcc`. `cargo-zigbuild` and `cargo-xwin` set those with
  `add_env_if_missing`, so the exported values won and the build linked with `musl-gcc` even when
  the caller had installed zig and asked `napi build -x` for a zig cross-compile. That cannot link a
  musl cdylib — rustc passes `-lgcc_s` and Ubuntu's musl sysroot has no `libgcc_s.so.1` — and for a
  foreign architecture it cannot produce anything at all, since `musl-gcc` is a wrapper around the
  host gcc. Both of html-to-markdown's musl Node bindings failed this way at publish time. Two
  changes: a new `configure-musl-cc` input (default `"true"`, set `"false"` to leave the variables
  to the cross toolchain), and the export is now skipped with a warning when the target
  architecture differs from the runner's. (`setup-rust/action.yml`,
  `setup-rust/scripts/add-target.sh`)

## [1.8.115] - 2026-08-05

### Fixed

- **`reusable-validate`: pyrefly resolves imports against the synced venv.** It type-checks with whatever interpreter it is handed — the runner's system Python — so every third-party import in a binding package read as `missing-import` regardless of what `uv sync` installed. The venv is now put on `PATH`/`VIRTUAL_ENV` after the sync. (`.github/workflows/reusable-validate.yml`)

### Added

- **`reusable-validate`: `python-extra-projects` input.** A binding package outside the root uv workspace has dependencies the root `uv sync` never installs (tree-sitter-language-pack's `packages/python` needs `tree-sitter`). Newline-separated project directories listed here are installed into the venv with `uv pip install -e`. (`.github/workflows/reusable-validate.yml`)

## [1.8.114] - 2026-08-05

### Added

- **`reusable-validate`: Go, Ruby, Dart and Elixir toolchain opt-ins.** The workflow could install only Rust, Python and Java, so the five whole-project checks poly drives that need another toolchain — `golangci-lint`, `rubocop`, `steep`, `dart-analyze`, `credo` — could not run in CI. Consumers worked around that by setting `[lint] workspace = false`, which disabled poly's entire workspace phase and left those five linters running in the git pre-commit hooks only, where CI never saw them. New `setup-go`, `setup-ruby`, `setup-dart` and `setup-elixir` inputs (each with version and working-directory companions) install what those checks need, so the workaround can be removed. (`.github/workflows/reusable-validate.yml`)

### Fixed

- **The issue-title fixtures test the regex that actually ships.** `test-validate.yml` still asserted the unscoped `^(bug|feat|…): .{8,}$` that v1.8.111 replaced, so it would have passed even if the scope support were reverted. Synced to the live regex and added scoped-title cases plus uppercase-scope and empty-scope negatives. (`.github/workflows/test-validate.yml`)

## [1.8.113] - 2026-08-05

### Fixed

- **`Unit tests / lint` is green again.** `lint.select = ["ALL"]` picked up ruff's new `CPY001` (missing copyright notice) on a dependency bump, failing every Python file in the repo — 73 errors. `CPY` is now ignored in `pyproject.toml`, matching what `poly.toml` already did. Also removed the two `# noqa: S310` directives ruff now reports as unused (`RUF100`) and made the boolean release flags of `create_release`/`update_release` keyword-only so they stay under the positional-argument limit (`PLR0917`). (`pyproject.toml`, `publish-github-release/scripts/`, `publish-nuget/scripts/publish.py`)
- **`upload-release-assets`: `remote_asset_size` no longer returns an implicit `Any`.** The size read out of the API payload is now type-narrowed before it is returned, which `pyrefly` rejected. (`upload-release-assets/scripts/upload_assets.py`)

## [1.8.112] - 2026-08-05

### Fixed

- **`upload-release-assets`: a re-uploaded asset no longer fails the job.** The release upload API is not idempotent: when a request reaches GitHub but its response is lost, `gh` retries and the retry returns HTTP 422 `ReleaseAsset.name already exists` even though the asset uploaded correctly — turning a successful publish into a red job (observed on `liter-llm` v1.15.0, where all four C FFI assets were present and `state=uploaded` while the job reported failure). `upload_one` now treats the upload as done when the release reports an asset of the same name whose size matches the local file, and otherwise retries up to three times with backoff before raising. A size mismatch — a genuinely stale asset — still fails. (`upload-release-assets/scripts/upload_assets.py`)

## [1.8.111] - 2026-08-03

### Fixed

- **`reusable-validate-issues`: accept scoped conventional-commit issue titles.** The title regex `^(bug|feat|docs|chore|refactor|test|ci|perf|build): .{8,}$` only permitted a bare `type:` prefix and rejected valid scoped titles like `feat(cli): …`. Added an optional scope group `(\([a-z0-9._-]+\))?` so `type(scope): …` passes while the 8-char minimum body and the type list are unchanged. (`.github/workflows/reusable-validate-issues.yml`)

## [1.8.110] - 2026-08-01

### Fixed

- **`reusable-binstall-verify`: authenticate the GitHub API calls `cargo binstall` makes.** The install job ran `cargo-bins/cargo-binstall` and `cargo binstall` with no `GITHUB_TOKEN` in scope, so its release-asset resolution hit the anonymous 60 req/hr GitHub API limit and 403'd on busy runners — reliably on `aarch64-apple-darwin`, where binstall's retry backoff outlasted the step deadline and failed the whole verify (and thus gated releases). Added a job-level `env: GITHUB_TOKEN: ${{ github.token }}` so both the setup action and the resolve calls authenticate (5000 req/hr). Uses the ambient caller token; needs only the `contents: read` callers already grant, so no consumer or `secrets:` change is required. (`.github/workflows/reusable-binstall-verify.yml`)

## [1.8.109] - 2026-08-01

### Added

- **`reusable-binstall-verify`: new reusable workflow that installs a released CLI via `cargo binstall` and smoke-tests it across a target matrix.** Pairs with `reusable-cli-release.yml` — that workflow uploads the `<asset-prefix><target>` archives, this one proves consumers can `cargo binstall` them from GitHub Releases. Asset-scheme agnostic: the download URL and in-archive binary path come from the consuming crate's `[package.metadata.binstall]`, so it only needs `package-name`, `binary-name`, and `manifest-path`. Inputs also cover a `smoke-command` override (for CLIs whose binary bundles runtime libs binstall does not place), a `targets` override (windows-gnu / reduced matrices), and a `git-url` fallback for CLIs not published to crates.io. (`.github/workflows/reusable-binstall-verify.yml`)

## [1.8.107] - 2026-07-31

### Added

- **`reusable-validate`: `setup-java` input to install a JDK for poly's checkstyle project check.** poly runs `mvn checkstyle:check` as a whole-project check against Java bindings; checkstyle 13.x requires a JDK 21+ while GitHub runners default to 17, so the check died with `UnsupportedClassVersionError` (class file version 65.0 vs 61.0). New opt-in `setup-java` (default `false`) plus `java-version` (default `"21"`) and `java-distribution` (default `"temurin"`) inputs add an `actions/setup-java@v5` step before poly runs. Backward-compatible — callers that don't set `setup-java` are unaffected. (`reusable-validate.yml`)

## [1.8.106] - 2026-07-30

### Fixed

- **`homebrew-build-bottles`: pin `homebrew/core` to match the pinned Linux brew.** The Linux leg pins brew to 6.0.12 (to dodge the 6.0.13 `--build-bottle` regression) but `HOMEBREW_NO_INSTALL_FROM_API=1` makes brew evaluate core formulae from the on-disk `homebrew/core` tap, which `install.sh` clones at latest. Core formulae adopted the `run` install-steps DSL in 6.0.13, which 6.0.12 can't parse, so dependency import (ca-certificates, …) died with `undefined method 'run' for an instance of Homebrew::InstallSteps::DSL` — silently failing **every** Linux bottle after the pin landed (crawlberg v1.0.11/v1.0.12: both Linux legs red → the merge-bottle-DSL job was skipped → the published tap formula was left with `url` at the new version but the bottle block frozen at v1.0.10, so `brew` composed a 404 bottle URL). The Linux path now clones `homebrew/core` at the commit contemporaneous with the brew tag (a blobless shallow clone bounded to a few days around the tag) so on-disk formula syntax matches the running brew, restoring the v1.0.10-era known-good combination. (`homebrew-build-bottles/scripts/build-bottles.sh`)

## [1.8.105] - 2026-07-29

### Removed

- **Removed `setup-openssl` action and `linux-features` input from build actions.** kreuzberg migrated all TLS to pure rustls + OS-native trust stores (ureq platform-verifier, ort tls-rustls), eliminating OpenSSL from the build entirely. The `setup-openssl` action which installed libssl-dev/OpenSSL is no longer used. The `linux-features` input (which passed `kreuzberg/openssl-vendored` to enable OpenSSL vendoring) is removed from all build actions: `build-rust-cli`, `build-rust-ffi`, `build-go-ffi`, `build-java-natives`, `build-csharp-natives`, `build-elixir-natives`, `build-swift-artifactbundle`. The musl builders (Alpine `apk add` lines) no longer install `openssl-dev`. Tests for the removed `linux-features` parameter have been deleted. (`setup-openssl/` action removed entirely, all `*-features` inputs and plumbing removed from 7 build actions + musl builders, `tests/test_build_ffi.py`)

### Added

- **`render-runtime-json` action: render a NuGet `runtime.json` from a `runtime.json.template` before `dotnet pack`.** alef now emits `packages/csharp/<Namespace>/runtime.json.template` (a RID-fallback graph with a literal `{{VERSION}}` placeholder) for every C# binding package, and the consumer's csproj has a `RequireRuntimeJson` target that hard-errors during `dotnet pack` unless a rendered, placeholder-free `runtime.json` sits beside it. The new composite action substitutes the release version for `{{VERSION}}`, asserts the result is placeholder-free valid JSON, and writes it to the template path with the `.template` suffix stripped (or an explicit `output-path`); emits the written path as `rendered-path`. (`render-runtime-json/action.yml`, `render-runtime-json/scripts/render.py`, `tests/test_render_runtime_json.py`)
- **glibc-2.28 floor for gnu-target Linux release artifacts via cargo-zigbuild.** The gnu binaries (CLI, Go/Java/C#/Dart/C FFI, Elixir NIF, Node) build natively on `ubuntu-24.04` and so inherited its glibc 2.39, even though neither the Rust code nor the statically-linked tesseract/leptonica C++ needs symbols that new — excluding RHEL 8/9, Debian 12, Ubuntu 22.04, Amazon Linux 2. Each affected build action gains a `glibc-version` input (`GLIBC_VERSION` env in the script-based ones); when it is set AND the target is `*-linux-gnu`, the action runs `cargo zigbuild --target <triple>.<glibc>` instead of `cargo build` and Zig links against the requested glibc so the artifact runs on older distros. **The input is opt-in (default empty = plain `cargo build`)** so these shared actions stay backward-compatible for every other polyrepo consumer — only callers that also install Zig + `cargo-zigbuild` and pass `glibc-version` (kreuzberg's `publish.yaml` passes `2.28`) change behaviour. Validated locally: a final ELF statically linking tesseract+leptonica reports a max requirement of exactly `GLIBC_2.28`. Because Zig compiles C/C++ with clang, it does not emit GCC-14's `__isoc23_*` symbols (which require glibc ≥2.38), so the `-std=gnu11` workaround the manylinux wheel build needs is unnecessary here. Artifacts still emit to `target/<base-triple>/release` (zigbuild strips the `.glibc` suffix from the output dir), so artifact discovery is unchanged. musl (Alpine), macOS, and Windows targets are untouched (plain `cargo build`). The caller (kreuzberg `publish.yaml`) installs Zig (`setup-zig`) + `cargo-zigbuild` before each gnu job; Node uses napi-rs's Zig cross path via `--use-napi-cross`. (`build-rust-cli/action.yml`, `build-rust-ffi/action.yml`, `build-rust-ffi/scripts/build.py`, `build-go-ffi/scripts/build.py`, `build-java-natives/scripts/{build,musl_builder}.py`, `build-csharp-natives/scripts/{build,musl_builder}.py`, `build-elixir-natives/scripts/{build,musl_builder}.py`, and kreuzberg `.github/workflows/publish.yaml`)

### Fixed

- **`publish-crates`: handle the first-ever publish of a new crate under Trusted Publishing.** crates.io OIDC tokens cannot *create* a crate that has never been published (`Trusted Publishing tokens do not support creating new crates. Publish the crate manually, first`), which hard-failed the whole release the moment a new crate (e.g. kreuzberg's `kreuzberg-candle-ocr` in v5.0.0) entered the publish list. The script now detects this specific rejection, stops retrying it (retrying never grants the token create permission), records the crate, and lets the remaining crates publish; at end-of-run it fails with one consolidated, actionable summary naming each crate and the exact one-time manual bootstrap (`CARGO_REGISTRY_TOKEN=<classic-token> cargo publish -p <crate> --allow-dirty`). Already-published versions (including an existing rc) still take the idempotent success path. (`publish-crates/scripts/publish.py`)
- **`publish-rubygems`: report the actual `gem spec` command in the failure diagnostic.** On a structurally-invalid gem the diagnostic printed `gem spec --file <name>`, but the `--file` flag was removed in RubyGems 3.3+ and the script already invokes `gem spec <path>` positionally. The misleading text made "invalid gem structure" failures look like a flag/version problem rather than a corrupt archive. Print the real positional command. (`publish-rubygems/scripts/publish.py`)
- **`homebrew-build-bottles`: pin the Linux leg to Homebrew 6.0.12.** Homebrew 6.0.13 regressed `brew install --build-bottle` on Linux — the keg builds (🍺 prints) but the process then exits 1 with the underlying error swallowed, aborting the script under `set -e` before `brew bottle` runs (crawlberg v1.0.11: both Linux bottles red on 6.0.13; 6.0.12 was the last green build, and macOS on 6.0.11 was unaffected). The Linux install path — where brew is freshly installed to latest — now checks out the `6.0.12` tag in the brew repo and sets `HOMEBREW_NO_AUTO_UPDATE=1` instead of `brew update`ing to latest; macOS keeps its preinstalled brew and its `brew update` unchanged. Override via `LINUX_BREW_PIN`. (`homebrew-build-bottles/scripts/build-bottles.sh`)

## [1.8.83] - 2026-06-21

### Fixed

- **`run-api-contract-tests`: support schemathesis 4.x.** The action installed schemathesis unpinned (`latest`), so it silently moved to the 4.x line — where `--request-timeout` is interpreted in **seconds** rather than the milliseconds 3.x used. The action forwards its `request-timeout-ms` input verbatim, so the 30000 ms default became a 30000-second (effectively unbounded) per-request timeout. Convert the ms input to seconds before invoking schemathesis, and pin the default install to `schemathesis>=4,<5` so a future major can't change the CLI contract unannounced. All other flags (`--max-examples`, `--checks` and the standard check names) are unchanged on 4.x. (`run-api-contract-tests/scripts/run.sh`, `run-api-contract-tests/action.yml`)

## [1.8.82] - 2026-06-21

### Fixed

- **`build-python-wheels`: deterministically install the pinned Rust toolchain on macOS.** `CIBW_BEFORE_ALL_MACOS` installed the default `stable` toolchain and relied on a lazy, `rust-toolchain.toml`-driven install of the pinned channel when maturin ran `cargo metadata` — which left the toolchain without a `cargo` proxy (`error: 'cargo' is not installed for the toolchain '1.95-aarch64-apple-darwin'`), failing every macOS wheel build. Now installs rustup with `--default-toolchain none --profile default`, reads the channel from the consumer's `rust-toolchain.toml` at `$GITHUB_WORKSPACE`, and explicitly `rustup toolchain install`s it with the full default profile (so `cargo`/`clippy`/`rustfmt` are present before the build). Falls back to `stable` when no channel is found. (`build-python-wheels/action.yml`)

## [1.8.81] - 2026-06-20

### Fixed

- **`retag-for-republish`: consume a `token` input so republish can move tags.** The action ran its `gh api` tag delete/create with `GH_TOKEN: github.token`, but the default `GITHUB_TOKEN` cannot write git refs (`HTTP 403 Resource not accessible by integration`), so `republish: true` flows failed at "Retag for republish". Add a `token` input (defaults to `github.token` for back-compat) and use it; callers already passing a GitHub App installation token with `contents: write` now succeed. (`retag-for-republish/action.yml`)

## [1.8.80] - 2026-06-20

### Removed

- **`reusable-cli-proxy-publish.yml`: remove the cli-proxy reusable workflow (and its test workflow + fixtures).** It had no consumers: cli-proxy npm publishing now runs inline in each repo's `publish.yaml` via the `publish-npm@v1` composite action, because npm OIDC trusted publishing matches the `job_workflow_ref` and a reusable-workflow call would present the reusable file's name instead of `publish.yaml` (where the trusted publisher is bound). (`.github/workflows/reusable-cli-proxy-publish.yml`, `.github/workflows/test-reusable-cli-proxy-publish.yml`, `tests/fixtures/cli-proxy/`)

### Fixed

- **`publish-npm`: publish the pure-JS umbrella package, not just per-platform sub-packages.** The skip guard treated any `.tgz` without a `.node` member as an empty stub, but the umbrella package consumers install (whose native binaries resolve via `optionalDependencies`) also ships no `.node` of its own — so it was silently skipped and never published, leaving only the per-platform sub-packages on the registry. A stub is now classified as a per-platform package (`os`/`cpu` pinned in its `package.json`) that lacks its prebuilt binary; the umbrella package (no `os`/`cpu`) always publishes. Surfaced by spikard `v0.16.0-rc.2`, whose `@spikard/node` umbrella was missing while its platform packages published; affects every napi-style binding repo. (`publish-npm/scripts/publish.py`, `tests/test_publish_npm.py`)

## [1.8.79] - 2026-06-20

### Added

- **`reusable-cli-proxy-publish.yml`: add reusable workflow to publish cli-proxy npm + PyPI packages.** A `workflow_call` reusable workflow that publishes the thin CLI proxy wrapper packages (npm + PyPI) which download a repo's prebuilt CLI binary at install time. Two independent, separately-gated jobs: an npm job (`publish-npm`, default `true`) delegating to `publish-npm@v1` (OIDC trusted publishing, `access: public`, `provenance: true`); and a pypi job (`publish-pypi`, default `true`, pinned to the `pypi` environment) that runs `uv build` on the proxy package — `publish-pypi@v1` publishes a prebuilt dist and does not build — before delegating to `publish-pypi@v1`. The caller's job needs `permissions: id-token: write` for both registries' OIDC flows. Inputs: `npm-package-dir` (default `cli-proxy/npm`), `pypi-package-dir` (default `cli-proxy/pypi`), `npm-tag` (default `latest`), `publish-npm`/`publish-pypi` (boolean toggles), `dry-run` (default `"false"`), `checkout-ref` (default `""`). (`.github/workflows/reusable-cli-proxy-publish.yml`)

## [1.8.78] - 2026-06-20

### Added

- **`reusable-cli-release.yml`: `extra-cargo-args` passthrough input.** Optional string (default `""`) forwarded verbatim to `build-rust-cli` in all three build jobs (core matrix, `extra-targets`, musl), so feature-gated CLIs can pass e.g. `--features all`. kreuzcrawl ships api/mcp/mcp-http/warc/ai behind `--features all`; without this the reusable workflow would build default-feature binaries (no MCP server, no API). No-op for default-feature consumers such as html-to-markdown. (`.github/workflows/reusable-cli-release.yml`)

## [1.8.77] - 2026-06-20

### Added

- **`reusable-cli-release.yml`: centralized CLI binary build + GitHub Release upload.** A `workflow_call` reusable workflow that builds a standalone Rust CLI across a reliable cross-platform matrix (x64+arm64 linux-gnu, arm64 macOS, x64 Windows) and uploads the archives to the repo's release. The reliable set deliberately excludes the scarce x64-macOS and arm64-Windows runners whose queue starvation previously blocked *all* CLI uploads — a single stuck leg failed the strict `upload` gate, leaving zero CLI assets on the release (observed on html-to-markdown v3.6.18). musl is a separate `continue-on-error` best-effort job, so its failure never fails the workflow or blocks the core uploads; `upload` runs whenever the core matrix succeeds (`!cancelled() && needs.cli-binaries.result == 'success'`). The upload step also un-drafts the release (`publish-github-release@v1 draft:false`, idempotent) so CLI binaries are never stranded in a draft, and can emit a `<asset-prefix>SHA256SUMS` file (`checksums: true`) for fail-closed verification by CLI proxy packages. Scarcer/flaky platforms (x64 macOS, arm64 Windows) belong in `extra-targets` — a separate `continue-on-error` best-effort matrix that ships when it builds but never blocks the release — rather than `targets`, which is strict-gated. Inputs: `package-name`, `binary-name`, `tag`, `asset-prefix` (default `cli-`), `checkout-ref`, `dry-run`, `build-musl` (default `true`), `checksums` (default `false`), `targets` (core matrix), `extra-targets` (best-effort matrix, default `[]`). (`.github/workflows/reusable-cli-release.yml`)

## [1.8.76] - 2026-06-20

### Fixed

- **`publish-maven`: stream `mvn clean deploy` output live and bound the step with a configurable timeout.** The previous `subprocess.run(..., stdout=PIPE, stderr=STDOUT)` buffered all Maven output and printed it only after the process returned. If the Central Portal hung during publish confirmation and GitHub cancelled the job timeout, the buffered output was lost entirely, leaving zero diagnostic clues. Also, no timeout was set on the subprocess — a stuck Central Portal burn silently until GitHub's ~360min job timeout, producing an opaque "The operation was canceled" failure instead of an actionable error. The fix replaces PIPE capture with `subprocess.Popen(..., bufsize=1)` and a line-by-line reader thread that `print(line, end="", flush=True)` immediately while accumulating for the `is_already_published()` check. A bounded wall-clock timeout (default 1800s = 30min, override via `INPUT_DEPLOY_TIMEOUT`) wraps the deploy; on timeout the process is killed, all streamed output is flushed, and a clear error (with link to <https://central.sonatype.com> deployments) is printed to stderr instead of an opaque GitHub cancellation. Surfaced by tslp `v1.9.0` publish hang. (`publish-maven/scripts/deploy.py`)
- **`build-python-wheels`: wipe `~/.cargo` and `~/.rustup` on macOS before building.** macos-latest runner images preinstall a Rust toolchain whose `bin/cargo-clippy` is not tracked by rustup's component manifest. When maturin's `cargo metadata` runs in a consumer checkout, the consumer's `rust-toolchain.toml` (`channel = "1.95"`, `components = [..., "clippy"]`) makes rustup materialize the pinned toolchain and install the clippy component, which aborts on the untracked binary with `failed to install component 'clippy-preview-aarch64-apple-darwin', detected conflict: 'bin/cargo-clippy'`, failing the wheel build. The `1.8.49` non-wiping pre-install (`ac2ae06`) regressed the earlier `1.8.48` wipe: it staged the default `stable` toolchain (not the pinned `1.95`) and left the stray binary in place, so the conflict reproduced (kreuzcrawl rc.81 macOS wheel job). `CIBW_BEFORE_ALL_MACOS` now wipes both dirs again so the in-cibw rustup owns the entire toolchain state and the pinned install is clean. Guarded by a unit test and a macos-latest integration leg that pins `rust-toolchain.toml`. (`build-python-wheels/action.yml`)

## [1.8.74] - 2026-06-17

### Fixed

- **`setup-elixir`: drop redundant `Install Hex and Rebar` step that pinned `HEX_MIRROR=https://cdn.hex.pm`.** The wrapper previously ran `mix local.hex --force && mix local.rebar --force` after `erlef/setup-beam@v1` had already installed both, hardcoding `HEX_MIRROR=https://cdn.hex.pm`. On arm64 GitHub-hosted runners `cdn.hex.pm` now fails DNS (`getaddrinfo ENOTFOUND cdn.hex.pm`) intermittently, causing every Setup Elixir step to fail at the redundant install even though `setup-beam`'s mirror-fallback logic had already successfully installed hex/rebar via `https://builds.hex.pm`. The wrapper now relies on `setup-beam`'s built-in `install-hex: true` / `install-rebar: true` (which honors the mirror list with proper fallback) and drops the duplicate step entirely. Fixes the rc.55 `Validate (Lint & Format)` CI failure and all downstream Elixir CI jobs on arm64 runners. (`setup-elixir/action.yml`)

## [1.8.73] - 2026-06-17

### Fixed

- **`setup-chrome`: explicitly connect chromium snap interfaces and run a blocking smoke test on linux-arm64.** The intermittent `Content snap command-chain for /snap/chromium/<rev>/gpu-2404/bin/gpu-2404-provider-wrapper not found: ensure slot is connected` abort observed downstream (kreuzcrawl C E2E job) is caused by racy snap interface autoconnect on GitHub-hosted Ubuntu ARM runners. The action now explicitly connects `chromium:{gpu-2404, hardware-observe, process-control, system-observe, mount-observe, network-observe, opengl, audio-*, camera, joystick, removable-media, cups-control, u2f-devices}` (each `|| true` since revisions vary), logs `snap connections chromium` for diagnostics, and replaces the previous `|| true` smoke test with a fail-fast retry loop that validates rendering (`chromium --headless=new --disable-gpu --no-sandbox --use-mock-keychain --dump-dom about:blank | grep -qi '<html'`). Three attempts with linear backoff; `exit 1` on final failure so a broken runner fails this step instead of producing confusing downstream test aborts. Docstring corrected — Chrome for Testing publishes no linux-arm64 build (only linux64), so the prior "downloads Chrome for Testing" claim was inaccurate. (`setup-chrome/action.yml`)

## [1.8.72] - 2026-06-17

### Fixed

- **`publish-crates`: inject `version = "<INPUT_VERSION>"` into every intra-workspace path-dep that lacks one, then restore the manifest after each `cargo publish`.** `cargo publish` validates every `[dependencies]`, `[dev-dependencies]`, and `[build-dependencies]` entry (including `[target.'cfg(...)'.<kind>]` and `[dependencies.<name>]` dotted-table variants) and rejects manifests where a `path = "..."` dep has no `version = "..."` constraint with `error: all dependencies must have a version requirement specified when publishing`. Some manifests deliberately omit the version on a sibling-path dep to work around unrelated build-graph bugs — kreuzberg's `crates/kreuzberg/Cargo.toml` strips it from `kreuzberg-tesseract` (commit `719a626991`) to dodge a maturin sdist "links collision" — which made every `cargo publish -p kreuzberg` fail with that error. The publish script now resolves the manifest path for each crate via `cargo metadata`, scans only dependency sections (skipping `[workspace.dependencies]`, `[features]`, etc.), rewrites every path-only entry idempotently (single-line inline tables, multi-line inline tables, and dotted-table forms), and restores the original bytes on context exit — success, failure, or exception. `workspace = true` entries and deps that already declare `version` are left untouched. Surfaced by kreuzberg `v5.0.0-rc.19`. (`publish-crates/scripts/publish.py`, `tests/test_inject_versions.py`)

- **`setup-elixir`: default `hexpm-mirrors` to cdn.hex.pm to bypass builds.hex.pm OTP 27.2 TLS key_usage_mismatch.** OTP 27.2's stricter TLS validation rejects the certificate chain on `builds.hex.pm` due to a key_usage/extKeyUsage mismatch, causing `mix local.hex --force` and `mix local.rebar --force` to fail with `TLS client: … key_usage_mismatch`. The `erlef/setup-beam@v1` action supports multiple mirrors via the `hexpm-mirrors` input; the new default prioritizes `https://cdn.hex.pm` (uses a compatible cert chain) with `https://builds.hex.pm` as fallback. The action also sets `HEX_MIRROR=https://cdn.hex.pm` on the "Install Hex and Rebar" step to cover the inline `mix local.hex/rebar` calls that bypass the `erlef/setup-beam` step. Callers can override `hexpm-mirrors` to customize the mirror list. Fixes OTP 27.2 test-elixir CI failures in tslp and other Elixir-dependent polyglot repos. (`setup-elixir/action.yml`)

## [1.8.71] - 2026-06-16

### Fixed

- **`publish-github-release/scripts/ensure_release.py`: poll for tag visibility on the git refs API before creating the release.** The v1.8.63 retry-on-404 fix absorbed lag against the release-lookup API, but after its 20×10s retries exhausted the script fell through to `create_release()` unconditionally. When the tag itself had not yet propagated to GitHub's git-refs API (workflow_dispatch racing the tag push), the resulting release pointed at a non-existent ref and the eventual tag push reproduced the original dual-release bug. The script now polls `GET /repos/{owner}/{repo}/git/refs/tags/{tag}` with a 12×5s loop before calling `create_release()`, exits 1 with a clear error if the tag is never visible, and matches the workflow-dispatch → publish → tag-push timing budget (60s) directly. Two new tests cover the success-after-retry and timeout-exits paths; `test_main_retries_exhausted_tag_missing_exits_gap1` was updated to assert the 12-poll budget. (`publish-github-release/scripts/ensure_release.py`, `publish-github-release/tests/test_ensure_release.py`)

## [1.8.70] - 2026-06-16

### Fixed

- **`setup-rust`: install `protoc` on every runner.** Several common crates (`etcd-client`, `tonic`, anything depending on `prost-build`) shell out to `protoc` from their `build.rs`. GitHub-hosted Linux/macOS/Windows runners do not preinstall it, so `cargo build` on a consumer crate panics with `Failed to compile proto files: Could not find protoc`. The new step installs `protobuf-compiler` via apt on Linux, `protobuf` via Homebrew on macOS, and `protoc` via Chocolatey on Windows, skipping if already present. Fixes the v1.6.1 liter-llm `Build CLI binary` failures (etcd-client transitive dep through liter-llm-proxy). (`setup-rust/action.yml`)

## [1.8.69] - 2026-06-14

### Fixed

- **`rewrite-native-deps`: strip `path = "..."` from `[workspace.dependencies]` entries so the sdist's workspace `Cargo.toml` resolves on consumer install.** v1.8.66 added `[patch.*]` stripping for sdist consumers (resolves #390), but missed `[workspace.dependencies]`. cargo eagerly validates every workspace-dependency entry, even when no member uses `workspace = true` for that name. A leftover `path = "crates/<core>"` points at a directory NOT shipped in the sdist (alef publish prepare only ships the binding crate via maturin's manifest-path), so consumer `pip install` of html-to-markdown==3.6.4 on Alpine/musl bails with `failed to read .../crates/<core>/Cargo.toml`. The new step parses `Cargo.toml` after the [patch.*] strip and drops every `path` attribute from `[workspace.dependencies]` entries (both inline-table forms and dotted-table standalone lines), leaving the version so the dep resolves from the registry. Resolves xberg-io/html-to-markdown#402.

## [1.8.68] - 2026-06-14

### Fixed

- **Every `cargo build` / `maturin build` / `cargo zigbuild` / `cargo ndk … build` / `cargo run` / `cargo test` invocation now passes `--locked` (or `CARGO_BUILD_LOCKED=true` for the maturin-wrapped paths).** Previously a `cargo build` invocation without `--locked` silently updates the lockfile to the latest semver-compatible versions before compiling. Combined with the `cargo generate-lockfile` step in `alef publish prepare` (separately fixed in alef), this let broken upstream releases — specifically `brotli-decompressor 5.0.1` and `5.0.2`, whose `alloc-no-stdlib` v2/v3 split trips `error[E0277] StandardAlloc: alloc::Allocator<u8> is not satisfied` — leak into bindings whose committed `Cargo.lock` already pinned the known-good `5.0.0`. This caused kreuzcrawl v0.3.0-rc.60's `Build Elixir NIF (macos-arm64 nif-2.17)` and `Build PHP extension (php8.3 macos-arm64)` jobs to fail despite the source repo's pin being correct.

  Sweep touches: `build-rust-cli/action.yml`, `build-rust-ffi/scripts/build.py` (in `build_cargo_args`), `build-go-ffi/scripts/build.py`, `build-java-natives/scripts/musl_builder.py` (Docker and native build paths), `build-csharp-natives/scripts/musl_builder.py` (Docker and native build paths), `build-android-natives/scripts/build.py` (the `cargo ndk … build` line), `build-dart-package/scripts/build.sh`, `build-swift-package/scripts/build.sh`, `build-swift-artifactbundle/scripts/build.sh` (4 `cargo build` + 2 `cargo zigbuild` + dry-run echoes), `build-ios-xcframework/scripts/build.sh`, `build-zig-package/scripts/build.sh`, `build-gpu-test-binary/scripts/build.sh` (changes `cargo_args=(test -p …)` to include `--locked`), `build-php-extension/action.yml` (Windows path), `build-php-extension/scripts/build-out-of-workspace.sh` (also now seeds `Cargo.lock` from `$WORKSPACE_ROOT/Cargo.lock` before `cargo generate-lockfile` so the out-of-workspace temp build inherits the workspace's pins), `build-python-sdist/scripts/build-out-of-workspace.sh` (same workspace-lock seed before `cargo generate-lockfile` so the lockfile shipped inside the sdist preserves pins on consumer install), `build-python-wheels/action.yml` (adds `CARGO_BUILD_LOCKED=true` to the `CIBW_ENVIRONMENT`, `CIBW_ENVIRONMENT_MACOS`, `CIBW_ENVIRONMENT_WINDOWS` defaults so maturin's nested cargo respects the committed lock inside cibuildwheel containers), `test-java-ffi/action.yml`, `verify-install/scripts/verify.sh` (both `cargo run` invocations).

  `actions/tests/test_build_ffi.py` updated to assert the new `--locked` arg position. Existing `--locked` usages in `setup-android-ndk`, `cargo install`, `cargo-zigbuild` install, and `install-alef/scripts/unix.sh` were already correct and are unchanged. `cargo generate-lockfile` invocations in `build-elixir-hex`, `publish-hex`, and the Windows `build-php-extension` PowerShell path are unchanged — they only generate files for dry-run/staging, not for the publish artifact. `cargo update -p time --precise 0.3.47` in the PHP path stays as an explicit intentional pin.

## [1.8.67] - 2026-06-14

### Fixed

- **`build-python-wheels`: install `numactl-devel` in manylinux containers for ORT aarch64 linker.** ONNX Runtime on `linux-aarch64` links against `libnuma.so.1`, but the AlmaLinux 8 manylinux_2_28 base does not preinstall the dev headers. `CIBW_BEFORE_ALL_LINUX` now passes `numactl-devel` alongside `cmake gcc-c++` to the `$PKG install` line so `cargo build --release` on `aarch64-unknown-linux-gnu` resolves `-lnuma` instead of failing with `/usr/bin/ld: cannot find -lnuma`. Fixes kreuzberg `Rust (ubuntu-24.04-arm)` linker failure observed on CI run 27492590412. (`build-python-wheels/action.yml`)

- **`publish-github-release/scripts/ensure_release.py`: close critical gaps in release-creation safety.** The v1.8.63 retry-on-404 fix absorbed tag-propagation lag but had three vulnerabilities:
  1. **Retry exhaustion without fallback.** After 20×10s retries return 404, the script silently falls through to `create_release`, reproducing the original bug. Now after retries exhaust, the script calls the canonical git-tag endpoint (`GET /repos/{owner}/{repo}/git/refs/tags/{tag}`) and exits with a clear error if the tag doesn't actually exist.
  2. **Unvalidated release creation.** GitHub's POST `/releases` can return `tag_name="untagged-..."` even when the request sends `tag_name="v3.6.2"`. This was the actual root cause of html-to-markdown v3.6.2 (the tag existed but the release was corrupted). Now the script asserts the response `tag_name` matches the request; if not, it immediately PATCHes the release to repair the `tag_name`. If the PATCH also fails to stick, the script exits 1.
  3. **No repair for pre-existing broken drafts.** When a prior workflow run left a broken draft with `name="v3.6.2"` and `tag_name="untagged-..."`, the tag-lookup 404-retries can't find it (because `GET /releases/tags/v3.6.2` requires a working `tag_name`). The script now lists all releases, finds any draft whose `name == tag` and `tag_name` starts with `"untagged-"`, and repairs it in-place via PATCH before creating a new release.

  Tests added to verify retry exhaustion exits cleanly (not silently), POST response validation, and broken-draft repair. Added Gap 2 existing-release path tests: `test_main_release_exists_with_broken_tag_repairs` (lines 395–411) validates tag_name repair via PATCH; `test_main_release_exists_broken_tag_patch_fails_exits_1` (lines 430–440) confirms sys.exit(1) on PATCH failure.

## [1.8.65] - 2026-06-14

### Fixed

- **`build-python-wheels`: fix subshell scope bug that broke `CIBW_BEFORE_ALL_LINUX` on x86_64 manylinux.** The previous `(command -v dnf >/dev/null && PKG=dnf || PKG=yum)` group runs in a subshell, so `PKG` is never set in the parent shell. The next clause then expands `$PKG install -y cmake gcc-c++` as `install -y cmake gcc-c++`, invoking GNU coreutils `install` which exits 1 with `install: invalid option -- 'y'`. Replaced with command substitution: `PKG=$(command -v dnf >/dev/null && echo dnf || echo yum)`. Fixes html-to-markdown v3.6.3 Publish run 27488669093 `Build Python wheels (ubuntu-latest)` failure.

- **`build-python-wheels`: source-build libheif 1.23.0 in manylinux containers.** Ubuntu Noble apt and the AlmaLinux 8 manylinux_2_28 base both ship libheif 1.17.x, but `libheif-sys 5.3+` requires `libheif >= 1.21`. `CIBW_BEFORE_ALL_LINUX` now installs `cmake`, `gcc-c++`, and codec headers (`libde265-devel libaom-devel x265-devel libdav1d-devel`) via dnf/yum, then downloads + compiles + installs libheif 1.23.0 to `/usr/local`. Without this, every Linux wheel build for any kreuzberg consumer fails at the `libheif-sys` build script with `Package 'libheif' has version '1.17.6', required version is '>= 1.21'`. macOS and Windows wheel paths are unchanged.

## [1.8.63] - 2026-06-13

### Fixed

- **`setup-elixir`: normalize `win25-vs2026` ImageOS to `win25` for `erlef/setup-beam@v1`.** GitHub-hosted `windows-latest` runners now report `ImageOS=win25-vs2026` (windows-2025 + Visual Studio 2026), but `erlef/setup-beam@v1` only recognizes the bare label `win25` and aborts with `Tried to map a target OS from env. variable 'ImageOS' (got win25-vs2026), but failed`. The action already rewrote `ubuntu24-arm64` and `ubuntu22-arm64` to their bare counterparts; this extends the rewrite to cover `win25-vs2026 → win25`. Restructured the rewrite as a `case` statement so future runner labels can be added with a single line. Fixes spikard v0.15.6-rc.22 Publish run 27373551984 `Build Elixir NIF (windows-x86_64)` failure → unblocks Hex publish (previously skipped because all Elixir NIF builds had to succeed).

## [1.8.62] - 2026-06-12

### Fixed

- **`publish-zig`: drop `-f` from curl invocation (conflicts with `--fail-with-body`).** The `Upload release asset` step ran `curl -fsSL --fail-with-body ...` against the `/uploads` endpoint. curl 7.76+ rejects this invocation with `curl: option --fail-with-body: is badly used here` because `-f`/`--fail` and `--fail-with-body` are mutually exclusive — they implement different non-2xx failure semantics (`--fail` discards the body, `--fail-with-body` surfaces it). The 1.8.52 + Unreleased draft-aware work added `--fail-with-body` without removing the preexisting `-f`. Use `-sS` (silent + show-errors) instead of `-fsS`; `--fail-with-body` already supplies the non-2xx failure path. Fixes html-to-markdown v3.6.0 Publish run 27423263158 `Publish Zig package metadata` failure.
- **`publish-zig`: address the release by id, not tag, for draft-release support.** `gh release upload <tag>`, `gh release view <tag>`, and `gh release edit <tag>` all resolve the tag via `GET /repos/.../releases/tags/<tag>`, which only returns *published* releases — drafts 404 regardless of token scope. The publish workflows in xberg-io/* keep the release in draft until the terminal `release-finalize` step, so every `publish-zig` invocation prior to that step failed with `release not found`. The action now (a) resolves `tag → release_id` via the paginated `/repos/.../releases` listing (which surfaces drafts when the calling token has `contents:write`, falling back to `/releases/tags/<tag>` so published-only tokens still work), (b) uploads the asset via `POST https://uploads.github.com/repos/.../releases/{id}/assets` with explicit `--clobber` (DELETE-then-POST) semantics, and (c) computes the Zig content multihash from the *local* tarball via `zig fetch <path>` — the public release-asset URL 404s for draft assets, and the hash is content-addressed so a local fetch yields the identical hash a consumer would compute against the eventual published URL. Release-notes append now uses `PATCH /repos/.../releases/{id}`. Fixes html-to-markdown v3.6.0-rc.24 Publish run 27400690680 `Publish Zig package metadata` failure. Mirrors the same draft-aware migration applied to `generate-elixir-checksums` and `verify-release-assets` in v1.8.52.
- **`publish-npm`: skip stub packages without `.node` native bindings.** Platform-specific npm package placeholders (e.g., `@kreuzberg/node-linux-arm64-musl` bootstrap stubs created in rc.8) contain only `README.md` and `package.json` with no prebuilt `.node` binary. When npm attempted to publish these empty payloads with `--provenance`, Sigstore transparency-log creation failed with `TLOG_CREATE_ENTRY_ERROR` during the signature generation phase. The script now inspects each `.tgz` tarball, skips any without a `.node` file, and logs the count of skipped stubs. Genuine build failures (missing binaries due to CI issues) are still published so the registry entry exists for diagnostics. Fixes kreuzberg rc.10 Publish run 27193384688 `@kreuzberg/node-linux-arm64-musl` failure.
- **`build-elixir-natives` and `build-php-extension`: force `/MD` CRT for cc-rs MSVC on Windows.** Linking `kreuzberg_nif.dll` and `kreuzberg_php.dll` on `x86_64-pc-windows-msvc` failed with `LNK1319: mismatch detected for 'RuntimeLibrary': MT_StaticRelease vs MD_DynamicRelease`. Root cause: `libkreuzberg_tesseract.rlib` is built by cmake-rs (defaults to `/MD`); `libesaxx_rs.rlib` (transitively via `gliner` → `tokenizers`) is built by cc-rs (defaults to `/MT`). When both rlibs are linked into the same cdylib, the mismatch trips the linker error. Both composites now set `CFLAGS_x86_64_pc_windows_msvc`, `CXXFLAGS_x86_64_pc_windows_msvc`, `CFLAGS_i686_pc_windows_msvc`, and `CXXFLAGS_i686_pc_windows_msvc` to `/MD` in the Windows build steps' `env:` blocks. cc-rs honors target-suffixed env vars only when actually compiling for that target, so non-Windows builds are unaffected. Fixes the recurring rc.7→rc.10 "Build Elixir NIF (windows-x86_64)" and "Build PHP extension (windows-x86_64)" failures.

## [1.8.52] - 2026-06-09

### Fixed

- **`publish-zig`: make release-asset upload idempotent (`--clobber` unconditionally).** Previously `gh release upload` ran without `--clobber` when `update-existing` was not opted in, so reruns of a partially-failed job (e.g. the `zig fetch` CDN-propagation retry budget timed out after a successful upload) aborted with `asset under the same name already exists`. `--clobber` is now unconditional: first upload still creates the asset, and any subsequent rerun cleanly overwrites it. Fixes kreuzcrawl v0.3.0-rc.53 publish run 27221636352 attempt 2 Zig metadata failure.
- **`generate-elixir-checksums`: download NIF assets via authenticated `gh release download` instead of the public CDN URL.** The script hit `https://github.com/<repo>/releases/download/<tag>/<name>` which only resolves for *published* releases — but the kreuzberg-dev publish workflows keep the release in draft until the terminal `release-finalize` job (which is itself gated on this checksum step), so the public URL always 404'd. `gh release download <tag> --pattern <name>` uses the authenticated GitHub API and works against both draft and published releases. Added a `token` input (defaults to the job's `GITHUB_TOKEN`); pass an App token with `contents:write` to see drafts. 20×10s retry loop preserved for transient API blips. Fixes kreuzcrawl v0.3.0-rc.53 publish run 27221636352 attempt 2 `Publish Elixir Hex package > Generate checksums from GitHub release` 404.
- **`verify-release-assets`: locate releases by tag via `GET /repos/{owner}/{repo}/releases` (handles drafts), falling back to `gh release view <tag>`.** The previous lookup used `gh release view <tag>` exclusively, which calls `GET /releases/tags/<tag>` — that endpoint only finds *published* releases. Drafts have no real Git tag and were invisible, so verification 404'd while `release-finalize` was blocked behind it. Now lists releases via the paginated API (which returns drafts when the calling token has draft visibility) and matches by `tag_name`; if that returns no match, falls back to `gh release view <tag>` so the action still works against published releases via tokens without draft scope. Fixes kreuzcrawl v0.3.0-rc.53 publish run 27221636352 attempt 2 `Verify release assets` failure.

## [1.8.51] - 2026-06-09

### Fixed

- **`publish-npm`: retry `npm publish` on Sigstore Rekor / transient network errors.** `npm publish --provenance` makes an HTTP call to `https://rekor.sigstore.dev/api/v1/log/entries` to create a transparency-log entry. When Rekor times out or aborts the response mid-fetch, npm returns `TLOG_CREATE_ENTRY_ERROR` and the publish step fails. The previous loop ran a single `npm publish` per tarball with no retry, so one transient Rekor blip failed an entire multi-platform publish (7 of 8 tarballs published, the 8th tripped the publish job). Wrapped the per-tgz publish call with 4× exponential backoff (5s, 10s, 20s, 40s) on `TLOG_CREATE_ENTRY_ERROR`, `error creating tlog entry`, `ETIMEDOUT`, `ECONNRESET`, `ECONNREFUSED`, `EAI_AGAIN`, `socket hang up`, `aborted`, `fetch failed`, and HTTP 5xx. Non-transient failures (auth, schema, already-published) fail immediately. Fixes kreuzberg rc.10 Publish run 27193384688 `kreuzberg-node-linux-arm64-musl-5.0.0-rc.10.tgz` failure.

## [1.8.50] - 2026-06-09

### Fixed

- **`build-csharp-natives`: extend `copy_macos_runtime_deps` search paths to find pyke-ORT prebuilt dylib.** The previous search resolved `dylib_path.parent.parent` (`target/<triple>/`, not the release dir) plus `target/release/` (wrong dir for cross-target builds), so `libonnxruntime.1.24.2.dylib` was never staged into the NuGet `runtimes/osx-arm64/native/` directory. Consumers then failed to load `libkreuzberg_ffi.dylib` with `Library not loaded: @rpath/libonnxruntime.1.24.2.dylib`. Now searches `dylib_path.parent` (release dir + `deps/`), recursively under `release/build/` (where `ort-sys` drops the prebuilt), and the pyke ORT cache (`$XDG_CACHE_HOME/ort.pyke.io/dfbin/`, `~/.cache/ort.pyke.io/dfbin/`, `~/Library/Caches/ort.pyke.io/dfbin/`). Reproduced by kreuzberg rc.10 test_apps smoke C# 8/8 fail.

## [1.8.49] - 2026-06-09

### Fixed

- **`publish-github-release/scripts/upload_artifacts.py`: retry transient SSL/network errors with exponential backoff.** The script uploaded each asset with a single `urllib.request.urlopen` call and exited on any exception. Large assets (~30 MB+) occasionally trigger `ssl.SSLEOFError: EOF occurred in violation of protocol` mid-upload from the GitHub uploads endpoint, which is transient. Now retries 5× with exponential backoff (2s, 4s, 8s, 16s) on `URLError`, `ssl.SSLError`, `ConnectionError`, `TimeoutError`, and HTTP 5xx. Fixes tslp v1.9.0-rc.29 publish run 27192809836 `Build parser-sources bundle` failure.

## [1.8.48] - 2026-06-09

### Fixed

- **`build-python-wheels`: wipe `~/.cargo` and `~/.rustup` before installing rustup on macOS.** macOS-latest runner images preinstall a Rust toolchain. When maturin then triggers `rustup install 1.95` via `rust-toolchain.toml`, rustup finds the partially installed 1.95 toolchain (`bin/cargo-clippy` already present) and rolls the install back with `failed to install component 'clippy-preview-aarch64-apple-darwin', detected conflict: 'bin/cargo-clippy'`. The 1.8.47 fix removed the action's own `dtolnay/rust-toolchain` step, but the runner-image preinstall stayed and reproduced the same conflict in kreuzberg rc.10 Publish run 27193384688 macOS wheel job 80282051523. Now `CIBW_BEFORE_ALL_MACOS` wipes both dirs before sourcing rustup-init, so the in-cibw rustup owns the entire toolchain state.
- **`publish-zig`: extend release-asset CDN propagation retry budget.** Bumped `zig fetch` retries from 8×5s (40s budget) to 20×10s (200s budget). Release dispatches under load have shown the GitHub release-asset CDN (`releases/download/<tag>/<name>` redirect target) answer 404 for >90s after `gh release upload` returns, exceeding the prior budget and failing the action with a misleading "failed after N attempts" error. The new budget absorbs the propagation race without flaking. Fixes kreuzcrawl v0.3.0-rc.52 publish run 27188386957 Zig metadata failure.
- **`build-swift-artifactbundle`: substitute `v__ALEF_SWIFT_VERSION__` placeholder in Package.swift.** Alef's canonical `Package.swift` seed uses two placeholders in the `.binaryTarget` block: `checksum: "__ALEF_SWIFT_CHECKSUM__"` and `url: ".../releases/download/v__ALEF_SWIFT_VERSION__/..."`. The action substituted only the checksum (plus a bogus `__ALEF_SWIFT_BUNDLE_URL__` line that never matched), so the published manifest shipped a literal `v__ALEF_SWIFT_VERSION__` in the URL and SwiftPM downloads 404'd. Added a `package-version` input; when set, the action also runs `sed -i.bak 's|v__ALEF_SWIFT_VERSION__|v${PACKAGE_VERSION}|g'` against the manifest. The second sed now uses `-i.bak` so it works on both macOS BSD sed and GNU sed. Removed the bogus URL-placeholder line. Fixes kreuzcrawl v0.3.0-rc.52 Swift artifactbundle failure.
- **`generate-elixir-checksums`: retry NIF download on 404 to absorb release-asset CDN propagation.** The script downloaded each `libfoo-vX.Y.Z-nif-2.*.so.tar.gz` once and exited on failure. Right after `gh release upload` returns, the `releases/download/<tag>/...` CDN may still 404 for 60–200s, so the Hex publish job failed even though the assets had been uploaded successfully. Now retries 20×10s on HTTP 404 (other HTTP errors and non-HTTP exceptions fail immediately). Fixes kreuzcrawl v0.3.0-rc.52 Publish Elixir Hex failure.
- **`verify-release-assets`: retry `gh release view` on transient failure.** A freshly created release can briefly answer 404 from `gh release view` when the GitHub API hits a stale read replica right after `gh release create` returns — the write has acked but the read replica has not converged. Now retries 20×10s. Same root cause as the publish-zig propagation race. Fixes kreuzcrawl v0.3.0-rc.52 Verify release assets failure (`gh release view failed for tag v0.3.0-rc.52: release not found` despite the release existing).

## [1.8.47] - 2026-06-09

### Fixed

- **`publish-pub`: wire GitHub OIDC token to pub.dev trusted publishing.** `dart pub publish --force` requires OAuth2 credentials when publishing to pub.dev. Added a step to exchange the GitHub OIDC token for pub.dev credentials and write them to `~/.config/dart/pub-credentials.json` before the publish step. Fixes `Authentication failed!` errors in Dart package publish workflows.
- **`build-python-wheels`: remove conflicting macOS Rust toolchain pre-installation.** The action pre-installed Rust via `dtolnay/rust-toolchain@stable`, which conflicted with cibuildwheel's own `CIBW_BEFORE_ALL_MACOS` rustup installation. When both ran, the second rustup would fail with "detected conflict: bin/cargo-clippy" because clippy was already installed by the first. Removed the dtolnay step on macOS; cibuildwheel now handles the full Rust setup. Fixes macOS wheel build failures in rc.8+.
- **`build-python-sdist`: ensure absolute output path for split-layout maturin sdist.** When building split-layout Python packages (pyproject.toml in packages/python/, crate at crates/<name>/Cargo.toml), the script changes directory into the package dir before invoking maturin. If `OUTPUT_DIR` is passed as a relative path, it becomes invalid after the cd. Now converts OUTPUT_DIR to an absolute path before cd. Fixes "Failed to build source distribution, pyproject.toml not found" errors in split-layout sdist builds.

## [1.8.46] - 2026-06-08

### Added

- **`prepare-release-metadata`: declare `release_kotlin_android` output.** alef >= 0.23.43 emits a `release_kotlin_android` field in `release-metadata --json` so consuming workflows can gate their kotlin-android publish jobs (Maven Central via Gradle) the same way `release_kotlin` gates the JVM-only Kotlin package. Without this declaration the value reached `$GITHUB_OUTPUT` but `needs.prepare.outputs.release_kotlin_android` returned empty and the `if:` gate evaluated false, causing every kotlin-android job in kreuzcrawl v0.3.0-rc.50/v0.3.0-rc.51 to skip silently. Companion to the alef 0.23.43 `ALL_RELEASE_TARGETS` addition.

## [1.8.45] - 2026-06-08

### Added

- **`finalize-release`: `go-strip-major-version` input.** Default `true` preserves the existing behavior of stripping a trailing `/vN` (N>=2) segment from `go-module-path` before composing the Go module subdir tag. Set to `false` when `go.mod` lives inside the major-version subdirectory itself (e.g. `packages/go/v5/go.mod`); the tag then becomes `packages/go/v5/{tag}` so Go's module proxy resolves `go.mod` from that subtree. Required by kreuzberg v5 layout, where the Go module sits at `packages/go/v5/go.mod` rather than at the stripped parent. Fixes `missing go.mod at revision v5.0.0-rc.7` resolution failures.

## [1.8.44] - 2026-06-08

### Fixed

- **`build-python-sdist`: drop `-m` from the split-layout `maturin sdist` invocation.** 1.8.42 + 1.8.43 passed `-m <crate>/Cargo.toml` to `maturin sdist`. With `-m`, maturin derives the sdist filename from the Rust crate's `[package].name` (e.g. `kreuzcrawl_py-0.3.0rc50.tar.gz` for crate `kreuzcrawl-py`) instead of pyproject's `[project].name` (`kreuzcrawl`). That tar then uploads to PyPI under the wrong project name and the OIDC publish fails with `400 Non-user identities cannot create new projects` because the Trusted Publisher is registered for `kreuzcrawl`, not `kreuzcrawl_py`. Now matches pre-1.8.39 behavior: `cd <package-dir> && maturin sdist --out <out>`. Maturin resolves `[tool.maturin].manifest-path` from the pyproject relative to `cwd`, so the split layout still works without `-m`. Fixes Publish to PyPI in kreuzcrawl v0.3.0-rc.50 publish run 27119781847 attempt 2.

## [1.8.43] - 2026-06-08

### Fixed

- **`build-python-sdist`: cd into `package-dir` (not workspace root) when invoking maturin for split layouts.** 1.8.42 ran `maturin sdist -m <crate>/Cargo.toml --out <dir>` from `$GITHUB_WORKSPACE`. That picks up the workspace-root `pyproject.toml` when one exists with a different build-backend (e.g. tslp's root pyproject uses `hatchling.build` for tooling). The generated sdist then declared `build-backend = "hatchling.build"`, so the publish smoke step failed `BackendUnavailable: Cannot import 'hatchling.build'`. The script now `cd`s into `package-dir` first so maturin reads its `pyproject.toml` (with `build-backend = "maturin"`), and passes `-m` for the out-of-tree crate path.

## [1.8.42] - 2026-06-08

### Fixed

- **`build-python-sdist`: handle split package layouts (pyproject in `packages/python/`, crate at `crates/<name>/Cargo.toml`).** The 1.8.39 out-of-workspace path assumed `package-dir` always contains a `Cargo.toml`; in monorepos like tslp the Python package lives next to its pyproject only, with the actual Rust crate referenced via `[tool.maturin] manifest-path`. The script now detects the split layout, resolves `manifest-path` from pyproject, and runs `maturin sdist -m <resolved> --out <dir>` directly from the workspace root (skipping the temp-dir copy + workspace-strip + `cargo generate-lockfile`, which can't work when the dir has no Cargo.toml). Fixes Python sdist publish-blocker on tslp rc.26.

## [1.8.41] - 2026-06-08

### Fixed

- **`build-php-extension` (Windows): replace bogus `New-TemporaryDirectory` cmdlet with `New-Item -ItemType Directory`.** The 1.8.39 out-of-workspace PowerShell branch called `New-TemporaryDirectory`, which is not a built-in PowerShell cmdlet (.NET only exposes `New-TemporaryFile`). Every Windows PHP extension job in kreuzberg rc.7 failed with `The term 'New-TemporaryDirectory' is not recognized`. Replaced with `New-Item -ItemType Directory -Path (Join-Path $env:RUNNER_TEMP "build-$([Guid]::NewGuid())")`.

## [1.8.40] - 2026-06-08

### Fixed

- **`install-task`: extend retry budget to ride out GitHub release CDN incidents.** Per commit `a9470f4`. Bumps `max_attempts` from 3 to 6 and initial backoff from 2s to 5s, growing the total retry window from ~14s to ~155s (5+10+20+40+80). The prior budget was too short to outlast typical multi-minute GH releases CDN 504 incidents, which just took out CI Rust, CI Validate, CI Dart, CI Zig, and Publish Rust crates jobs across tslp rc.26. Mirrors the matching tslp `build.rs` `fetch_bytes` retry hardening committed in `tree-sitter-language-pack@3e6de6646`.

## [1.8.39] - 2026-06-08

### Fixed

- **`build-php-extension` + `build-python-sdist`: build out-of-workspace to avoid Cargo `links` conflicts.** Per commit `6c5aed0`. After `rewrite-native-deps` converts path-deps to registry version-deps, Cargo still resolves the workspace dep graph and sees BOTH the registry `kreuzberg-tesseract@<rc>` (via the binding crate) AND the local path `kreuzberg-tesseract` (via `tools/benchmark-harness → kreuzberg → kreuzberg-tesseract`). Both declare `links = "kreuzberg_tesseract"`, violating Cargo's one-package-per-links-key invariant — resolver bails with `failed to select a version for kreuzberg-tesseract`. Each action now copies the binding crate to a tempdir, strips `workspace = true` directives, runs `cargo generate-lockfile` from a clean slate, builds in isolation, then copies artifacts back to `$GITHUB_WORKSPACE/target/release/`. Fixes 13 publish-blocker jobs across kreuzberg rc.4 + rc.5 (Python sdist + all 12 PHP × {8.2, 8.3, 8.4} × {linux-x86_64, linux-arm64, macos-arm64, windows-x86_64}).
- **`publish-npm`: pass `--force` to `npm publish` to allow first-publish of new scoped subpackages.** Per commit `9dbae75`. npm CLI v11+ validates scoped package names before publishing; a brand-new platform subpackage (e.g. `@kreuzberg/node-linux-arm64-musl@<rc>`) trips a 404 on the pre-publish metadata lookup because the registry has no prior version. `--force` bypasses that check while leaving server-side integrity and version-conflict enforcement intact.
- **`publish-rubygems`: use positional gemfile arg for `gem spec` (RubyGems 3.3+ dropped `--file`).** Per commit `901855b`. The prior fix added `--file <path>`, but RubyGems 3.3 removed the flag — newer toolchains failed with `invalid option: --file`. Reverted to `gem spec <gemfile>` positional form, which works across RubyGems 3.x.

## [1.8.36] - 2026-06-07

### Fixed

- **`publish-maven`: write settings.xml with literal credentials to bypass env-resolution 403.** Per commit `74299ae`: `deploy.py` now writes a temp `settings.xml` with the literal username/password (XML-escaped, chmod 0600, `-s <file>` passed to mvn). Fixes Sonatype Central HTTP 403 on RC.46/RC.47 where `${env.MAVEN_USERNAME}` / `${env.MAVEN_PASSWORD}` placeholders silently resolved to empty strings.

### Changed

- `prek autoupdate` + `uv sync --upgrade`: bump `xberg-io/pre-commit-hooks` rev pin to `v2.1.6`; refresh dev dependencies.

## [1.8.35] - 2026-06-07

### Added

- **`check-registry`: retry alef CLI with exponential backoff (5 attempts, 2s/4s/8s/16s).** Per commit `089bdc4`. Absorbs transient registry-existence-check 5xx responses during the prepare stage.

### Fixed

- `swift-artifactbundle`: parameterize `binary-target-name` (commit `8e36532`).
- `ai-rulez`: regenerate manifest to include `commit-procedure.mdc` (commit `0246c3b`).

## [1.8.34] - 2026-06-06

### Fixed

- Drop `x86_64-apple-ios` from Dart iOS XCFramework matrix (commit `cd60600`); pyke ORT has no prebuilt artifact for that triple.

## [1.8.33] - 2026-06-05

### Fixed

- **`build-elixir-natives`: rename macOS NIF `.dylib` to `.so` in upload archive.** `rustler_precompiled 0.9.0`'s `lib_name_with_ext/2` hardcodes `.so` for every non-Windows consumer-side download URL (no `.dylib` branch exists). Previously, macOS NIFs were uploaded as `libkreuzcrawl_nif-v...-aarch64-apple-darwin.dylib.tar.gz` but the Hex publish step's `mix rustler_precompiled.download` tried `…aarch64-apple-darwin.so.tar.gz` → 404 → exit 1. Split `lib_extension` into `cargo_lib_extension` (filesystem extension Cargo writes — keeps `.dylib` for finding the file in `target/<triple>/release/`) and `asset_extension` (extension RustlerPrecompiled expects in the download URL — always `.so` for non-Windows). Renames `libkreuzcrawl_nif.dylib` → `…aarch64-apple-darwin.so` inside the tarball; Erlang loads NIFs by contents, not filename. Fixes `Publish Elixir Hex package` on RC.41+.

## [1.8.32] - 2026-06-05

### Fixed

- **`setup-node-workspace`: install pnpm via `npm install -g pnpm@10` after Node setup.** Both `pnpm/action-setup@v6` paths (`standalone: true` and default) route through `@pnpm/exe`, whose SEA-built binary fails on Intel macOS (`@pnpm/exe does not ship a working binary for Intel macOS (darwin-x64) due to an upstream Node.js SEA bug`) and requires `npm` on PATH on ARM Linux (`spawn npm ENOENT` before `actions/setup-node` ever ran because pnpm setup was first). Pinning to v10 did not help — the SEA breakage affects `@pnpm/exe@10` and `@pnpm/exe@11` equally. Reorder steps so `actions/setup-node@v6` runs first (provides Node + npm on every platform, including ARM Linux), then install pnpm with `npm install --global pnpm@10` (the JS package — uses the system Node.js, no SEA). Drops the `cache: pnpm` setup-node hint since pnpm isn't yet installed at that point. Fixes Node bindings publish on `x86_64-apple-darwin` and `aarch64-unknown-linux-gnu`.

## [1.8.31] - 2026-06-05

### Fixed

- **`setup-node-workspace`: suppress `packageManager` read when pinning pnpm version.** When `pnpm/action-setup@v6` sees both a `version` input and a `packageManager` field in `package.json`, it errors `ERR_PNPM_BAD_PM_VERSION: Multiple versions of pnpm specified` and aborts. Set `package_json_file: .pnpm-action-skip-packagemanager` (a non-existent path) so the action ignores the `packageManager` field and unconditionally honors the `version: "10"` input. Local dev keeps its `packageManager: pnpm@11.5.1` pin in `package.json`.

## [1.8.30] - 2026-06-05

### Fixed

- **`setup-node-workspace`: pin pnpm to 10.x for Intel macOS SEA bug.** `@pnpm/exe` 11+ ships a broken SEA binary for Intel macOS (darwin-x64): the upstream Node.js SEA bug surfaces as `npm error @pnpm/exe does not ship a working binary for Intel macOS` during `pnpm/action-setup`, killing the install before any job code runs. Pinned `version: "10"` to dodge the SEA-broken 11.x binaries. Upstream: pnpm/pnpm#11423, nodejs/node#62893. Lockfile 9.0 is forward/backward compatible between pnpm 10 and 11, so CI on 10 stays compatible with local dev on 11.5.1. (Superseded by v1.8.32 — the SEA bug affects v10 too.)

## [1.8.29] - 2026-06-05

### Fixed

- **`publish-crates`: line-buffer Python stdout in `publish.py`.** GitHub Actions captures the script's stdout block-buffered, so per-crate `Publishing …`, `Published …`, and index-poll progress lines are silently dropped when the job is cancelled by `timeout-minutes`. Adding `sys.stdout.reconfigure(line_buffering=True)` (and the same for stderr) at module top makes the captured log reflect what actually executed before a cancel, which is the only way to diagnose a 30-minute publish that returned no log output between two stderr-only `WARNING: … not visible in crates.io index after 600s` lines. No behavioural change to publishing itself.

## [1.8.28] - 2026-06-05

### Fixed

- **`lint-docs`: harden `prek` installer against GitHub API rate-limit 403s.** The previous `Install prek` step in `lint-docs/action.yml` called `curl -s https://api.github.com/repos/j178/prek/releases/latest` unauthenticated with no retries. When the runner hit GitHub's anonymous rate limit (observed `curl: (22) The requested URL returned error: 403`), `set -euo pipefail` propagated the empty `VERSION` into the download URL and the step crashed. Switched to authenticated `gh api repos/j178/prek/releases/latest --jq '.tag_name'` (with `GH_TOKEN: ${{ github.token }}`), wrapped in a 3-attempt retry loop with a `PREK_FALLBACK_VERSION=v0.4.4` final fallback. Download is also retried 3× via `curl --retry 3 --retry-delay 2` plus an outer attempt loop. Eliminates the flaky 403 failure mode for `CI Docs` on busy runner shards.

- **`build-ruby-gem`: replace `rustc --print host-triple` with `host-tuple` on Windows.** rustc 1.95 renamed `--print host-triple` to `--print host-tuple`; the diagnostic step on the Windows path used the old form and failed `Process completed with exit code 1`, taking down the Ruby gem publish for `windows-x64`.

## [1.8.27] - 2026-06-05

### Fixed

- **`setup-node-workspace`: enable pnpm standalone install.** `pnpm/action-setup@v6` defaults to a `npm`-based self-installer that fails with `spawn npm ENOENT` on GitHub-hosted ARM Linux runners (Node/npm are not preinstalled). Setting `standalone: true` makes the action download the pnpm binary directly without requiring npm on PATH. Fixes Node bindings publish on `aarch64-unknown-linux-gnu`.

## [1.8.26] - 2026-06-05

### Fixed

- **`setup-onnx-runtime`: repair broken script paths.** v1.8.24 shipped the action referencing scripts at the kreuzberg-internal path layout `scripts/ci/actions/setup-onnx-runtime/<file>.sh`, but the actual scripts were copied into the action subdirectory at `setup-onnx-runtime/scripts/<file>.sh`. The action invocations now failed immediately. Fixed all 3 occurrences (linux.sh, macos.sh, windows.ps1) to use the GHA-canonical `${{ github.action_path }}/scripts/<file>.sh` expression, which correctly resolves to the action's directory regardless of the consumer's checkout layout.

- **`setup-tesseract-cache`: repair broken script paths.** v1.8.24 shipped the action referencing scripts at the kreuzberg-internal path layout `scripts/ci/actions/setup-tesseract-cache/<file>.sh`, but the actual scripts were copied into the action subdirectory at `setup-tesseract-cache/scripts/<file>.sh`. The action invocations now failed immediately. Fixed all 4 occurrences (clean-dirs.sh, setup-dirs.sh, clean-target-cache.sh, set-outputs.sh) to use the GHA-canonical `${{ github.action_path }}/scripts/<file>.sh` expression, which correctly resolves to the action's directory regardless of the consumer's checkout layout.

- **`setup-tesseract-cache/scripts/clean-dirs.sh`: harden against unset vars (SC2115).** The `rm -rf` commands did not guard against unset `cache_dir_prefix` or `label` vars, creating a risk of inadvertent root deletion if either var failed to resolve. Added `${var:?message}` guards to all `rm -rf` calls; script now fails fast with a clear error if required parameters are missing.

- **`.github/workflows/test-setup-go-cgo-env.yml`: add required inputs.** v1.8.25 made `ffi-crate-dir` and `ffi-lib-name` required inputs to `setup-go-cgo-env`, but the test workflow was calling the action without passing them. Added `with: { ffi-crate-dir: "crates/kreuzberg-ffi", ffi-lib-name: "kreuzberg_ffi" }` to satisfy the action contract; the test now passes actionlint validation.

### Added

- **`test-setup-onnx-runtime.yml`: new test workflow.** Validates the `setup-onnx-runtime` action on Linux and macOS (workflow_dispatch + path trigger). Verifies that ONNX Runtime libraries are downloaded and staged to the requested `dest-dir` without errors.

- **`test-setup-tesseract-cache.yml`: new test workflow.** Validates the `setup-tesseract-cache` action on Linux (workflow_dispatch + path trigger). Creates a fixture Cargo.toml, invokes the action, and verifies cache directory creation and outputs (cache-dir, cache-enabled, docker-options).

## [1.8.25] - 2026-06-05

### Changed

- **`build-go-ffi`: make `crate-name` and `header-path` required inputs.** Drops kreuzberg-specific defaults (`default: "kreuzberg-ffi"` and `default: "crates/kreuzberg-ffi/include/kreuzberg.h"`). Callers must now explicitly pass these inputs for all consumers.

- **`setup-go-cgo-env`: make `ffi-crate-dir` and `ffi-lib-name` required inputs.** Drops kreuzberg defaults (`default: "crates/kreuzberg-ffi"` and `default: "kreuzberg_ffi"`). Callers must now explicitly specify FFI library paths.

- **`build-elixir-natives`: make `nif-crate-name` and `nif-crate-path` required inputs.** Drops kreuzberg defaults (`default: "kreuzberg_nif"` and `default: "packages/elixir/native/kreuzberg_nif"`). Callers must now explicitly pass NIF crate metadata.

- **`build-dart-package`: make `package-dir` and `crate-name` required inputs.** Drops kreuzberg defaults (`default: "packages/dart"` and `default: "kreuzberg-dart"`). Callers must now explicitly pass package directory and crate name.

- **`build-java-natives`: make `crate-name` required input.** Drops kreuzberg default (`default: "kreuzberg-ffi"`). Callers must now explicitly specify the FFI crate to build.

## [1.8.24] - 2026-06-05

### Added

- **`setup-onnx-runtime`: new composite action.** Upstream the kreuzberg-local action for downloading and staging ONNX Runtime libraries. Accepts parameterized `dest-dir` (required), `ort-version` (required), `arch-id` (optional), and `strategy` (optional). Provides Linux, macOS, and Windows platform-specific setup scripts. (`setup-onnx-runtime/action.yml`, `setup-onnx-runtime/scripts/{linux.sh,macos.sh,windows.ps1}`)

- **`setup-tesseract-cache`: new composite action.** Upstream the kreuzberg-local action for managing tesseract build caches per architecture. Requires parameterized `label`, `cache-dir-prefix`, and `tesseract-crate-toml` inputs (no kreuzberg-specific defaults). Handles cache setup/cleanup, per-target cleanup, and Docker environment configuration. (`setup-tesseract-cache/action.yml`, `setup-tesseract-cache/scripts/{setup-dirs.sh,clean-dirs.sh,clean-target-cache.sh,set-outputs.sh}`)

## [1.8.23] - 2026-06-04

### Added

- **`build-swift-artifactbundle`: substitute Package.swift checksum placeholders.** When building a Swift artifact bundle from a Rust FFI library, the wrapper Package.swift often needs the tarball checksum and/or URL to be filled in before distribution. Set the `package-manifest-path` input to the path of Package.swift relative to the action's working directory; the action will substitute all occurrences of `__ALEF_SWIFT_CHECKSUM__` and `__ALEF_SWIFT_BUNDLE_URL__` with the resolved checksum. The substituted manifest path is returned in the `package-manifest-updated` output for consumers to upload to GitHub Release or commit to version control. (`build-swift-artifactbundle/action.yml`, `build-swift-artifactbundle/scripts/build.sh`, `tests/test_build_swift_artifactbundle.sh`)

### Fixed

- **`build-node-napi`: verify platform-specific .node binary is staged before tarball packing.** The "napi artifacts" step of build-node-napi outputs platform-specific `.node` binaries into each platform's subdirectory (e.g., `prebuilds/darwin-arm64/node.node`). However, if the build completes without errors but the binary ends up in an unexpected location, the packing step silently creates a tarball missing the binary — downstream consumers then get extraction failures or "Cannot find module" errors. A new verification step now confirms the `.node` file exists in the platform subdirectory before packing; if missing, the action fails fast with a clear error message. Surfaced by kreuzberg rc.12 where darwin-arm64 binding build succeeded but the prebuilt binary was missing from the tarball. (`build-node-napi/action.yml`, `.github/workflows/test-build-node-napi.yml`)

- **`build-go-ffi`: document Go generate consumer contract and html-to-markdown usage.** The build-go-ffi action produces platform-specific FFI libraries (libfoo_ffi.so, libfoo_ffi.dylib, foo_ffi.dll) and C headers in a tarball archive. Go binding consumers consume these via `go generate` using a standardized filename pattern: `{lib-name}-{rust-target}.tar.gz` downloaded from the parent repo's GitHub Release. Added comprehensive README documenting the archive layout contract, usage flow, and a concrete html-to-markdown example showing correct crate names (html-to-markdown-core vs libhtml2md), header paths, and integration patterns. (`build-go-ffi/README.md`)

- **`publish-packagist`: exit non-zero if polling timeout occurs after webhook trigger.** The publish-packagist action triggers a Packagist webhook and polls until the new version appears. On timeout, the prior behavior was to exit 0 with a warning, allowing the workflow to continue even though the package was not actually published — downstream release workflows would then fail silently or with confusing errors when consumers tried to `composer require` the unavailable version. Now exits with status 1 on polling timeout, blocking the release workflow and surfacing the failure. Also enhanced with prerelease detection (rc, alpha, beta, dev suffixes) and Packagist stability constraint diagnostics to aid debugging of why a release didn't appear. (`publish-packagist/action.yml`, `publish-packagist/scripts/publish.py`)

## [1.8.22] - 2026-06-04

### Added

- **`publish-zig`: multi-platform packaging mode (`multi-platform-ffi-dir`).** When a consumer
  has FFI libraries pre-built for several Rust target triples and wants a single Zig tarball
  that `zig fetch --save` resolves on any supported host, set `multi-platform-ffi-dir` to a
  dir laid out per Rust RID (`linux-x64/<libs>`, `osx-arm64/<libs>`, `win-x64/<libs>`, plus a
  shared `include/<header>` dir). The action copies each RID's libraries into
  `<working-directory>/lib/<canonical-target-triple>/`, patches `build.zig.zon` `.paths` to
  allowlist `lib` and `include` (otherwise `zig fetch` consumers cannot see them), and
  overwrites `build.zig` with a `ridDir(target)` switch that resolves the correct
  `lib/<rid>` subdir from Zig's compile-time target. Two new required inputs
  (`module-name`, `ffi-lib-name`) parameterise the rewritten module export and
  `linkSystemLibrary` call. Mutually exclusive with `use-alef-package`. Closes the
  regression where downstream `zig fetch` consumers compiled the in-tree `build.zig`
  pointing at workspace-relative `../../target/release` and failed with
  `unable to find dynamic system library` errors. (`publish-zig/action.yml`,
  `publish-zig/README.md`, `.github/workflows/test-publish-actions.yml`)

### Fixed

- **`build-rust-ffi`: verify macOS dylib install_name was actually rewritten.** The "Fix macOS dylib install_name" step
  calls `install_name_tool -id @rpath/<name>.dylib <path>` to replace the absolute build-path `LC_ID_DYLIB` with an
  `@rpath`-relative one for portability. However, `install_name_tool` can silently fail in edge cases (read-only
  filesystem, permission issues, corrupted binary) without returning a non-zero exit code, resulting in dylibs being
  distributed to consumers with the broken absolute path still embedded. The script now verifies the fix by running
  `otool -D` after the rewrite and confirming the new `@rpath` install_name is present; if not, it exits with an
  error and logs the actual install_name for debugging. (`build-rust-ffi/scripts/fix_dylib_install_name.py`)

## [1.8.18] - 2026-06-01

### Fixed

- **`setup-elixir`: normalize `ImageOS` on arm64 runners so `erlef/setup-beam@v1` resolves.** On
  `ubuntu-24.04-arm` GitHub-hosted runners the runtime `ImageOS=ubuntu24-arm64` is not in the
  set the action recognises (`ubuntu22`, `ubuntu24`, `win*`, `macos*`), so it fails with
  `Tried to map a target OS from env. variable 'ImageOS' (got ubuntu24-arm64), but failed`.
  The composite now rewrites `ImageOS` to the non-suffixed form (`ubuntu24`/`ubuntu22`) before
  invoking `setup-beam`, restoring CI Lint on h2m's arm64 validator job.
  (`setup-elixir/action.yml`)

## [1.8.17] - 2026-06-01

### Fixed

- **`rewrite-native-deps`: strip workspace `[patch.*]` sections so consumer sdist builds resolve registry deps.**
  `alef publish prepare --lang …` correctly rewrites the binding crate's path-dep on the core crate to a registry
  version-dep, but it leaves any workspace-root `[patch.crates-io] core = { path = "..." }` (or other `[patch.*]`)
  untouched. When a consumer unpacks the sdist on a fresh machine the path no longer exists, but the patch override
  still wins over the registry dep — Cargo bails with `failed to read crates/<core>/Cargo.toml: No such file or
  directory`. The action now strips the entire `[patch.*]` block from the workspace `Cargo.toml` as a post-step;
  `[patch]` sections are workspace/dev affordances with no meaning in a published source distribution. Resolves
  xberg-io/html-to-markdown#390 (Alpine/musl `pip install` failure on every release since 3.5.1).
  (`rewrite-native-deps/action.yml`)

## [1.8.16] - 2026-05-29

### Fixed

- **`setup-chrome`: warm snapd + retry `snap install chromium` on linux-arm64.** Snapd on GitHub-hosted `ubuntu-*-arm` runners is frequently not fully seeded when the first `snap install` runs, which makes the install fail with the generic `error: cannot perform the following tasks:` and aborts the workflow. The action now starts `snapd.service`/`snapd.socket`, waits for `snap wait system seed.loaded`, and retries `snap install chromium --classic` up to 5 times with linear backoff (5/10/15/20s), re-warming snapd between attempts. Surfaced by kreuzcrawl `9be6b203b` CI E2E (python) on linux-arm64. (`setup-chrome/action.yml`)

## [1.8.6] - 2026-05-27

### Fixed

- **`publish-zig`: retry `zig fetch` through the release-asset propagation race.** The "Resolve Zig hash + URLs" step ran `zig fetch` against `releases/download/<tag>/<name>` immediately after the "Upload release asset" step returned. A freshly uploaded GitHub release asset can briefly answer `404 Not Found` from the asset CDN (the redirect target) until propagation completes, so the fetch failed non-deterministically — passing when propagation happened to be fast, failing when it lagged. The fetch now retries up to 8 times with a 5s backoff (≈40s ceiling), and the secondary SHA-256 `curl` gained `--retry 3 --retry-delay 2 --retry-all-errors` for the same reason. Surfaced by spikard v0.15.6-rc.9 Publish Release "Publish Zig metadata" (`zig fetch failed ... bad HTTP response code: '404 Not Found'` ~140ms after `Asset uploaded successfully`). (`publish-zig/action.yml`)

## [1.8.5] - 2026-05-27

### Added

### Changed

### Fixed

- **`setup-node-workspace`: honor `frozen-lockfile: false` by passing `--no-frozen-lockfile`.** pnpm defaults `frozen-lockfile=true` in CI, so the action's prior logic — which only *added* `--frozen-lockfile` when the input was `"true"` and otherwise passed no flag — still ran a frozen install in CI, silently ignoring `frozen-lockfile: false`. napi-rs workspaces whose main package pins platform `optionalDependencies` at a not-yet-published version (the release under test) cannot record those specifiers in the lockfile, so a frozen install fails with `ERR_PNPM_OUTDATED_LOCKFILE`. The action now passes `--no-frozen-lockfile` when the input is not `"true"`. Surfaced by spikard v0.15.6-rc.8 CI Rust/Validate (Setup Node). (`setup-node-workspace/action.yml`)
- **`build-ruby-gem`: switch the Windows linker to `lld` to handle rustc's brace-expanded archive args.** Recent mingw-w64-ucrt toolchain bumps (gcc 16.x) ship an `ld.exe` that does not brace-expand the `{libfoo,libbar,...}.rlib` shorthand rustc emits for cdylib link lines. The result is `ld.exe: cannot find  ■: No such file or directory` (mojibake of the literal `{`) and a failed Ruby gem build on x64-mingw-ucrt. The Windows install step now also installs `mingw-w64-ucrt-x86_64-lld`, and the compile step exports `CARGO_TARGET_X86_64_PC_WINDOWS_GNU_RUSTFLAGS='-C link-arg=-fuse-ld=lld'`. (The target-prefixed env var is required because rb-sys's cargo invocation does not propagate plain `RUSTFLAGS` to rustc — verified in kreuzcrawl rc.32 Publish Release job 77937367149, where the original `RUSTFLAGS` export was set but never reached the gcc command line.) Surfaced by kreuzcrawl v0.3.0-rc.31 Publish Release job 77914103699.
- **`install-alef`: pass `--force` to the `cargo install` source-build fallback.** When the release binary is missing (the tag-vs-binary-upload race) and the fallback runs on a runner that already has `alef` installed (cached image or a prior step), `cargo install` aborted with "binary `alef` already exists in destination". The unix and Windows fallbacks now use `--force` to overwrite, making installation idempotent. Surfaced via `check-registry` failing in consumer publish workflows.
- **`build-elixir-hex`: gate Cargo.lock generation on dry-run.** The "Generate Cargo.lock" step now only runs when `inputs.dry-run == 'true'`, which is the intended behavior when a dry-run publish bypasses the rewrite step (before the core crate is on crates.io). Previously the step always ran unconditionally, which was inconsistent with the documented workflow and failed the test assertion.

### Deprecated

### Removed

### Security

## [1.8.2] - 2026-05-26

### Fixed

- `publish-zig`: surface zig fetch + zig init stderr on failure. The "Resolve Zig hash + URLs" step captured both zig init and zig fetch output but suppressed stderr via `2>/dev/null` redirection, and the output capture itself was hidden in a subshell `$(...)` that exited silently on non-zero return when `set -e -o pipefail` was in effect. This left no diagnostic when zig commands failed — operators saw only the trailing "did not produce a hash" error with no root cause. The step now captures both stdout and stderr, runs each zig command with `set +e` to preserve the exit code, and prints the full captured output when failures occur, surfacing network timeouts, invalid URLs, corrupted tarballs, or zig toolchain errors.

- `build-elixir-natives`: pass `--manifest-path` through to musl docker `cargo build`. Elixir NIF crates often declare their own `[workspace]` block to escape the parent workspace, so `cargo -p <crate>` from the workspace root cannot find them. The non-musl native build path already passes `--manifest-path`; the musl docker path was missing it, causing aarch64-linux-musl builds to fail with `error: package ID specification 'kreuzberg_nif' did not match any packages`. The container mount at `/src` maps the host repo root, so the host path is converted to an in-container path before passing to cargo — preserving the path-translation contract expected by the build isolation.

## [1.8.1] - 2026-05-26

### Fixed

- **`homebrew-build-bottles`: strip stale bottle blocks before `brew install --build-bottle`.** A pre-existing formula can carry `bottle do … end` blocks left OUTSIDE its `class … end` body (historical GoReleaser output, or older merges that appended at end-of-file). Homebrew then fails to even load the formula with `undefined method 'bottle' for module Formulary::FormulaNamespace…`, so `brew install --build-bottle` dies before a fresh bottle can be built — and because the bottle merge step is gated on a successful build, the companion fix in `homebrew-merge-bottles` (1.7.2) could never run, leaving the malformed formula deadlocked across releases. The build action now drops every bottle block from the freshly tapped formula clone before building (building a bottle needs none); `homebrew-merge-bottles` re-adds one block inside the class afterwards. No-op for formulas with no bottle blocks. (`homebrew-build-bottles/scripts/build-bottles.sh`)

## [1.8.0] - 2026-05-25

### Added

- **`setup-node-workspace`: add optional `registry-url` input** to support npm registry authentication. When set (e.g., `https://registry.npmjs.org/`), the input is passed through to `actions/setup-node@v6`, which configures `.npmrc` with the registry and allows OIDC or static token auth. Default is empty (no registry override). (`setup-node-workspace/action.yml`)

### Fixed

- **`setup-rust`: fix "rustc is not installed for toolchain" on macOS-arm64.** When a bare toolchain channel (e.g., `1.95`) without an architecture triple is passed, the action now expands it to the runner's actual architecture-OS triple (e.g., `1.95-aarch64-apple-darwin` on macOS-arm64) before passing to `actions-rust-lang/setup-rust-toolchain@v1`. Previously, bare channels were passed as-is, which defaulted to x86_64 even on arm64 runners, causing "not installed for" failures when maturin or cargo tried to use the toolchain. (`setup-rust/action.yml`)

- `publish-zig`: the `Upload release asset` step ran `gh release upload` with no `GH_TOKEN`, so the upload failed ("set the GH_TOKEN environment variable") whenever the caller didn't set it on the step. Added a `token` input (default `${{ github.token }}`) wired into the upload and release-notes steps, so the action is self-sufficient like the sibling `upload-release-assets`/`publish-github-release` actions.

## [1.7.2] - 2026-05-25

### Fixed

- **`homebrew-merge-bottles`: strip ALL existing bottle blocks (any scope) before inserting fresh one.** Old GoReleaser-bootstrapped formulas (e.g. `xberg-io/tap/alef`) accreted `bottle do … end` blocks at file-level scope — outside the `class < Formula … end` body. `brew bottle` then failed with `undefined method 'bottle' for module Formulary::FormulaNamespace…` because the DSL call lives where no Formula receiver is bound. The merge script previously replaced only the *first* matched block (`count=1`) and required a trailing `\n` after the closing `end` (so trailing-without-newline blocks were missed). Now: regex matches `end(?:\n|\Z)` (covers trailing block without newline), and the replace step strips *every* bottle block in the file before inserting one fresh block immediately after the `license` line — guaranteed inside the class. Triple+ blank lines from the strip are collapsed. (`homebrew-merge-bottles/scripts/merge-bottles.sh`)

## [1.7.1] - 2026-05-25

### Added

- `run-test-apps`: composite action to verify a published binding by running its e2e fixture suite against the registry-installed version. Installs alef-cli, the target language toolchain, overrides the version pin in alef.toml, and invokes `alef test-apps generate` + `alef test-apps run`. Reports per-language pass/fail and uploads test-run logs as artifacts on failure.

### Fixed

- `run-test-apps`: preserve the `alef test-apps run` exit code through the `| tee` log redirect via `set -o pipefail` + `${PIPESTATUS[0]}`. Previously `tee`'s exit code (always 0) masked failing suites as passes. Also fail loudly on tomlkit install errors instead of silently degrading to an `ImportError`.
- `publish-zig`: accept enum-literal `.name` in `build.zig.zon` for Zig 0.14+ compatibility (Zig 0.14 changed the manifest schema so `.name = .foo` replaces the old `.name = "foo"` syntax).

## [1.6.12] - 2026-05-25

### Fixed

- `build-csharp-natives`, `build-java-natives`, `build-elixir-natives`: inject
  `RUSTFLAGS="-C target-feature=-crt-static"` into the Alpine Docker build for
  `*-linux-musl` targets. The default musl rust toolchain enables `+crt-static`,
  which silently drops the `cdylib` crate type with
  `warning: dropping unsupported crate type cdylib for target *-linux-musl`,
  leaving no `.so` for the staging step to find. Disabling `crt-static` restores
  cdylib output while keeping the bin/staticlib crate types working. The merged
  `env_vars` dict still wins, so callers can override.

### Removed

- `publish-swift`: remove the metadata-only Swift Package Index ping action.
  Swift packages are distributed directly from Git tags, so downstream release
  workflows should keep package build/smoke checks and drop SPI ping jobs.

## [1.6.11] - 2026-05-25

### Fixed

- `build-elixir-natives`: resolve the built NIF library's release directory from
  `cargo metadata`'s `target_directory` instead of assuming `<crate>/target`. The
  NIF crate builds into its own `target/` only when its `Cargo.toml` is a
  standalone workspace; when its path-deps (or the `rewrite-native-deps`
  prepublish step) make it a member of the parent workspace — or when
  `CARGO_TARGET_DIR`/`.cargo/config.toml` redirect it — the lib lands in the
  parent's `target/`, so the crate-relative assumption (v1.6.x) failed with
  `built NIF library not found`. Now queried from cargo, with a crate-local
  fallback when `cargo metadata` is unavailable.

## [1.6.10] - 2026-05-25

### Fixed

- `verify-package-contents`: accept a directory as `artifact-path` and iterate
  over all supported archive types inside it. Previously the script only accepted
  a single archive file; kreuzberg's publish workflow passes `dist/` directories
  containing multiple `.whl` and `.tar.gz` files, causing the script to fail with
  `Unsupported artifact extension: dist`. The script now detects whether `artifact-path`
  is a file or directory, finds all archives matching supported extensions (`.whl`,
  `.jar`, `.nupkg`, `.zip`, `.tar.gz`, `.tgz`, `.crate`, `.gem`, `.tar`) via recursive
  glob, verifies each archive, and aggregates results. Single-file callers remain
  backward compatible. Fixes v5.0.0-rc.1 publish-pypi verification blocking.
- `build-elixir-natives`: fix release directory lookup for NIF crates with
  workspace Cargo.toml. When the NIF crate declares its own `[workspace]`
  section, cargo writes the compiled library to `<crate-path>/target/<triple>/release/`
  instead of the repository root `target/<triple>/release/`. The script now
  resolves the release directory relative to `nif_crate_path` rather than the
  repository root, fixing failures on Windows (and potentially other platforms)
  when the NIF crate has its own workspace configuration.
- `build-csharp-natives`, `build-java-natives`, `build-elixir-natives`: fix
  musl linker detection in Alpine container. The `rust:1-alpine3.21` image is
  itself musl-based, so plain `gcc` produces musl-linked binaries. However,
  `rustc` was defaulting to the linker binary `musl-gcc`, which does not exist
  in the container, causing builds to fail with `error: linker \`musl-gcc\` not
  found`. Set `CARGO_TARGET_<TARGET>_LINKER=gcc` as a target-specific env var
  in the inline docker build command so rustc routes to the available linker.

## [1.6.5] - 2026-05-25

### Added

- `package-php-pie`: `dry-run` input that passes `--dry-run` through to `alef
  publish package`. In dry-run mode alef short-circuits before the
  `assert_no_member_path_deps` validation, so the binding crate's `Cargo.toml`
  does not need to be rewritten to registry version-deps (which is impossible
  before the core crate is on crates.io). The action gracefully exits without
  producing an archive when `dry-run: true`; callers must gate their downstream
  `upload-artifact` on the same dry-run flag. Closes the last chicken-and-egg
  gap in the source-build publish path: previously a dry-run that left path
  deps unrewritten (correct, since the version is not yet published) would
  fail the path-dep assertion inside `alef publish package`.

## [1.6.4] - 2026-05-24

### Fixed

- `lint-docs`: fix prek binary extraction from tarball. The `Install prek` step
  downloaded the tarball correctly but extracted it to the wrong path: the prek
  release tarball has structure `prek-<target>/prek`, but the extraction command
  was unpacking directly to `$HOME/.local/bin`, resulting in `$HOME/.local/bin/prek-<target>/prek`.
  Added `--strip-components=1` to tar so the binary lands at `$HOME/.local/bin/prek`
  as expected. Fixes CI docs runs failing with `chmod: cannot access /home/runner/.local/bin/prek`.

## [1.6.3] - 2026-05-24

### Fixed

- `lint-docs`: install `prek` (pre-commit wrapper) before running `task docs:lint:prose`, which
  internally invokes `prek run textlint`. The action previously installed Task, lychee, and
  textlint, but omitted prek, causing exit code 127 (command not found) when docs:lint:prose
  ran prek hooks on the prose linter.

## [1.6.2] - 2026-05-24

### Fixed

- `build-python-wheels`: case-insensitively compare `runner.arch` when
  deciding whether to set `CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER`.
  `runner.arch` resolves to `ARM64` (uppercase) on GitHub-hosted arm64
  runners, so the previous lowercase compare always missed and the
  linker override was never emitted into `CIBW_ENVIRONMENT`. Python
  wheel builds on `ubuntu-24.04-arm` failed inside the manylinux
  container with `error: linker \`aarch64-linux-gnu-gcc\` not found`
  because cargo defaulted to the cross-compiler binary name even on
  native arm64. The compare now lowercases the value first so the
  override fires on every arm64-on-Linux runner.

## [1.6.1] - 2026-05-24

### Fixed

- `build-csharp-natives`, `build-java-natives`, `build-elixir-natives`:
  switch musl Docker image from `alpine:3.21` to `rust:1-alpine3.21`. The
  bare alpine image lacks `rustup` and `cargo`, so the in-container
  `rustup target add ...` call returned exit code 127 and aborted every
  musl native build. `rust:1-alpine3.21` ships with the toolchain
  pre-installed; the existing `apk add` line still provides the C build
  deps the cdylib link step needs.

## [1.6.0] - 2026-05-24

### Added

- `publish-hex`: new optional input `tarball-path` accepts a pre-built Hex
  source tarball (.tar) from `build-elixir-hex@v1`, allowing publish without
  rebuilding. When set, publishes the tarball directly via `mix hex.publish
  package <tarball-path>` instead of rebuilding from source. Preserves
  dry-run and idempotency (already-published) handling.

## [1.5.1] - 2026-05-24

### Fixed

- `build-elixir-natives`: build the NIF crate named by `nif-crate-name` instead
  of the hardcoded `kreuzberg_nif`. The musl/alpine build rewrite left a literal
  `cargo build -p kreuzberg_nif` in `scripts/build.py`, so every consumer whose
  crate is not named `kreuzberg_nif` (e.g. `spikard_nif`) failed with cargo exit
  101. Added a unit test asserting the configured crate name is threaded through.

## [1.5.0] - 2026-05-24

### Removed

- `build-homebrew-bottle`: removed the synthetic single-binary bottle action.
  Use `homebrew-build-bottles` for real Homebrew bottles generated by `brew`.
- `publish-homebrew`: removed the legacy single-formula bottle updater. Use
  `publish-homebrew-source-formulas` for formula rendering and
  `homebrew-merge-bottles` for bottle DSL updates.

## [1.4.0] - 2026-05-24

### Added

- `publish-homebrew-source-formulas`: New composite action for rendering one or
  more Homebrew formulas from per-formula `.rb.tmpl` templates with `${tag}` /
  `${version}` / per-asset `${<sha_key>}` substitution, downloading release
  tarballs via `gh release download` and computing their SHA256 digests.
  Tolerant of dry-run releases: when
  `dry-run: true` and an asset is missing, it substitutes the zero-SHA
  placeholder + emits a warning so dry-run pipelines can still render and diff
  formulas before the real release exists. Replaces the per-repo
  `scripts/publish/update-homebrew-formula.sh` boilerplate (e.g.
  html-to-markdown's 184-line dual-formula updater) with a thin shared
  invocation + a JSON config + templates. Ships with a
  `test-publish-homebrew-source-formulas` integration workflow exercising the
  dry-run placeholder path end-to-end. Surfaced by html-to-markdown
  3.5.0-rc.2 publish dry-run, where the inline script failed at
  `gh release download` with "release not found" against the synthesized
  dry-run tag — blocking the entire bottle pipeline (which `needs` the
  formula update to succeed) from exercising even in dry-run mode.

## [1.3.1] - 2026-05-24

### Fixed

- `build-ruby-gem`: Added a `dry-run` input that, when `true`, skips the embedded
  `rewrite-native-deps` step — closing the last gap in the source-build action
  family (now consistent with `build-elixir-natives`, `build-elixir-hex`,
  `build-php-extension`, `build-python-sdist`). Source-build Ruby gem builds in
  publish dry-run mode now succeed without requiring the rc version to be on
  crates.io. Surfaced during the v1.4.0-rc.31 publish dry-run audit, which
  showed three call sites (Ruby native-gem, Elixir NIF, Ruby source-gem) using
  the un-gated `rewrite-native-deps` directly in liter-llm's `publish.yaml`.

## [1.3.0] - 2026-05-24

### Added

- `build-elixir-hex`: New composite action — the Hex source-package analog of
  `build-python-sdist` / `build-ruby-gem`. It rewrites the Rustler NIF crate's
  workspace path-dependencies to registry version-dependencies (via
  `rewrite-native-deps`, default-on) and then runs `mix hex.build`, so the
  published tarball compiles standalone on a consumer machine instead of failing
  on missing workspace paths. On `dry-run: true` it skips the rewrite (the rc
  version is not yet on crates.io) and falls back to `cargo generate-lockfile`
  in the NIF crate directory so the `mix.exs` `files` list still finds the
  required `<nif-crate-path>/Cargo.lock`. Replaces the hand-rolled inline
  `mix deps.get` + `mix hex.build` step across the polyglot repos and bakes in
  the dependency rewrite so it cannot be omitted. Ships with a
  `test-build-elixir-hex` integration workflow that exercises the dry-run
  lockfile fallback path end-to-end against a Rustler fixture. Surfaced by
  html-to-markdown 3.5.0-rc.2 publish dry-run, which failed in `mix hex.build`
  with `Missing files: native/html_to_markdown_nif/Cargo.lock` because the
  ungenerated lockfile (gitignored) was never produced by an inline step.

## [1.2.1] - 2026-05-24

### Fixed

- `build-php-extension`, `build-python-sdist`: Added a `dry-run` input that, when
  `true`, skips the embedded `rewrite-native-deps` step. Dry-run publish workflows
  run before the core `liter-llm` crate is on crates.io, so the rewrite's
  `--require-registry` lookup hard-failed (`failed to select a version for the
  requirement liter-llm = "^X.Y.Z-rc.N"`) and blocked the entire PHP PIE matrix
  (and would do the same for the Python sdist build) from going green in dry-run.
  Mirrors the existing `dry-run` guard on `build-elixir-natives`. Surfaced in
  liter-llm v1.4.0-rc.31 publish dry-run.

## [1.2.0] - 2026-05-24

### Added

- `build-python-sdist`: New composite action — the python-sdist analog of
  `build-ruby-gem`. It rewrites the binding crate's workspace path-dependencies to
  registry version-dependencies (via `rewrite-native-deps`, default-on) and then runs
  `maturin sdist`, so the source distribution compiles standalone on a consumer machine
  instead of failing on missing workspace paths. Supports both package-dir mode
  (`cd <package-dir> && maturin sdist`) and manifest-path mode (`maturin sdist -m
  <Cargo.toml>`), a `maturin-version` pin (default `>=1.5,<2.0`), and writes the sdist to
  a repo-relative or absolute `output-dir`. Replaces the hand-rolled inline `maturin
  sdist` step across the polyglot repos and bakes in the dependency rewrite so it cannot
  be omitted. Ships with a `test-build-python-sdist` integration workflow.

## [1.1.0] - 2026-05-24

### Added

- `rewrite-native-deps`: New composite action that rewrites a source-build language package's workspace path-dependencies to registry version-dependencies via `alef publish prepare --lang <lang> [--require-registry]`. Source-build packages (Ruby gem, Python sdist, Elixir NIF, PHP extension, Swift) ship a `Cargo.toml` whose core-crate deps point at workspace paths that no longer exist once the package is unpacked on a consumer machine — breaking `gem install`, source `pip install`, and SPM builds. The action strips those paths and pins the published version so the shipped manifest resolves. Requires alef >= 0.19.0. Inputs: `lang` (required, comma-separated), `alef-version` (default `latest`), `require-registry` (default `true`), `working-directory` (default `.`). The `lang` value is charset-validated before reaching the CLI.

### Changed

- `build-ruby-gem`, `build-php-extension`, `build-elixir-natives`: Run `rewrite-native-deps` before the native build by default, so the artifacts these actions produce resolve their core-crate dependencies from the registry rather than the workspace. New inputs `rewrite-native-deps` (default `true`) and `alef-version` (default `latest`); set `rewrite-native-deps: false` to build against the local workspace in non-release CI. The Elixir build additionally skips the rewrite on `dry-run`. Because the rewrite passes `--require-registry`, the core crates must already be published to the registry when these actions run during a release.
- Bumped dev dependencies (`uv.lock`) and pre-commit hook revisions (`xberg-io/pre-commit-hooks` v1.1.13 → v1.1.18, `ruff-pre-commit` v0.15.13 → v0.15.14).

### Fixed

- `publish-github-release`: Replaced the stale `build_create_flags` tests (the gh-CLI flag helper was removed when the action moved to the GitHub REST API) with tests that assert the `create_release()` REST payload and endpoint.
- `publish-npm`: Hoisted the `SETUP_NODE_PLACEHOLDER` sentinel to a module-level constant (ruff `N806`).
- `detect-private-key`: Excluded `CHANGELOG.md` and `publish-maven/action.yml`, whose only matches are documentation references to the `-----BEGIN PGP PRIVATE KEY BLOCK-----` armor header, not real keys.
- Applied `ruff-format` and `rumdl` formatting to previously-undrifted scripts and READMEs.

## [1.0.9] - 2026-05-24

### Fixed

- `publish-npm`: Auto-upgrade npm CLI to v11+ before publish when the host npm is older. OIDC trusted publishing requires npm v11.5.1+; Node 22 (currently the LTS default in `actions/setup-node@v6`) ships npm 10.9.x, which falls through to classic-token auth and surfaces as `ENEEDAUTH … This command requires you to be logged in` when no static `NODE_AUTH_TOKEN` is configured. The action now runs `npm install -g npm@latest` before invoking the publish script when `npm --version | cut -d. -f1 < 11`. No-op on hosts that already ship npm 11+. Surfaced in liter-llm v1.4.0-rc.30 publish runs (`Publish Node packages`, `Publish WASM package`) — the v1.0.8 placeholder-strip got us past the setup-node sentinel, only for npm 10 to refuse OIDC.

## [1.0.8] - 2026-05-24

### Fixed

- `publish-npm`: Treat `NODE_AUTH_TOKEN='XXXXX-XXXXX-XXXXX-XXXXX'` as unset for OIDC purposes. `actions/setup-node@v6` exports the literal 23-char placeholder string `XXXXX-XXXXX-XXXXX-XXXXX` as `NODE_AUTH_TOKEN` (see `authutil.ts`'s `core.exportVariable('NODE_AUTH_TOKEN', process.env.NODE_AUTH_TOKEN || 'XXXXX-XXXXX-XXXXX-XXXXX')`) whenever the caller hasn't already set the env var. The placeholder is intended as a sentinel that lets `.npmrc`'s `_authToken=${NODE_AUTH_TOKEN}` resolve to something non-empty so npm doesn't complain about a missing token at config-read time — but at publish time, npm sends that literal placeholder string to the registry as the real auth credential and the registry returns `404 Not Found` (shadowing OIDC trusted publishing). The script now treats the placeholder the same as "unset": it pops the env var, strips `_authToken=` lines from `.npmrc`, and lets npm CLI v11+ exchange the GHA OIDC token automatically. Surfaced in liter-llm v1.4.0-rc.30 publish runs (`Publish Node packages`, `Publish WASM package`) which kept 404'ing after `NODE_AUTH_TOKEN` was removed from the workflow's `env:` blocks — setup-node was still injecting the placeholder.

## [1.0.7] - 2026-05-24

### Fixed

- `publish-npm`: Strip `_authToken=` lines from EVERY candidate `.npmrc` (`$NPM_CONFIG_USERCONFIG`, `$HOME/.npmrc`, and `$PWD/.npmrc`) regardless of the value's form when `NODE_AUTH_TOKEN` is unset. The v1.0.6 fix targeted the wrong file — `actions/setup-node@v6` writes the placeholder line to `$NPM_CONFIG_USERCONFIG=/home/runner/work/_temp/.npmrc`, not `$HOME/.npmrc`. Because `Path.home() / ".npmrc"` was the only path probed when `NPM_CONFIG_USERCONFIG` happened to be unset on that environment fork, the strip silently no-op'd and the `_authToken=${NODE_AUTH_TOKEN}` placeholder line stayed in the actual `.npmrc` that `npm publish` read. The script now walks all three locations, prints which one it acted on, and additionally relaxes the matcher to strip ANY `_authToken=...` line on the empty-token path — we're committing to OIDC trusted publishing in that branch, so any leftover `_authToken` line would shadow OIDC. Adds diagnostic logging so future regressions surface without needing log forensics.

## [1.0.6] - 2026-05-24

### Fixed

- `publish-npm`: Strip `//<registry>/:_authToken=${NODE_AUTH_TOKEN}` placeholder lines from `.npmrc` (in addition to the post-expansion empty form `_authToken=`). `actions/setup-node@v6` writes the literal placeholder string `_authToken=${NODE_AUTH_TOKEN}` to `.npmrc` and defers env-var expansion to npm CLI at read time. When the caller's job doesn't set `NODE_AUTH_TOKEN` (because they're relying on OIDC trusted publishing), npm expands the placeholder to an empty token at PUT time → `404 Not Found` from the npm registry, with no fallback to OIDC. The previous `_strip_empty_npm_auth_token` only matched the post-expansion empty case (`=` then EOL); the new regex also matches the unexpanded `=${NODE_AUTH_TOKEN}` form so OIDC trusted publishing actually takes over. Surfaced in liter-llm v1.4.0-rc.30 publish run 26339094710 (`Publish Node packages` and `Publish WASM package` both 404'd after provenance signing succeeded — trusted publisher config on npmjs.org was correct, the line was just shadowing OIDC).

## [1.0.5] - 2026-05-23

### Fixed

- `publish-hex`: Treat Hex.pm's `inserted_at: can only modify a release up to one hour after publication` error as a success-equivalent skip. Hex allows in-place re-uploads only within a one-hour window after the first publish; after that, a re-run of the same version (e.g. when retrying a partial publish run that failed on a sibling registry) returns the validation error above with non-zero exit. The release is already live on hex.pm, so the action now matches this string in the same skip-grep as `already published` / `version already exists`. Surfaced in liter-llm v1.4.0-rc.30 publish run 26339094710 (`liter_llm 1.4.0-rc.30` had been on hexpm since the first publish dispatch hours earlier).

## [1.0.4] - 2026-05-23

### Fixed

- `upload-release-assets`: forward `GITHUB_TOKEN` (or `INPUT_TOKEN`) into the `gh release upload` subprocess as `GH_TOKEN` so the call authenticates. The composite step's `${{ secrets.GITHUB_TOKEN }}` was already available in `os.environ`, but `gh` only looks at `GH_TOKEN` and its keyring (which is empty on hosted runners), so the upload returned `HTTP 401: Bad credentials`. Surfaced in liter-llm v1.4.0-rc.30 publish run 26337912364 (Upload PHP extension assets job).

## [1.0.3] - 2026-05-23

### Fixed

- `wait-for-package` (pypi): try both the as-given SemVer version (`1.4.0-rc.30`) AND the PEP 440-normalized form (`1.4.0rc30`) when polling PyPI's JSON endpoint. PyPI's API only resolves the canonical PEP 440 form (`/pypi/<pkg>/1.4.0rc30/json` returns 200 while `/pypi/<pkg>/1.4.0-rc.30/json` returns 404), so callers passing the SemVer-form tag downstream saw `not found on pypi after 20 attempts` even though the package was successfully published. Surfaced in liter-llm v1.4.0-rc.30 publish run 26336349972 — `Verify install Python` job failed after 16 min of polls while `liter-llm@1.4.0rc30` had been live on PyPI the entire time. The new `_pep440_normalize` helper covers `rc/alpha/beta/a/b` prereleases and the unchanged-on-release case.

## [1.0.2] - 2026-05-23

### Fixed

- `setup-gradle`: Bump default `gradle-version` from `"8.11"` to `"8.13"`. Android Gradle Plugin 8.13.0 (consumed by alef-emitted `packages/kotlin-android/build.gradle.kts`) refuses to apply on Gradle <8.13 with `Minimum supported Gradle version is 8.13. Current version is 8.11.` Surfaced as tslp CI Mobile `kotlin-android AAR check` failures across all four ABIs after the alef 0.18.0 regen.

## [1.0.1] - 2026-05-23

### Added

- `install-alef`: Cache the installed alef binary inside the composite action via `actions/cache@v4`, keyed on host triple + resolved version. Cache hits skip the download/build entirely. For `version: main`, the cache key embeds the current `xberg-io/alef` HEAD commit's short SHA, so a new main commit invalidates the cache automatically.
- `install-alef`: New `scripts/resolve.sh` factored out of `unix.sh` — resolves `latest`/`main`/tag to a stable cache key and install ref before any download/build runs, so the cache lookup can fire before the slow path.
- `setup-php`: Add `tools` input to install global PHP tools (phpstan, psalm, composer, etc.) via shivammathur/setup-php
- `setup-maven`: Add `java-version` input (default `"21"`) to install Java via `actions/setup-java`
- `setup-gradle`: Add `java-version` input (default `"21"`) to install Java via `actions/setup-java`

### Changed

- `install-alef`: On release-binary download failure, the source-build fallback (`cargo install --git --tag v<X.Y.Z> --locked alef-cli`) now writes the produced binary into the cache, so subsequent jobs in the same workflow that share the cache key skip the cargo build entirely. Previously every job re-built from source whenever the release assets were late.
- `install-alef`: PATH wiring moved out of the platform install scripts into the composite action itself so it runs on cache hits too.

### Fixed

- `install-alef`: Source-build fallback now invokes `cargo install ... alef` (the single crate produced by alef's post-restructure workspace) instead of the removed `alef-cli` crate. Surfaced as the v0.18.0 release-publish failure when the release-binary download path missed the cache, fell through to `cargo install --git --tag v0.18.0 --locked alef-cli`, and crates.io returned `could not find 'alef-cli' in https://github.com/xberg-io/alef?branch=main with version '*'`. Updates both `scripts/unix.sh` (Linux/macOS) and `scripts/windows.ps1` to reference the current crate name.
- `publish-crates`: Increase sparse-index propagation timeouts so heavy workspace publishes (e.g. alef's 29-crate run) don't fail when crates.io's CDN lags. `INDEX_POLL_TIMEOUT_SECONDS` 300→600, `PUBLISH_RETRY_ATTEMPTS` 6→10, `PUBLISH_RETRY_DELAY_SECONDS` 30→60. Previous budget (5min wait + 6×30s retries = 8min total) was exhausted on alef v0.17.35 at slot 21/29 (`alef-backend-kotlin-android` couldn't see freshly-published `alef-backend-kotlin` in the index). New budget gives 20min total per dependent — covers observed real-world propagation tail.
- `publish-pypi`: Skip the `uv publish` invocation when the discovered version is already on the registry. The action's `scripts/publish.py` now parses the project name + version from the dist filenames (wheel-name spec + sdist tarball-name spec), queries the PyPI JSON API (`<base>/pypi/<name>/<version>/json`, auto-derived from `repository-url`), and emits `version_published=true` to `$GITHUB_OUTPUT` when the version is already present — gating both the `setup-uv` and `uv publish` steps. Previously, force-republishing a tag failed with `400 File already exists` because PyPI's API is immutable; the action now treats that as a success-equivalent skip. New output: `skipped` (true when version was already published).
- `publish-maven`: Run `actions/setup-java@v5` so the central publishing plugin can resolve credentials from `~/.m2/settings.xml`. Previously the action ran only `setup-maven`, leaving no `<server>` entry in the user's settings.xml — `mvn deploy` failed with `Unable to get publisher server properties for server id: ossrh: Cannot invoke "org.apache.maven.settings.Server.clone()" because "server" is null`. setup-java writes a `<server id="${server-id}">` block keyed on `MAVEN_USERNAME` / `MAVEN_PASSWORD` env vars (which callers already pass to the publish step), so the publishing-plugin resolves them transparently. New inputs: `setup-java` (default `true`), `java-version` (default `25`, matches the current LTS used by spikard), `java-distribution` (default `temurin`), `server-id` (default `ossrh`, matches the alef-generated `<publishingServerId>`).
- `finalize-release`: Set `GH_REPO` env var so `gh release view`/`edit` resolve the target repo without needing a local git checkout. The finalize job typically runs without `actions/checkout` (no source code needed), so previously `gh` had no git remote to auto-detect from and silently fell back to a 404 — `Release v0.15.2 not found` even though the release was visible to anyone with the URL. The retry-loop fix from the earlier patch was masking this misconfiguration; with `GH_REPO` set, the first attempt now succeeds.
- `publish-maven`, `publish-maven-gradle`: Replace the armor-header prefix grep with an unconditional try-armored-then-try-base64 import. GitHub Actions log-masks any substring that matches a registered secret, including the literal `-----BEGIN PGP PRIVATE KEY BLOCK-----` pattern in the script when the secret value begins with that header — visible in logs as `if echo "$MAVEN_GPG_PRIVATE_KEY" | head -1 | grep -q "***"`. The masking is display-only, but the prefix detection itself was also brittle to leading/trailing whitespace or CR characters. The new approach pipes the raw value to `gpg --batch --import` first, falls back to `base64 -d | gpg --batch --import`, and surfaces the actual gpg stderr in the failure message so future format mismatches are diagnosable.
- `publish-nuget`: Fix three protocol bugs in the OIDC trusted-publishing token exchange — endpoint was `/api/v2/OidcToken` (now `/api/v2/token`), audience was `nuget` (now `https://www.nuget.org`), and the OIDC token was being sent in the JSON body (now sent as `Authorization: Bearer <token>` with the request body carrying `{"username": "<nuget-user>", "tokenType": "ApiKey"}`). Matches the protocol used by the official `NuGet/login@v1` action. New required input `nuget-user` (or env `INPUT_NUGET_USER`) carries the nuget.org profile name; OIDC fails fast with a clear error if unset.
- `publish-rubygems`: Recover the rubygems push credential from `BUNDLE_GEM__PUSH_KEY` (and `RUBYGEMS_API_KEY`) when `GEM_HOST_API_KEY` is empty. `rubygems/configure-rubygems-credentials@v2` exports all three env vars, but the caller's step-level `GEM_HOST_API_KEY: ${{ secrets.RUBYGEMS_API_KEY }}` with an empty secret shadows the value, so `gem push` saw an empty key and got back `Access Denied`. The fallback uses whichever non-empty var is available and passes it explicitly to the child process.
- `publish-maven`: Import the `MAVEN_GPG_PRIVATE_KEY` into the keyring before invoking `mvn deploy`. Previously the action passed `MAVEN_GPG_PASSPHRASE` through but never imported the key, so `maven-gpg-plugin` failed with `gpg: no default secret key: No secret key` whenever the caller workflow hadn't run `setup-java@v5` with `gpg-private-key`. Accepts both armored OpenPGP and base64-encoded armored (auto-detected). Step is skipped when `MAVEN_GPG_PRIVATE_KEY` is unset, so callers that already imported via `setup-java` remain compatible.
- `publish-maven-gradle`: Accept base64-encoded GPG private keys in addition to armored PGP format — auto-detects format and decodes as needed to handle secrets stored base64-encoded to avoid newline corruption.
- `finalize-release`: Retry release lookup up to 6 times with 5s sleep between attempts to handle propagation race where release was created but API hasn't caught up yet.
- `reusable-validate-issues`: Soft-fail project-board add when token lacks org-level Projects: write scope
- `install-alef`: `resolve.sh` no longer aborts the workflow when the GitHub Commits/Releases API request fails or returns no matching JSON. The intended fallback (`resolved_version=main` / explicit error on `latest`) now runs because `set -e`/`pipefail` are scoped narrowly around the curl pipeline.
- `publish-swift`: Skip the "Verify tag is fetchable" check during dry-runs. The dry-run mode is exercised before the tag is pushed, so requiring the tag on origin always fails. The check still runs for real publishes.
- `publish-hex`: Run `mix deps.get` (and install `rebar` locally) before `mix hex.publish`. Without this, the publish step failed with `Unchecked dependencies for environment dev: ex_doc, rustler_precompiled, credo, rustler — the dependency is not available, run "mix deps.get"`.
- `publish-pypi`: Switch from `pypa/gh-action-pypi-publish@release/v1` to `uv publish --trusted-publishing automatic`. The pypa action's `create-docker-action.py` reads `GITHUB_ACTION_REPOSITORY`, which inside a composite is the composite's repo (`xberg-io/actions`), so it tries to pull `ghcr.io/xberg-io/actions:v1` and fails with `denied`. `uv publish` performs the OIDC token exchange in-process — no Docker.
- `publish-npm`: Strip empty `NODE_AUTH_TOKEN` env and `_authToken=` lines from `.npmrc` before invoking `npm publish`. When a caller writes `NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}` and the secret is undefined, the previous behavior forced classic-token auth with an empty token and 404'd at the registry PUT. With this fix, an empty token triggers npm CLI v11+ OIDC trusted publishing automatically.
- `publish-rubygems`: Invoke `rubygems/configure-rubygems-credentials@v2.0.0` when `GEM_HOST_API_KEY` is empty/unset and not in dry-run. This exchanges the GHA OIDC token for a short-lived RubyGems credential, enabling trusted publishing without a static API key. Classic API-key flow is preserved when the secret is set.

### Deprecated

### Removed

### Security
