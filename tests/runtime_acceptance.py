"""Real runtime checks, also runnable inside a loopback-only network namespace."""
import json
from pathlib import Path
import subprocess
import socket
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from niri_translate.inference import LocalClient,split_text,translate
from niri_translate.storage import DATA
report={}
process=subprocess.Popen([str(DATA/'runtime/bin/llama-server'),'-m',str(DATA/'models/Hy-MT2-1.8B-Q4_K_M.gguf'),
    '--host','127.0.0.1','--port','18769','-ngl','0','-t','8','-c','8192','-np','1','--jinja',
    '--no-webui','--offline','--no-context-shift','--log-disable','--api-key','runtime-test'],
    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    client=LocalClient(18769,'runtime-test');start=time.monotonic()
    while time.monotonic()-start<60:
        if process.poll() is not None:raise RuntimeError('runtime failed to start')
        try:client.json('/health');break
        except Exception:time.sleep(.1)
    else:raise TimeoutError('runtime load timeout')
    report['load_s']=time.monotonic()-start
    text='这是一段用于测试超长输入的文本。请保留句子顺序、数字 123 和所有信息。'*800
    cache={}
    def count(s):
        if s not in cache:cache[s]=len(client.prompt_tokens(s,'英语'))
        return cache[s]
    pieces=split_text(text,lambda s:count(s)<=4064)
    assert ''.join(p.text for p in pieces)==text
    assert all(p.literal or count(p.text)<=4064 for p in pieces)
    report['long_input']={'chars':len(text),'input_tokens':count(text),
                         'chunks':len(pieces),'largest_prompt_tokens':max(count(p.text) for p in pieces if not p.literal),'no_content_lost':True}
    events=list(client.request('/completion',{'prompt':client.prompt_tokens('请把这段话翻译成完整的英语。','英语'),'n_predict':1,'stream':True},stream=True))
    assert events[-1]['stop_type']=='limit'
    report['real_output_limit_reported']=True
    out=[]
    translate(client,'模型下载完成后，即使没有互联网连接也能进行本地翻译。','英语',out.append,lambda _:None)
    report['translation']=''.join(out)
    assert 'translat' in report['translation'].lower()
    report['network_interfaces']=sorted(name for _,name in socket.if_nameindex())
    report['offline_loopback_only']=report['network_interfaces']==['lo']
finally:
    process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    report['server_reaped']=not Path(f'/proc/{process.pid}').exists()
Path(sys.argv[1]).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
