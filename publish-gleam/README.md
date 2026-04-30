# publish-gleam

Publish Gleam packages to [Hex.pm](https://hex.pm) via `gleam publish`.

Gleam packages share the Hex.pm registry with Elixir packages, but use a
separate publish tool. This action wraps `gleam publish --yes [--replace]`
with the same idempotency guarantees as the sibling `publish-hex` action.

## Authentication

Set `HEX_API_KEY` in the calling workflow's environment. The action checks
its presence before publishing and fails fast if missing.

```yaml
- uses: kreuzberg-dev/actions/publish-gleam@v1
  env:
    HEX_API_KEY: ${{ secrets.HEX_API_KEY }}
  with:
    package-dir: packages/gleam
```

You can use the same key as `publish-hex` (Elixir) — they hit the same Hex
tenant.

## Usage

```yaml
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: kreuzberg-dev/actions/publish-gleam@v1
        env:
          HEX_API_KEY: ${{ secrets.HEX_API_KEY }}
        with:
          package-dir: packages/gleam
```

### Dry run

```yaml
- uses: kreuzberg-dev/actions/publish-gleam@v1
  with:
    package-dir: packages/gleam
    dry-run: 'true'
```

### Skip BEAM setup if already installed

```yaml
- uses: erlef/setup-beam@v1
  with:
    otp-version: '27'
    gleam-version: '1.6'
- uses: kreuzberg-dev/actions/publish-gleam@v1
  env:
    HEX_API_KEY: ${{ secrets.HEX_API_KEY }}
  with:
    package-dir: packages/gleam
    setup-beam: 'false'
```

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `package-dir` | no | `.` | Directory containing `gleam.toml`. |
| `setup-beam` | no | `true` | Whether to install Erlang/OTP + Gleam via `erlef/setup-beam@v1`. |
| `otp-version` | no | `27` | Erlang/OTP version. |
| `gleam-version` | no | `1.6` | Gleam version. |
| `replace` | no | `true` | Pass `--replace` to allow replacing an existing version. |
| `dry-run` | no | `false` | Skip the actual publish; print what would happen. |

## Outputs

| Name | Description |
|---|---|
| `skipped` | `true` when the version was already published (idempotency). |
