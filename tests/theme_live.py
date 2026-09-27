"""Live light/dark rendering using isolated matugen palettes; desktop is unchanged."""
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from niri_translate.storage import DATA
ROOT=Path(__file__).resolve().parents[1]
QML=DATA/'venv/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages/niri_translate/ui/shell.qml'

def status():
    p=subprocess.run(['qs','-p',str(QML),'ipc','call','drawer','status'],capture_output=True,text=True)
    return json.loads(p.stdout) if p.returncode==0 else {}

def wait(predicate):
    end=time.monotonic()+20
    while time.monotonic()<end:
        value=status()
        if predicate(value):return value
        time.sleep(.1)
    raise TimeoutError(value)

palette=json.loads(subprocess.check_output(['matugen','--dry-run','--json','hex','color','hex','#2b5969'],text=True))['colors']
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);generated=root/'generated/clavis';generated.mkdir(parents=True)
    config=root/'config.json';config.write_text('{"theme":{"mode":"light"},"effects":{"shellBackgroundOpacity":1}}')
    colors=generated/'colors.json'
    def update(mode):
        new=generated/'next.json';new.write_text(json.dumps({k:v[mode] for k,v in palette.items()}));new.replace(colors)
    update('light')
    env=os.environ|{'CLAVIS_GENERATED_HOME':str(root/'generated'),'CLAVIS_PERSONALIZATION_CONFIG':str(config)}
    proc=subprocess.Popen([str(DATA/'venv/bin/niri-translate')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    report={}
    try:
        report['light']=wait(lambda v:v.get('visible') and v.get('ready') and not v.get('dark',True))
        connection=socket.socket(socket.AF_UNIX)
        connection.connect(str(Path(os.environ['XDG_RUNTIME_DIR'])/'niri-translate/instance.sock'))
        connection.sendall(('\n'.join(json.dumps(request) for request in [dict(cmd='direction',value=0),dict(cmd='source',value='This application translates text locally. No translation is sent to a cloud service.'),dict(cmd='translate')])+'\n').encode())
        connection.settimeout(30)
        for line in connection.makefile():
            state=json.loads(line)
            if state['status'].startswith('完成') and state['output']:break
        connection.close()
        time.sleep(.4)
        subprocess.run(['qs','-p',str(QML),'ipc','call','drawer','capture',str(ROOT/'docs/theme-light.png')],check=True)
        time.sleep(.4)
        update('dark')
        report['dark']=wait(lambda v:v.get('dark'))
        time.sleep(.4)
        subprocess.run(['qs','-p',str(QML),'ipc','call','drawer','capture',str(ROOT/'docs/theme-dark.png')],check=True)
        time.sleep(.4)
        update('light')
        report['light_again']=wait(lambda v:v.get('connected') and not v.get('dark',True))
        report['desktop_theme_changed']=False
    finally:
        proc.terminate();proc.wait(timeout=20)
    (ROOT/'docs/theme-test.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
