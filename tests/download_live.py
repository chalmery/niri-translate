"""Verify cancellation/resume against the real pinned HF URL, fetching the tail only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from niri_translate import download as dl
from niri_translate.storage import MODELS,Cancelled,model_path
root=Path(__file__).resolve().parents[1]
model=MODELS[0];original=model_path(model)
report={}
with tempfile.TemporaryDirectory(dir=root/'.build',prefix='download-check-') as directory:
    target=Path(directory)/model['filename'];part=target.with_suffix('.gguf.part')
    subprocess.run(['cp','--reflink=auto',str(original),str(part)],check=True)
    offset=model['size']-1024*1024
    with part.open('r+b') as stream:stream.truncate(offset)
    cancel=threading.Event()
    def progress(done,total):
        if done>=offset+256*1024:cancel.set()
    with patch.object(dl,'model_path',return_value=target):
        try:dl.download(model,cancel,progress)
        except Cancelled:report['cancelled']=True
        else:raise AssertionError('expected cancellation')
        report['partial_bytes_after_cancel']=part.stat().st_size
        assert not target.exists()
        report['unfinished_not_loadable']=True
        dl.download(model,threading.Event(),lambda *_:None)
        report['resumed_and_sha256_verified']=target.stat().st_size==model['size'] and not part.exists()
(root/'docs/download-test.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
