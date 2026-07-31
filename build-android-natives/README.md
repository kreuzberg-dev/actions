# build-android-natives

Cross-compile a Rust crate for Android ABIs using cargo-ndk and stage the
resulting `.so` files under the output directory, ready to be packed into
Android AAB or APK archives.

The action expects the caller to have already checked out the repo, run
`xberg-io/actions/setup-rust@v1`, and set up the Android SDK using
`android-actions/setup-android@v3`. It does not install any toolchains itself.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `crate-name` | yes | — | Cargo package name to build. |
| `lib-name` | no | `crate-name` with `-` → `_` | Base name of the produced library. |
| `abis` | no | `arm64-v8a,x86_64` | Comma-separated Android ABIs. |
| `api-level` | no | `21` | Android API level for cargo-ndk. |
| `output-dir` | no | `dist/android-natives` | Staging root directory. |
| `dry-run` | no | `false` | Skip cargo build and emit a plan only. |

## Outputs

| Name | Description |
|---|---|
| `output-dir` | Absolute path to the staging root directory. |

## Usage

```yaml
strategy:
  matrix:
    abi: [arm64-v8a, x86_64]
runs-on: ubuntu-latest
steps:
  - uses: actions/checkout@v6
  - uses: android-actions/setup-android@v3
  - uses: xberg-io/actions/setup-rust@v1
  - id: natives
    uses: xberg-io/actions/build-android-natives@v1
    with:
      crate-name: my-crate
      abis: ${{ matrix.abi }}
      api-level: "21"
  - uses: actions/upload-artifact@v7
    with:
      name: android-natives
      path: ${{ steps.natives.outputs.output-dir }}
```

## Notes

- cargo-ndk stages the crate's own cdylib at `{output-dir}/{abi}/lib{lib-name}.so`.
  After building, the action verifies `lib{lib-name}.so` exists and is non-empty for
  every ABI and fails otherwise, so `lib-name` must match the crate's `[lib]` name.
- The action requires the Android SDK to be set up via
  `android-actions/setup-android@v3` before being called.
- Supported ABIs: `arm64-v8a`, `x86_64`, `x86`, `armeabi-v7a`.
