#!/usr/bin/env bash
set -euo pipefail
exec "${XDG_DATA_HOME:-$HOME/.local/share}/niri-translate/venv/bin/niri-translate" "$@"
