import hashlib
import json
import os
from pathlib import Path

APP_ID = "io.github.chalmery.niri-translate"
ROOT = Path(__file__).parent
MODELS = json.loads((ROOT / "models.json").read_text())


def xdg(variable, default):
    return Path(os.environ.get(variable) or Path.home() / default) / "niri-translate"


CONFIG = xdg("XDG_CONFIG_HOME", ".config")
DATA = xdg("XDG_DATA_HOME", ".local/share")
STATE = xdg("XDG_STATE_HOME", ".local/state")


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.chmod(0o600)
    tmp.replace(path)


def settings():
    try:
        return json.loads((CONFIG / "settings.json").read_text())
    except (OSError, ValueError):
        return {}


def model_path(model):
    return DATA / "models" / model["filename"]


class Cancelled(Exception):
    pass


def verify(path, model, cancel, progress=lambda *_: None):
    if path.stat().st_size != model["size"]:
        raise ValueError("文件大小不符，请重新下载官方模型")
    digest = hashlib.sha256()
    done = 0
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            if cancel.is_set():
                raise Cancelled()
            digest.update(chunk)
            done += len(chunk)
            progress(done, model["size"])
    if digest.hexdigest() != model["sha256"]:
        raise ValueError("SHA-256 校验失败；不会加载该文件")
    return path


def identify_local(path, cancel, progress=lambda *_: None):
    candidates = [m for m in MODELS if m["size"] == path.stat().st_size]
    for model in candidates:
        try:
            verify(path, model, cancel, progress)
            return model
        except ValueError:
            pass
    raise ValueError("仅支持设置中列出的三个官方 GGUF（按大小及 SHA-256 识别）")
