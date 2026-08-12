"""Regression tests for the Homebrew bottle build action."""

import os
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "homebrew-build-bottles" / "scripts" / "build-bottles.sh"


def test_tap_clone_retries_transient_failure(tmp_path: Path) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    attempts_file = tmp_path / "tap-attempts"
    output_dir = tmp_path / "output"

    brew = binary_dir / "brew"
    brew.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --version) echo "Homebrew test" ;;
  config|update|trust|uninstall) ;;
  tap)
    attempts=$(cat "$TEST_TAP_ATTEMPTS" 2>/dev/null || echo 0)
    attempts=$((attempts + 1))
    echo "$attempts" > "$TEST_TAP_ATTEMPTS"
    [[ "$attempts" -gt 1 ]]
    ;;
  list) exit 1 ;;
  install) ;;
  bottle)
    touch "sample--${VERSION}.arm64_test.bottle.tar.gz"
    echo '{}' > "sample--${VERSION}.arm64_test.bottle.json"
    ;;
  *) echo "unexpected brew command: $*" >&2; exit 1 ;;
esac
"""
    )
    brew.chmod(0o755)

    sleep = binary_dir / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n")
    sleep.chmod(0o755)

    environment = os.environ | {
        "FORMULAS": "sample",
        "GITHUB_REPO": "example/project",
        "OUT_DIR": str(output_dir),
        "PATH": f"{binary_dir}:{os.environ['PATH']}",
        "RUNNER_OS": "macOS",
        "TAG": "v1.2.3",
        "TAP": "example/tap",
        "TEST_TAP_ATTEMPTS": str(attempts_file),
        "UPLOAD": "false",
        "VERSION": "1.2.3",
    }

    result = subprocess.run(["bash", str(_SCRIPT)], check=False, capture_output=True, text=True, env=environment)

    assert result.returncode == 0, result.stderr
    assert attempts_file.read_text().strip() == "2"
    assert (output_dir / "sample-1.2.3.arm64_test.bottle.tar.gz").is_file()
