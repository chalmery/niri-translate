"""Explicit downloads only; partial files are never loadable."""
import re
import urllib.error
import urllib.request
from .storage import Cancelled, model_path, verify


def download(model, cancel, progress, opener=None, *, target=None):
    # Capture the destination before the worker starts; never change it mid-download.
    target = model_path(model) if target is None else target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".gguf.part")
    url = f'https://huggingface.co/{model["repo"]}/resolve/{model["revision"]}/{model["filename"]}'
    opener = opener or urllib.request.build_opener()
    offset = part.stat().st_size if part.exists() else 0
    if offset > model["size"]:
        part.unlink()
        offset = 0
    if offset < model["size"]:
        headers = {"Accept-Encoding": "identity", "User-Agent": "niri-translate/0.1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        if cancel.is_set():
            raise Cancelled()
        with opener.open(urllib.request.Request(url, headers=headers), timeout=10) as response:
            if response.status == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if not match or int(match[1]) != offset or int(match[3]) != model["size"]:
                    raise ValueError("服务器返回了无效的断点范围，请重试")
            elif response.status == 200:
                offset = 0  # Range ignored: restart, never append a full response.
            else:
                raise ValueError(f"下载响应异常：HTTP {response.status}")
            with part.open("ab" if offset else "wb") as stream:
                while True:
                    if cancel.is_set():
                        raise Cancelled()
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    offset += len(chunk)
                    if offset > model["size"]:
                        raise ValueError("下载大小超出目录记录")
                    stream.write(chunk)
                    progress(offset, model["size"])
    if part.stat().st_size < model["size"]:
        raise RuntimeError("下载提前结束；部分文件已保留，可重试续传")
    try:
        verify(part, model, cancel)
    except ValueError:
        part.unlink(missing_ok=True)  # A bad complete file must not poison every retry.
        raise
    if cancel.is_set():
        raise Cancelled()
    part.replace(target)
    return target
