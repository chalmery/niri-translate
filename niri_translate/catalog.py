"""Translation-only GGUF discovery through public Hugging Face metadata."""
from datetime import datetime, timezone
import json
import re
import urllib.error
import urllib.request

from .storage import DATA, MODELS, ROOT, Cancelled, atomic_json

SOURCES = [source for source in json.loads((ROOT / 'model_sources.json').read_text())
           if source.get('kind') == 'translation']
SOURCE_MAP = {source['repo']: source for source in SOURCES}
BUNDLED = {(m['repo'], m['filename'], m['sha256']): m for m in MODELS}
CACHE = DATA / 'model-catalog.json'
MAX_RESPONSE = 4 * 1024 * 1024
MAX_MODELS = 2048
QUANT = re.compile(r'-(Q4_K_M|Q5_K_M|Q6_K|Q8_0)\.gguf$', re.IGNORECASE)


def normalise_model(raw):
    """Validate remote/cache metadata; derive all local paths and labels ourselves."""
    if not isinstance(raw, dict):
        raise ValueError('模型目录条目无效')
    repo, filename = raw.get('repo'), raw.get('filename')
    source = SOURCE_MAP.get(repo)
    if not source or not isinstance(filename, str) or len(filename) > 180:
        raise ValueError('不支持的模型来源或文件名')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.gguf', filename, re.IGNORECASE):
        raise ValueError('只支持仓库根目录中的单文件 GGUF')
    quant = QUANT.search(filename)
    if not quant or 'mmproj' in filename.lower():
        raise ValueError('不在常用量化范围内')
    revision, digest, size = raw.get('revision'), raw.get('sha256'), raw.get('size')
    if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('缺少固定仓库版本')
    if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('缺少模型 SHA-256')
    if type(size) is not int or not 0 < size < 2**48:
        raise ValueError('模型大小无效')
    bundled = BUNDLED.get((repo, filename, digest))
    if bundled:
        return dict(bundled)
    q = quant[1].upper()
    return dict(id=f'hf:{repo}:{filename}:{digest}', name=f"{source['name']} {q}",
                repo=repo, revision=revision, filename=filename, size=size, sha256=digest,
                quant=q, family=source['family'], kind=source['kind'], description=source['description'],
                publisher=source['publisher'], profile=source['profile'],
                recommended=source.get('lightweight', False) and q == source['preferred_quant'],
                catalog_model=True)


def merge_catalog(existing, incoming):
    # Append only: a refreshed index must not change a running model or an in-flight job.
    result = [model for model in existing if model.get('repo') in SOURCE_MAP]
    identities = {m['id'] for m in result}
    for raw in incoming:
        # Old caches may contain general-purpose models. Never reintroduce removed sources.
        if isinstance(raw, dict) and isinstance(raw.get('repo'), str) and raw['repo'] not in SOURCE_MAP:
            continue
        model = normalise_model(raw)
        if model['id'] not in identities:
            if len(result) >= MAX_MODELS:
                raise ValueError('模型目录达到容量上限，请清理目录缓存后重试')
            result.append(model)
            identities.add(model['id'])
    return result


def load_catalog():
    try:
        if CACHE.stat().st_size > MAX_RESPONSE:
            raise ValueError('模型目录缓存过大')
        cached = json.loads(CACHE.read_text())
        if not isinstance(cached, dict) or cached.get('version') != 1 or not isinstance(cached.get('models'), list):
            raise ValueError('模型目录缓存格式不支持')
        models = merge_catalog(MODELS, cached['models'])
        updated = cached.get('updated_at', '')
        if not isinstance(updated, str) or len(updated) > 40:
            updated = ''
        return models, updated, '已读取本地模型目录；可离线浏览，点击在线更新获取新版本'
    except FileNotFoundError:
        return list(MODELS), '', '内置翻译专用模型目录；点击在线更新获取新版本'
    except (OSError, ValueError, TypeError):
        return list(MODELS), '', '目录缓存无法读取，已使用内置列表；可重新在线更新'


def save_catalog(models, updated_at):
    atomic_json(CACHE, dict(version=1, updated_at=updated_at, models=models))


def fetch_catalog(cancel, message=lambda _: None):
    models, failures = [], []
    completed = 0
    for source in SOURCES:
        if cancel.is_set():
            raise Cancelled()
        repo = source['repo']
        message(f"正在读取 {source['name']}（{completed + len(failures) + 1}/{len(SOURCES)}）…")
        try:
            request = urllib.request.Request(f'https://huggingface.co/api/models/{repo}?blobs=true',
                                             headers={'User-Agent': 'niri-translate/0.1', 'Accept': 'application/json'})
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if cancel.is_set():
                raise Cancelled()
            if len(raw) > MAX_RESPONSE:
                raise ValueError('仓库元数据过大')
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('id') != repo or not isinstance(data.get('siblings'), list):
                raise ValueError('仓库元数据无效')
            found = []
            for entry in data['siblings']:
                if not isinstance(entry, dict):
                    continue
                lfs = entry.get('lfs')
                if not isinstance(lfs, dict):
                    continue
                try:
                    found.append(normalise_model(dict(repo=repo, revision=data.get('sha'), filename=entry.get('rfilename'),
                                                      size=lfs.get('size'), sha256=lfs.get('sha256'))))
                except ValueError:
                    continue  # Ignore shards, projectors and files with no verifiable metadata.
            if not found:
                raise ValueError('仓库没有可用的常用单文件 GGUF')
            models.extend(sorted(found, key=lambda m: (not m['recommended'], m['size'])))
            completed += 1
        except urllib.error.HTTPError as exc:
            failures.append(f"{source['name']}：HTTP {exc.code}")
        except (OSError, ValueError, TypeError):
            failures.append(f"{source['name']}：网络或目录信息不可用")
    if cancel.is_set():
        raise Cancelled()
    if not completed:
        raise RuntimeError('在线更新失败，原有列表和本地模型已保留。请检查 Hugging Face 连接后重试。')
    return dict(models=models, failures=failures, completed=completed,
                updated_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
