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
        config = json.loads((CONFIG / "settings.json").read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(config, dict):
        return {}
    # Older versions saved an absolute path even when restoring the default.
    # Drop only overrides matching this user's current default; preserve custom paths.
    configured = config.get('models_dir')
    if isinstance(configured, str) and configured:
        try:
            if Path(configured).expanduser().resolve() == default_model_directory().resolve():
                config.pop('models_dir')
        except (OSError, ValueError, RuntimeError):
            pass
    return config


def default_model_directory():
    """Resolve per-user storage at startup; never persist the default as an override."""
    return DATA / 'models'


def model_directory(config=None):
    config = settings() if config is None else config
    configured = config.get('models_dir')
    if isinstance(configured, str) and configured:
        directory = Path(configured).expanduser()
        if directory.is_absolute():
            return directory
    return default_model_directory()


def model_path(model, config=None):
    directory = model_directory(config)
    if model.get('catalog_model'):
        # Keep equal filenames/revisions from different repositories isolated.
        directory = directory / 'catalog' / model['sha256']
    return directory / model["filename"]


class Cancelled(Exception):
    pass


def verify(path, model, cancel, progress=lambda *_: None):
    if path.stat().st_size != model["size"]:
        raise ValueError("文件大小不符，请重新下载模型库中的对应文件")
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


def identify_local(path, cancel, progress=lambda *_: None, models=None):
    candidates = [m for m in (MODELS if models is None else models) if m["size"] == path.stat().st_size]
    for model in candidates:
        try:
            verify(path, model, cancel, progress)
            return model
        except ValueError:
            pass
    raise ValueError("文件未匹配当前模型库。请先在线更新模型目录，再导入列表中的 GGUF（按大小及 SHA-256 识别）")


def model_inventory(config, models=None):
    """Cheap disk snapshot. A matching size never substitutes for load-time SHA-256."""
    local_paths = config.get('local_paths', {})
    result = []
    for model in (MODELS if models is None else models):
        path = Path(local_paths.get(model['id']) or model_path(model, config))
        part = model_path(model, config).with_suffix('.gguf.part')
        size = partial = 0
        state = 'missing'
        try:
            if path.is_file():
                size = path.stat().st_size
                state = 'present' if size == model['size'] else 'invalid'
            if part.is_file():
                partial = part.stat().st_size
                if state == 'missing':
                    state = 'partial'
        except OSError:
            state = 'unreadable'
        result.append(dict(id=model['id'], name=model['name'], size=model['size'],
                           family=model.get('family', 'Hy-MT'), kind=model.get('kind', 'translation'),
                           description=model.get('description', '翻译模型'), quant=model.get('quant', ''),
                           repo=model['repo'], publisher=model.get('publisher', '官方'),
                           revision=model['revision'], recommended=model.get('recommended', False),
                           path=str(path), external=path != model_path(model, config),
                           disk_size=size, partial_size=partial, local_state=state,
                           label={'present': '已在本地', 'missing': '未下载', 'partial': '下载未完成',
                                  'invalid': '文件大小异常', 'unreadable': '无法访问'}[state]))
    return result
