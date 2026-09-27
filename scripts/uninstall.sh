#!/usr/bin/env bash
set -euo pipefail
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/niri-translate"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/niri-translate"
APP_ID=io.github.chalmery.niri-translate
if [[ -x "$DATA_DIR/venv/bin/python" ]]; then
  "$DATA_DIR/venv/bin/python" - <<'PYLOCK'
import os
from pathlib import Path
from PySide6.QtCore import QLockFile
base=Path(os.environ.get('XDG_RUNTIME_DIR',f'/tmp/niri-translate-{os.getuid()}'))/'niri-translate'
lock=QLockFile(str(base/'instance.lock'));lock.setStaleLockTime(0)
if base.exists() and not lock.tryLock(0):
    raise SystemExit('请先从托盘菜单退出客户端，再卸载。')
lock.unlock()
PYLOCK
fi
rm -f "$HOME/.local/bin/niri-translate" \
  "${XDG_DATA_HOME:-$HOME/.local/share}/applications/$APP_ID.desktop" \
  "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/$APP_ID.svg" \
  "$CONFIG_DIR/autostart/$APP_ID.desktop"
rm -rf "$DATA_DIR/venv" "$DATA_DIR/runtime"
if [[ " $* " == *" --purge "* ]]; then
  rm -rf "$CONFIG_DIR/niri-translate" "$STATE_DIR"
fi
if [[ " $* " == *" --delete-models "* ]]; then
  rm -rf "$DATA_DIR/models"
fi
echo '已卸载。默认保留模型、配置和日志；--purge 删除配置和日志，--delete-models 删除下载的模型。外部本地模型从不删除。'
