# publish-pub

Publish Dart packages to [pub.dev](https://pub.dev) using OIDC trusted publishing.

## One-time setup per package

1. Publish version `0.0.1` (or any initial version) manually once to claim the
   package name on pub.dev.
2. Visit `https://pub.dev/packages/<your-package>/admin` and enable
   **Automated publishing** for your GitHub repository, with tag pattern
   `v{{version}}` (or whichever your repo uses).
3. Ensure your publish workflow has `permissions: id-token: write` so the
   action can mint the OIDC token pub.dev expects.

No long-lived secret is needed — pub.dev validates the OIDC token at publish
time against the configured GitHub repo and tag pattern.

## Usage

```yaml
jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: kreuzberg-dev/actions/publish-pub@v1
        with:
          package-dir: packages/dart
```

### Dry run

```yaml
- uses: kreuzberg-dev/actions/publish-pub@v1
  with:
    package-dir: packages/dart
    dry-run: 'true'
```

### Skip Dart setup if already installed

```yaml
- uses: dart-lang/setup-dart@v1
  with:
    sdk: '3.5.0'
- uses: kreuzberg-dev/actions/publish-pub@v1
  with:
    package-dir: packages/dart
    setup-dart: 'false'
```

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `package-dir` | no | `.` | Directory containing `pubspec.yaml`. |
| `dart-version` | no | `stable` | Dart SDK version (passed to `dart-lang/setup-dart`). |
| `setup-dart` | no | `true` | Whether to invoke `dart-lang/setup-dart`. Set to `false` when Dart is already installed. |
| `dry-run` | no | `false` | Skip the actual publish; only run validation. |

## Outputs

| Name | Description |
|---|---|
| `skipped` | `true` when the version was already published (idempotency). |

## Idempotency

If the version is already published, the action exits 0 with `skipped=true`
instead of failing. This makes it safe to re-run a release workflow on a tag
that's already partially published.
