"""Real model acceptance probe; synthetic test text only, never user history."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from niri_translate.inference import LocalClient, translate

binary = sys.argv[1]
model = sys.argv[2]
out = Path(sys.argv[3])
port = 18769
start = time.monotonic()
log = open('/tmp/niri-probe-server.log', 'w')
process = subprocess.Popen([binary, '-m', model, '--host', '127.0.0.1', '--port', str(port),
                            '-ngl', '0', '-t', '8', '-c', '8192', '-np', '1', '--jinja',
                            '--no-context-shift', '--no-webui', '--offline', '--api-key', 'probe-local'],
                           stdout=log, stderr=log)
report = {"model": Path(model).name, "runtime_commit": "d2e54583c7452353eb35d40431281f6ee984332f", "threads": 8, "context": 8192, "samples": []}
try:
    client = LocalClient(port, 'probe-local')
    while time.monotonic() - start < 180:
        if process.poll() is not None:
            raise RuntimeError('llama-server exited; inspect /tmp/niri-probe-server.log')
        try:
            client.json('/health')
            break
        except Exception:
            time.sleep(.2)
    else:
        raise TimeoutError('model loading exceeded 180 s')
    report['load_s'] = time.monotonic() - start
    samples = [
        ('short-en', '简体中文', 'Please close the window before leaving the room.'),
        ('short-zh', '英语', '你好，我想把会议改到明天下午三点。'),
        ('email', '英语', '王经理您好：\n\n附件是本周的项目进度报告。由于测试环境暂时不可用，发布计划将顺延至下周二。请您在周五前确认是否需要调整。\n\n谢谢！'),
        ('technical', '简体中文', 'The client sends requests to 127.0.0.1. Network operations run on a worker thread so the GUI remains responsive. If the server returns HTTP 503, wait until model loading finishes and retry.'),
        ('format', '简体中文', 'Deployment checklist:\n\n1. Open https://example.com/api and keep ${TOKEN} unchanged.\n2. Set timeout_ms = 3000; retry at most 3 times.\n\n```python\nprint("hello")\n```'),
    ]
    for label,target,text in samples:
        output=[]; t0=time.monotonic(); first=[]
        def emit(chunk):
            if not first: first.append(time.monotonic()-t0)
            output.append(chunk)
        timings=translate(client,text,target,emit,lambda s:None)
        report['samples'].append(dict(label=label,source=text,target=target,chars=len(text),output=''.join(output),total_s=time.monotonic()-t0,first_output_s=first[0] if first else None,**timings))
        print(json.dumps(report['samples'][-1],ensure_ascii=False),flush=True)
    report['memory'] = [line.strip() for line in Path(f'/proc/{process.pid}/status').read_text().splitlines() if line.startswith(('VmRSS:', 'VmHWM:'))]
    report['props'] = {k:v for k,v in client.json('/props').items() if k in ('model_alias','model_path','chat_template')}
finally:
    process.terminate()
    try: process.wait(timeout=10)
    except subprocess.TimeoutExpired: process.kill();process.wait()
    log.close()
    report['exit_code']=process.returncode
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('REPORT',out,flush=True)
