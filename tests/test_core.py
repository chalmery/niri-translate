import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

from niri_translate import download as dl
from niri_translate.inference import LocalClient, split_text, translate
from niri_translate.storage import Cancelled, verify


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status, self.headers = status, headers or {}


class Opener:
    def __init__(self, response): self.response = response; self.request = None
    def open(self, request, timeout): self.request = request; return self.response


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'test.gguf'
        self.part = self.path.with_suffix('.gguf.part')
        self.data = b'GGUF\x00sampledata'
        self.model = dict(repo='test/model',revision='a'*40,filename='test.gguf',
                          size=len(self.data),sha256=hashlib.sha256(self.data).hexdigest())
        self.patch = patch.object(dl,'model_path',return_value=self.path);self.patch.start()
        self.cancel = threading.Event()
    def tearDown(self): self.patch.stop();self.tmp.cleanup()
    def run_download(self,response):
        return dl.download(self.model,self.cancel,lambda *_:None,Opener(response))
    def test_resume_verified_then_atomic_rename(self):
        self.part.write_bytes(self.data[:4])
        self.run_download(Response(self.data[4:],206,{'Content-Range':f'bytes 4-{len(self.data)-1}/{len(self.data)}'}))
        self.assertEqual(self.path.read_bytes(),self.data);self.assertFalse(self.part.exists())
    def test_range_ignored_restarts_not_appends(self):
        self.part.write_bytes(self.data[:4]);self.run_download(Response(self.data))
        self.assertEqual(self.path.read_bytes(),self.data)
    def test_invalid_range_never_loads(self):
        self.part.write_bytes(self.data[:4])
        with self.assertRaises(ValueError): self.run_download(Response(self.data[4:],206,{'Content-Range':'bytes 5-13/14'}))
        self.assertFalse(self.path.exists())
    def test_checksum_failure_retry_can_recover(self):
        with self.assertRaises(ValueError): self.run_download(Response(b'x'*len(self.data)))
        self.assertFalse(self.part.exists());self.assertFalse(self.path.exists())
        self.run_download(Response(self.data));self.assertTrue(self.path.exists())
    def test_cancel_keeps_partial(self):
        self.part.write_bytes(self.data[:4]);self.cancel.set()
        with self.assertRaises(Cancelled): self.run_download(Response(self.data))
        self.assertEqual(self.part.read_bytes(),self.data[:4]);self.assertFalse(self.path.exists())
    def test_truncated_download_retained_for_resume(self):
        with self.assertRaises(RuntimeError): self.run_download(Response(self.data[:4]))
        self.assertEqual(self.part.read_bytes(), self.data[:4])
        self.assertFalse(self.path.exists())
    def test_complete_part_requires_no_network(self):
        self.part.write_bytes(self.data)
        self.run_download(None);self.assertTrue(self.path.exists())


class SplitTests(unittest.TestCase):
    def test_no_loss_at_any_length(self):
        text='  First sentence. Second sentence!\n\n中文段落。第二句！\nhttps://example.com/verylongpath\n'
        for size in [1,3,12,100]:
            parts=split_text(text,lambda s:len(s)<=size)
            self.assertEqual(''.join(p.text for p in parts),text)
            self.assertTrue(all(p.literal or len(p.text)<=size for p in parts))
    def test_code_is_literal(self):
        text='Intro\n\n```python\nprint("hello")\n```\nEnd'
        parts=split_text(text,lambda s:len(s)<10)
        self.assertEqual(''.join(p.text for p in parts),text)
        self.assertTrue(next(p for p in parts if p.text.startswith('```')).literal)
    def test_oversized_sentence_split_without_truncation(self):
        parts=split_text('中'*1000,lambda s:len(s)<=64)
        self.assertEqual(len(parts),16);self.assertEqual(sum(len(p.text) for p in parts),1000)


class FakeClient:
    def __init__(self,events):self.events=events
    def check(self):pass
    def json(self,*_):return {'default_generation_settings':{'n_ctx':8192}}
    def prompt_tokens(self,text,target):return list(range(len(text)))
    def request(self,*args,**kwargs):return iter(self.events)


class StreamTests(unittest.TestCase):
    def test_limit_is_failure_partial_kept(self):
        output=[]
        with self.assertRaisesRegex(RuntimeError,'长度'):
            translate(FakeClient([{'content':'partial'},{'stop':True,'stop_type':'limit'}]),'hello','英语',output.append,lambda _:None)
        self.assertEqual(output,['partial'])
    def test_unexpected_eof_is_failure(self):
        with self.assertRaisesRegex(RuntimeError,'意外'):
            translate(FakeClient([{'content':'partial'}]),'hello','英语',lambda _:None,lambda _:None)
    def test_empty_input_makes_no_request(self):
        self.assertEqual(translate(None,'  ','英语',None,None),{'chunks':0})
    def test_paragraphs_and_code_preserved(self):
        output=[]
        translate(FakeClient([{'content':'译文'},{'stop':True,'stop_type':'eos'}]),'a\n\nb\n```\nx()\n```','英语',output.append,lambda _:None)
        self.assertEqual(''.join(output),'译文\n\n译文\n```\nx()\n```')

if __name__=='__main__':unittest.main()
