#!/usr/bin/env bash
set -euo pipefail

echo "=== Initial disk usage ==="
df -h /

echo "=== Removing unnecessary packages ==="
# ~keep /usr/local/lib/node_modules is deliberately NOT removed. That directory holds npm's own
# implementation, and /usr/local/bin/npm is only a symlink into it, so deleting it leaves a
# dangling symlink rather than a clean absence: `npm` stays on PATH and every invocation fails
# with ENOENT. That broke pnpm/action-setup in any job running this action first, and it presents
# far from its cause -- xberg-enterprise's backend spec-drift check was red for days on
# "spawn npm ENOENT" while the drift it was meant to catch went unchecked. It is also a poor
# trade: this path is a few hundred MB against the ~20 GB the entries below reclaim.
sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc /opt/hostedtoolcache/CodeQL || true
sudo rm -rf /usr/local/share/boost /opt/microsoft /usr/local/.ghcup || true

echo "=== Removing large apt packages ==="
sudo apt-get remove --yes -o APT::AutoRemove::SuggestsImportant=false \
	'^ghc-' 'php.*' 'powershell' 'azure-cli' 'google-cloud-sdk' 2>/dev/null || true

echo "=== Cleaning apt cache ==="
sudo apt-get autoremove --yes || true
sudo apt-get clean || true
sudo rm -rf /var/lib/apt/lists/* || true

echo "=== Cleaning Docker ==="
docker system prune -af --volumes || true
docker builder prune -af || true

echo "=== Cleaning journalctl logs ==="
sudo journalctl --vacuum-size=50M || true

echo "=== Cleaning Python caches ==="
sudo rm -rf ~/.cache/pip /tmp/pip-* /tmp/tmp* || true
sudo rm -rf /opt/pipx_bin /opt/pipx || true

echo "=== Cleaning Rust artifacts ==="
sudo rm -rf ~/.cargo/registry/cache ~/.cargo/git/db || true

echo "=== Disk usage after cleanup ==="
df -h /
