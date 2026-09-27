import os
from pathlib import Path
import sys
from .storage import APP_ID


def autostart_path():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / f"{APP_ID}.desktop"


def desktop_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'


def set_autostart(enabled):
    path = autostart_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        executable = Path(sys.executable).parent / "niri-translate"
        if not executable.exists():
            raise ValueError("请先安装客户端，再启用登录自启")
        path.write_text('[Desktop Entry]\nType=Application\nName=Niri Translate\n'
                        f'Exec={desktop_quote(executable)} --background\nIcon={APP_ID}\n'
                        'Terminal=false\nX-GNOME-Autostart-enabled=true\n')
    else:
        path.unlink(missing_ok=True)
