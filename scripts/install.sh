#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/niri-translate"
command -v qs >/dev/null || { echo "请先安装 Quickshell（验证版本 0.3.1）"; exit 1; }
mkdir -p "$DATA_DIR"
command -v uv >/dev/null || { echo '请先安装 uv（Fedora: sudo dnf install uv）'; exit 1; }
uv venv --python python3 "$DATA_DIR/venv" --allow-existing
uv pip install --python "$DATA_DIR/venv/bin/python" --require-hashes -r "$ROOT/requirements.lock"
uv pip install --python "$DATA_DIR/venv/bin/python" --no-deps --no-build-isolation "$ROOT"
if [[ ! -x "$DATA_DIR/runtime/bin/llama-server" ]] || ! cmp -s "$ROOT/runtime.lock.json" "$DATA_DIR/runtime/runtime.lock.json"; then
  "$ROOT/scripts/build-runtime.sh"
fi
"$DATA_DIR/venv/bin/python" "$ROOT/scripts/install-desktop.py"
echo '安装完成。应用菜单搜索 Niri Translate；登录自启默认关闭。'
echo '启动：~/.local/bin/niri-translate'
