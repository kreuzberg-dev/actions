# setup-chrome

Install a Chrome-compatible browser for headless tests across Linux
(including `ubuntu-24.04-arm`), macOS, and Windows.

- **linux-arm64**: installs the official `chromium` snap with `--classic`
  confinement, which provides a real Chromium binary that properly handles
  standard command-line arguments. The older `apt chromium` package is a
  snap stub that mangles `--` flags and is no longer used.
- **everything else**: delegates to [`browser-actions/setup-chrome`][upstream].

The action adds a `google-chrome` alias to `PATH` on every platform and exposes the installed
executable through the `chrome-path` output.

## Usage

```yaml
- uses: xberg-io/actions/setup-chrome@v1
```

With overrides:

```yaml
- uses: xberg-io/actions/setup-chrome@v1
  with:
    chrome-version: "stable"
```

## Inputs

| Name             | Required | Default  | Description                                                                                                                                |
| ---------------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `chrome-version` | no       | `stable` | Chrome channel (`stable`, `beta`, `dev`) or an explicit Chrome-for-Testing version. Ignored on linux-arm64, where the chromium snap is installed. |

## Outputs

| Name          | Description                                                   |
| ------------- | ------------------------------------------------------------- |
| `chrome-path` | Absolute path to the installed Chrome-compatible executable. |

[upstream]: https://github.com/browser-actions/setup-chrome
