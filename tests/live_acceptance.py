"""Exercise installed tray, QML drawer and real inference via their public protocols.

Run in an otherwise idle app: this uses synthetic text and exits the test instance.
It does not claim physical pointer/keyboard or logout/login verification.
"""
import json
import os
from pathlib import Path
import select
import shlex
import signal
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from niri_translate.storage import ROOT as PACKAGE, APP_ID, DATA
SOCK=Path(os.environ['XDG_RUNTIME_DIR'])/'niri-translate/instance.sock'
QML=DATA/'venv/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages/niri_translate/ui/shell.qml'
results={}
def run(*args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT).strip()
def check(name,value):
    assert value,name
    results[name]=True
    print(name,flush=True)

def pid():return int(SOCK.with_name('instance.lock').read_text().splitlines()[0])
def children(parent):
    p=Path(f'/proc/{parent}/task/{parent}/children')
    return [int(s) for s in p.read_text().split()] if p.exists() else []
def process_name(pid):
    try:return Path(f'/proc/{pid}/comm').read_text().strip()
    except FileNotFoundError:return ''

class Client:
    def __init__(self):
        self.sock=socket.socket(socket.AF_UNIX);self.sock.connect(str(SOCK));self.buffer=b'';self.state={}
        self.wait(lambda s:bool(s))
    def send(self,cmd,value=None):self.sock.sendall((json.dumps(dict(cmd=cmd,value=value))+'\n').encode())
    def wait(self,predicate,timeout=40):
        if predicate(self.state): return self.state
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            while b'\n' in self.buffer:
                line,self.buffer=self.buffer.split(b'\n',1);self.state=json.loads(line)
                if predicate(self.state):return self.state
            ready,_,_=select.select([self.sock],[],[],.2)
            if ready:
                chunk=self.sock.recv(2**20)
                if not chunk:raise EOFError()
                self.buffer+=chunk
        raise TimeoutError(str({k:v for k,v in self.state.items() if k not in ('source','output')}))
    def close(self):self.sock.close()

def drawer(method,*args):return run('qs','-p',str(QML),'ipc','call','drawer',method,*args)
def pause_ui():time.sleep(.35)

# The desktop launcher returns before the child; keep this test process alive.
launch=subprocess.run(['gio','launch',str(Path.home()/'.local/share/applications'/f'{APP_ID}.desktop')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,text=True)
results['desktop_launcher_exit']=launch.returncode
end=time.monotonic()+15
while not SOCK.exists() and time.monotonic()<end:time.sleep(.1)
c=Client()
backend=pid()
retain_before=c.state.get('retain_on_hide', False)
try:
    check('desktop_entry_starts_app',launch.returncode==0 and backend>0)
    c.wait(lambda s:s['ready'])
    pause_ui();ui=json.loads(drawer('status'))
    check('drawer_connected_and_visible',ui['connected'] and ui['open'] and ui['visible'])
    windows=json.loads(run('niri','msg','-j','windows'))
    check('no_regular_niri_window',not any(w.get('app_id')==APP_ID for w in windows))
    # Locate the standard SNI registered by this backend.
    items=shlex.split(run('busctl','--user','get-property','org.kde.StatusNotifierWatcher','/StatusNotifierWatcher','org.kde.StatusNotifierWatcher','RegisteredStatusNotifierItems'))[2:]
    service=None
    for item in items:
        bus,path=item.split('/',1)
        try:title=run('busctl','--user','get-property',bus,'/'+path,'org.kde.StatusNotifierItem','Title')
        except subprocess.CalledProcessError:continue
        if 'niri-translate' in title:service=bus;break
    check('tray_registered_in_actual_host',service is not None)
    c.send('settings',True);c.wait(lambda s:s['settings'])
    c.send('hide');c.wait(lambda s:not s['open']);pause_ui()
    check('drawer_really_unmapped',not json.loads(drawer('status'))['visible'])
    run('busctl','--user','call',service,'/StatusNotifierItem','org.kde.StatusNotifierItem','Activate','ii','0','0')
    c.wait(lambda s:s['open']);pause_ui()
    reopened=json.loads(drawer('status'))
    check('tray_activate_opens_drawer',reopened['visible'])
    check('reopen_always_returns_to_translation',not reopened['settings'])
    before=children(backend)
    run(str(Path.home()/'.local/bin/niri-translate'))
    check('single_instance_same_pid',pid()==backend)
    check('single_instance_same_children',children(backend)==before)
    c.send('settings',False);c.send('direction',0)
    c.send('source','This application translates text locally. No translation is sent to a cloud service.')
    c.send('translate');c.wait(lambda s:s['status'].startswith('完成') and bool(s['output']))
    translation=c.state['output'];source=c.state['source']
    check('en_to_zh_real_model',any('\u4e00'<=ch<='\u9fff' for ch in translation))
    pause_ui();drawer('capture',str(ROOT/'docs/screenshot.png'));pause_ui()
    c.send('retain_on_hide',True);c.wait(lambda s:s['retain_on_hide'])
    c.send('hide');c.wait(lambda s:not s['open']);c.send('show');c.wait(lambda s:s['open'])
    check('hide_preserves_texts_when_enabled',c.state['source']==source and c.state['output']==translation)
    c.send('retain_on_hide',False);c.wait(lambda s:not s['retain_on_hide'])
    c.send('hide');c.wait(lambda s:not s['open']);c.send('show');c.wait(lambda s:s['open'])
    check('hide_clears_texts_when_disabled',not c.state['source'] and not c.state['output'] and not c.state['translating'])
    pause_ui();ui=json.loads(drawer('status'))
    check('drawer_text_panes_are_empty',ui['sourceLength']==0 and ui['outputLength']==0)
    c.send('direction',1);c.send('source','请在明天下午三点之前发送测试报告。');c.send('translate')
    c.wait(lambda s:s['status'].startswith('完成') and s['source'].startswith('请'))
    check('zh_to_en_real_model','report' in c.state['output'].lower())
    c.send('source','这是一个用来测试停止功能的较长段落，请保留所有信息并逐句翻译。'*100);c.send('translate')
    c.wait(lambda s:s['translating'] and len(s['output'])>5,timeout=90)
    c.send('stop');c.wait(lambda s:s['status'].startswith('已停止'));partial=c.state['output']
    c.send('show');c.wait(lambda s:s['open'])
    check('cancel_retains_output',c.state['output']==partial)
    c.send('source','这句话仅用于测试旧请求的输出不能覆盖新请求。'*20);c.send('translate')
    c.send('source','你好。');c.send('translate')
    c.wait(lambda s:s['status'].startswith('完成') and s['source']=='你好。')
    check('old_request_isolation',len(c.state['output'])<80)
    server=next(p for p in children(backend) if process_name(p)=='llama-server')
    c.send('model',1);c.wait(lambda s:s['model']==1 and not s['ready'])
    time.sleep(.5)
    check('switch_stops_previous_model',not Path(f'/proc/{server}').exists())
    check('uninstalled_model_not_auto_downloaded',not (DATA/'models/Hy-MT2-1.8B-Q8_0.gguf.part').exists())
    c.send('model',0);c.wait(lambda s:s['model']==0 and s['ready'])
    server=next(p for p in children(backend) if process_name(p)=='llama-server')
    os.kill(server,signal.SIGKILL);c.wait(lambda s:not s['ready'])
    check('inference_failure_keeps_source',c.state['source']=='你好。')
    c.send('load');c.wait(lambda s:s['ready'])
    check('inference_failure_reload_recovers',True)
    c.send('width',760);c.wait(lambda s:s['width']==760);pause_ui()
    check('drawer_width_changes',json.loads(drawer('status'))['width']==760)
    c.send('width',820)
    c.send('autostart',True);c.wait(lambda s:s['autostart'])
    auto=Path.home()/'.config/autostart'/f'{APP_ID}.desktop'
    check('autostart_enabled_with_background',auto.exists() and '--background' in auto.read_text())
    run('systemctl','--user','daemon-reload')
    generated=run('systemctl','--user','list-unit-files','--no-pager','*niri*')
    results['generated_autostart_unit_listing']='\n'.join(line for line in generated.splitlines() if 'translate@autostart' in line)
    check('session_generator_sees_autostart','autostart.service' in generated)
    c.send('autostart',False);c.wait(lambda s:not s['autostart'])
    check('autostart_disabled_by_default_after_test',not auto.exists())
    run('systemctl','--user','daemon-reload')
    c.send('settings',True);c.wait(lambda s:s['settings']);pause_ui();drawer('capture',str(ROOT/'docs/settings.png'));pause_ui()
finally:
    owned=children(backend)
    try:
        c.send('retain_on_hide',retain_before)
        c.send('quit')
    except OSError:pass
    c.close()
    end=time.monotonic()+20
    while Path(f'/proc/{backend}').exists() and time.monotonic()<end:time.sleep(.1)
    results['quit_reaps_all_owned_children']=all(not Path(f'/proc/{p}').exists() for p in owned)
    (ROOT/'docs/desktop-test.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(results,ensure_ascii=False,indent=2))
