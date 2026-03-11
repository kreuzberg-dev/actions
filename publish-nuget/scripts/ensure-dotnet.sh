#!/usr/bin/env bash
set -euo pipefail

if command -v dotnet >/dev/null 2>&1; then
  echo "dotnet already available: $(dotnet --version)"
  exit 0
fi

echo "Installing .NET SDK..."
curl -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh
chmod +x /tmp/dotnet-install.sh
/tmp/dotnet-install.sh --channel LTS
rm -f /tmp/dotnet-install.sh

export PATH="$HOME/.dotnet:$PATH"
if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$HOME/.dotnet" >>"$GITHUB_PATH"
fi

echo "Installed dotnet: $(dotnet --version)"
