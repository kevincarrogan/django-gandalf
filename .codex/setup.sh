#!/usr/bin/env bash
set -euxo pipefail

# Put user-installed tools on PATH for later agent commands.
mkdir -p "$HOME/.local/bin"
grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' "$HOME/.bashrc" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
export PATH="$HOME/.local/bin:$PATH"

# Install just.
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to "$HOME/.local/bin"

# Install project dependencies and all dependency groups from pyproject.toml / uv.lock.
uv sync --all-groups

# Install Git hooks and prefetch hook environments.
uv run pre-commit install --install-hooks
