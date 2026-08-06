# setup-c-cpp-tools

Install the C/C++ toolchain used by the xberg-io pre-commit hooks.

Installs `cppcheck`, `clang-format`, and `shellcheck`. `cppcheck` is pinned to
the version expected by `xberg-io/pre-commit-hooks` (currently `2.20.0`);
because Ubuntu's stock package is behind, it is built from source via CMake
when not already present at the expected version. On macOS, all three tools
come from Homebrew.

Windows is not supported (the upstream pre-commit hooks pin Linux/macOS
toolchains only).

## Usage

```yaml
- uses: xberg-io/actions/setup-c-cpp-tools@v1
```

With overrides:

```yaml
- uses: xberg-io/actions/setup-c-cpp-tools@v1
  with:
    cppcheck-version: "2.20.0"
    install-clang-format: "true"
    install-cppcheck: "true"
    install-shellcheck: "true"
```

clang-format only — the shape jobs that just need `poly fmt` should use, since a cppcheck version
miss builds it from source on Linux:

```yaml
- uses: xberg-io/actions/setup-c-cpp-tools@v1
  with:
    install-cppcheck: "false"
    install-shellcheck: "false"
```

## Inputs

| Name                   | Required | Default   | Description                                                                                    |
| ---------------------- | -------- | --------- | ---------------------------------------------------------------------------------------------- |
| `cppcheck-version`     | no       | `2.20.0`  | cppcheck version to install. Must match the pin in `xberg-io/pre-commit-hooks`.           |
| `install-clang-format` | no       | `true`    | Install clang-format. Set to `false` to skip.                                                  |
| `install-cppcheck`     | no       | `true`    | Install cppcheck. Set to `false` to skip.                                                      |
| `install-shellcheck`   | no       | `true`    | Install shellcheck. Set to `false` to skip.                                                    |
