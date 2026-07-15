#!/usr/bin/env bash
set -euo pipefail
# One-line installer for greenlint
# Usage: curl -fsSL https://raw.githubusercontent.com/fabiocicerchia/greenlint/main/install.sh | bash

if command -v pipx &>/dev/null; then
  pipx install git+https://github.com/fabiocicerchia/greenlint
else
  pip install --user git+https://github.com/fabiocicerchia/greenlint
fi
echo "greenlint installed. Run: greenlint --help"
