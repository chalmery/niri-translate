"""Read Clavis' generated Material palette; never modify desktop theme settings."""
import json
import os
from pathlib import Path
import re
from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPalette

LIGHT = dict(background='#f5fafd', on_background='#171c1f', on_surface='#171c1f',
             on_surface_variant='#40484c', surface_container_low='#f0f4f7',
             surface_container='#eaeff2', outline_variant='#bfc8cc', primary='#08677f',
             on_primary='#ffffff', primary_container='#b8eaff', on_primary_container='#001f28', error='#ba1a1a')
DARK = dict(background='#0f1416', on_background='#dee3e6', on_surface='#dee3e6',
            on_surface_variant='#bfc8cc', surface_container_low='#171c1f',
            surface_container='#1b2023', outline_variant='#40484c', primary='#88d0ec',
            on_primary='#003544', primary_container='#004d61', on_primary_container='#b8eaff', error='#ffb4ab')


def rgb(color): return tuple(int(color[i:i+2],16) for i in (1,3,5))

def mix(a,b,weight):
    return '#' + ''.join(f'{round(x*weight+y*(1-weight)):02x}' for x,y in zip(rgb(a),rgb(b)))


def map_palette(palette, fallback_dark=False):
    valid={key:value for key,value in palette.items() if isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value)}
    background=valid.get('background',(DARK if fallback_dark else LIGHT)['background'])
    red,green,blue=rgb(background)
    dark=(.2126*red+.7152*green+.0722*blue)<128
    colors=(DARK if dark else LIGHT)|valid
    # Match Clavis Appearance.colLayer0Base and colLayer0Border.
    surface=mix(colors['background'],colors['primary'],.99)
    return dict(dark=dark,surface=surface,card=colors['surface_container_low'],
                ink=colors['on_surface'],muted=colors['on_surface_variant'],
                accent=colors['primary'],on_accent=colors['on_primary'],
                border=mix(colors['outline_variant'],surface,.4),
                line=colors['outline_variant'],footer=colors['primary_container'],
                footer_text=colors['on_primary_container'],error=colors['error'])


def paths():
    home=Path.home()
    config=Path(os.environ.get('XDG_CONFIG_HOME') or home/'.config')
    data=Path(os.environ.get('XDG_DATA_HOME') or home/'.local/share')
    config_home=Path(os.environ.get('CLAVIS_CONFIG_HOME') or config/'clavis')
    data_home=Path(os.environ.get('CLAVIS_DATA_HOME') or data/'clavis')
    profile=os.environ.get('CLAVIS_PROFILE','default')
    if profile in ('.','..') or '/' in profile or '\\' in profile: profile='default'
    profile_home=Path(os.environ.get('CLAVIS_PROFILE_HOME') or data_home/'profiles'/profile)
    generated=Path(os.environ.get('CLAVIS_GENERATED_HOME') or profile_home/'generated')
    return (Path(os.environ.get('CLAVIS_PERSONALIZATION_CONFIG') or config_home/'config.json'),
            generated/'clavis/colors.json')


class ThemeWatcher(QObject):
    updated=Signal(object)
    def __init__(self,parent=None,files=None):
        super().__init__(parent)
        self.config_path,self.colors_path=files or paths()
        self.current={}
        self.watcher=QFileSystemWatcher(self)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(100)
        self.timer.timeout.connect(self.reload)
        self.watcher.fileChanged.connect(lambda _:self.timer.start())
        self.watcher.directoryChanged.connect(lambda _:self.timer.start())
        self.poll=QTimer(self);self.poll.setInterval(3000)
        self.poll.timeout.connect(self.reload);self.poll.start()
        self.reload()

    def reload(self):
        # Watch files AND parents to survive atomic rename/replacement by matugen.
        wanted=set()
        for path in (self.config_path,self.colors_path):
            if path.exists():wanted.add(str(path))
            if path.parent.exists():wanted.add(str(path.parent))
        existing=set(self.watcher.files()+self.watcher.directories())
        if wanted-existing:self.watcher.addPaths(list(wanted-existing))
        try: config=json.loads(self.config_path.read_text())
        except (OSError,ValueError): config={}
        try: palette=json.loads(self.colors_path.read_text())
        except (OSError,ValueError):
            if self.current:return  # Keep last valid theme during a partial write.
            palette={}
        if not isinstance(palette,dict):return
        if not isinstance(config,dict): config={}
        prefs=config.get('theme',{})
        mode=prefs.get('mode') if isinstance(prefs,dict) else None
        if mode not in ('dark','light'):
            color=QGuiApplication.palette().color(QPalette.ColorRole.Window)
            mode='dark' if color.lightness()<128 else 'light'
        value=map_palette(palette,mode=='dark')
        value['source']='Clavis' if palette else 'system fallback'
        try: value['opacity']=max(0.0,min(1.0,float(config.get('effects',{}).get('shellBackgroundOpacity',1))))
        except (AttributeError,ValueError,TypeError): value['opacity']=1.0
        if value!=self.current:
            self.current=value
            self.updated.emit(value)
