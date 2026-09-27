from pathlib import Path
import os
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from niri_translate.storage import APP_ID, ROOT, DATA
from niri_translate.desktop import desktop_quote

share = Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')
bin_dir = Path.home()/'.local/bin'
bin_dir.mkdir(parents=True, exist_ok=True)
launcher = bin_dir/'niri-translate'
if launcher.exists() and not launcher.is_symlink():
    shutil.copy2(launcher, launcher.with_suffix('.backup'))
launcher.unlink(missing_ok=True)
launcher.symlink_to(DATA/'venv/bin/niri-translate')
apps = share/'applications'; apps.mkdir(parents=True,exist_ok=True)
(apps/f'{APP_ID}.desktop').write_text('[Desktop Entry]\nVersion=1.0\nType=Application\n'
    'Name=Niri Translate\nName[zh_CN]=Niri 本地翻译\nComment=Offline Chinese-English translation\n'
    f'Exec={desktop_quote(launcher)}\nIcon={APP_ID}\nTerminal=false\n'
    'Categories=Utility;\nKeywords=translate;translation;翻译;\nStartupNotify=true\n')
icons=share/'icons/hicolor/scalable/apps';icons.mkdir(parents=True,exist_ok=True)
shutil.copy2(ROOT/'assets'/f'{APP_ID}.svg',icons/f'{APP_ID}.svg')
print('桌面入口：',apps/f'{APP_ID}.desktop')
