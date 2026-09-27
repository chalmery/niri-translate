"""Tray/controller process. The separate Quickshell surface is a layer-shell drawer."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import time

from shiboken6 import isValid
from PySide6.QtCore import QObject, QLockFile, QProcess, QProcessEnvironment, QTimer, QUrl
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon
from .desktop import autostart_path, set_autostart
from .download import download
from .catalog import fetch_catalog, load_catalog, merge_catalog, save_catalog
from .inference import LocalClient, translate
from .jobs import Job
from .runtime import Runtime
from .hardware import probe_devices
from .theme import ThemeWatcher
from .storage import (APP_ID, CONFIG, DATA, ROOT, STATE, atomic_json,
                      default_model_directory, identify_local, model_path, model_directory,
                      model_inventory, settings, verify)


def runtime_directory():
    path = Path(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/niri-translate-{os.getuid()}')) / 'niri-translate'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


class Controller(QObject):
    def __init__(self, runtime_dir, background=False, launch_ui=True):
        super().__init__()
        self.config = settings()
        self.models, catalog_updated, catalog_status = load_catalog()
        self.catalog_job = None
        # Migrate the former single external path without losing it on model switches.
        self.config.setdefault('local_paths', {})
        if self.config.get('local_path') and self.config.get('model'):
            self.config['local_paths'].setdefault(self.config['model'], self.config.pop('local_path'))
        index = next((i for i,m in enumerate(self.models) if m['id'] == self.config.get('model')), 0)
        if self.config.get('model') and self.config['model'] != self.models[index]['id']:
            catalog_status = '此前选择的模型已移出翻译模型库，已切回默认翻译模型'
        self.state = dict(open=not background, settings=False, source='', output='',
                          direction=self.config.get('direction', 0) % 2, model=index,
                          width=max(640, min(int(self.config.get('drawer_width', 820)), 1200)),
                          status='内容仅在本机处理 · 不保存历史', model_status='准备模型…',
                          ready=False, input_error=False, translating=False, model_busy=False, progress=0,
                          autostart=autostart_path().exists(), quitting=False,
                          models=model_inventory(self.config, self.models), models_dir=str(model_directory(self.config)),
                          models_dir_url=QUrl.fromLocalFile(str(model_directory(self.config))).toString(),
                          catalog_busy=False, catalog_error=False, catalog_updated=catalog_updated, catalog_status=catalog_status,
                          default_models_dir=str(default_model_directory()), models_dir_default=not bool(self.config.get('models_dir')),
                          storage_status='', storage_error=False, storage_revision=0,
                          hardware_busy=True, hardware_detail='正在检测可用计算设备…', devices=[],
                          acceleration='cpu' if self.config.get('acceleration') == 'cpu' else 'auto', backend='尚未加载', loading=False)
        self.theme = ThemeWatcher(self)
        self.state["theme"] = self.theme.current
        self.theme.updated.connect(self.theme_changed)
        self.invalid_files = {}
        self.model_job = self.translation_job = None
        self.pending_load = False
        self.jobs = set()
        self.model_epoch = self.translation_epoch = 0
        self.quitting = False
        self.clients = {}
        self.runtime = Runtime(self)
        self.runtime.mode = self.state['acceleration']
        self.runtime.changed.connect(self.runtime_changed)
        self.runtime.ready.connect(self.changed)
        self.runtime.stopped.connect(self.runtime_stopped)
        self.publish_timer = QTimer(self)
        self.publish_timer.setInterval(40)
        self.publish_timer.setSingleShot(True)
        self.publish_timer.timeout.connect(self.publish)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.socket_name = str(runtime_dir / 'instance.sock')
        QLocalServer.removeServer(self.socket_name)
        if not self.server.listen(self.socket_name):
            raise RuntimeError('无法创建单实例通信端点')
        self.server.newConnection.connect(self.accept_client)
        self.tray = QSystemTrayIcon(QIcon(str(ROOT / 'assets' / f'{APP_ID}.svg')), self)
        self.tray.setToolTip('Niri Translate · 本地翻译')
        self.menu = QMenu()
        for title, callback in [('打开翻译抽屉', self.reveal), ('设置', self.open_settings), ('退出', self.quit)]:
            self.menu.addAction(title).triggered.connect(callback)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(lambda reason: self.toggle() if reason == QSystemTrayIcon.Trigger else self.reveal() if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()
        self.tray_timer = QTimer(self)
        self.tray_timer.setInterval(2000)
        self.tray_timer.timeout.connect(self.check_tray)
        self.tray_timer.start()
        self.ui = None
        if launch_ui:
            self.launch_ui()
        self.check_tray()
        QTimer.singleShot(0, self.detect_hardware)
        self.inventory_timer = QTimer(self)
        self.inventory_timer.setInterval(2000)
        self.inventory_timer.timeout.connect(self.refresh_models)
        self.inventory_timer.start()

    def detect_hardware(self):
        job = Job(lambda job: probe_devices(DATA / 'runtime/bin/llama-server'), self)
        def detected(result):
            if self.quitting:
                return
            self.runtime.devices = result['devices']
            self.state.update(devices=result['devices'], hardware_detail=result['detail'], hardware_busy=False)
            self.changed()
            self.load_if_present()
        job.result.connect(detected)
        self.launch_job(job)

    def refresh_models(self):
        inventory = model_inventory(self.config, self.models)
        for model in inventory:
            path = Path(model['path'])
            try:
                stat = path.stat()
                if self.invalid_files.get(str(path)) == (stat.st_size, stat.st_mtime_ns):
                    model.update(local_state='invalid', label='完整性校验失败')
            except OSError:
                pass
        if inventory != self.state['models']:
            self.state['models'] = inventory
            self.changed()

    def refresh_catalog(self):
        if self.catalog_job or self.quitting:
            return
        job = Job(lambda job: fetch_catalog(job.cancelled, job.message.emit), self)
        self.catalog_job = job
        self.state.update(catalog_busy=True, catalog_error=False, catalog_status='正在连接 Hugging Face 模型目录…')
        def message(text):
            if not self.quitting:
                self.state['catalog_status'] = text
                self.changed()
        def completed(result):
            if self.quitting:
                return
            selected = self.models[self.state['model']]['id']
            try:
                models = merge_catalog(self.models, result['models'])
                save_catalog(models, result['updated_at'])
            except (OSError, ValueError) as exc:
                failed(str(exc) if isinstance(exc, ValueError) else '无法保存模型目录缓存，原列表已保留；请检查数据目录权限')
                return
            added = len(models) - len(self.models)
            self.models = models
            self.state['model'] = next(i for i, model in enumerate(models) if model['id'] == selected)
            failures = result['failures']
            detail = f"已更新 {result['completed']} 个仓库，新增 {added} 个选项；现有下载不受影响"
            if failures:
                detail += '。以下来源未更新，已保留缓存：' + '；'.join(failures)
            self.state.update(catalog_updated=result['updated_at'], catalog_status=detail, catalog_error=bool(failures))
            self.refresh_models()
            self.changed()
        def failed(error):
            if not self.quitting:
                self.state.update(catalog_error=True, catalog_status=error + '；本地模型仍可使用')
                self.changed()
        job.message.connect(message)
        job.result.connect(completed)
        job.failed.connect(failed)
        self.launch_job(job)
        self.changed()

    def model_index(self, value):
        # Stable IDs survive filtering and catalog refreshes; retain numeric IPC compatibility.
        if isinstance(value, str):
            return next((i for i, model in enumerate(self.models) if model['id'] == value), -1)
        if type(value) is int and 0 <= value < len(self.models):
            return value
        return -1

    def set_models_directory(self, value):
        if self.model_job or self.runtime.loading or self.state['hardware_busy']:
            self.state.update(storage_error=True, storage_status='请等待下载、校验或模型加载完成后再更改目录')
            return
        use_default = value is None
        if not use_default and (not isinstance(value, str) or not value.strip()):
            self.state.update(storage_error=True, storage_status='请输入模型存储目录的绝对路径')
            return
        try:
            if use_default:
                directory = default_model_directory()
            else:
                url = QUrl(value.strip())
                directory = Path(url.toLocalFile() if url.isLocalFile() else value.strip()).expanduser()
        except (ValueError, RuntimeError):
            self.state.update(storage_error=True, storage_status='目录路径无效，请检查后重试')
            return
        if not directory.is_absolute():
            self.state.update(storage_error=True, storage_status='请填写绝对路径、使用 ~/Models，或选择文件夹')
            return
        try:
            directory = directory.resolve()
            directory.mkdir(parents=True, exist_ok=True)
            # Check real write access, including ACLs, without leaving a probe file behind.
            with tempfile.TemporaryFile(dir=directory):
                pass
            use_default = use_default or directory == default_model_directory().resolve()
            updated = dict(self.config)
            if use_default:
                updated.pop('models_dir', None)
            else:
                updated['models_dir'] = str(directory)
            atomic_json(CONFIG / 'settings.json', updated)
        except (OSError, ValueError, RuntimeError):
            self.state.update(storage_error=True, storage_status='无法保存目录：请确认路径有效、目录可写且配置文件可保存；原设置未更改')
            return
        self.cancel_model()
        self.config = updated
        self.state.update(models_dir=str(directory), models_dir_url=QUrl.fromLocalFile(str(directory)).toString(),
                          models_dir_default=use_default,
                          storage_error=False, storage_revision=self.state['storage_revision'] + 1,
                          storage_status=('已恢复跟随系统默认目录。' if use_default else '已保存自定义目录。')
                          + '新下载将使用此目录；已有文件和未完成的下载保留在原位置。')
        self.refresh_models()
        self.load_if_present()

    def open_storage_folder(self):
        directory = model_directory(self.config)
        directory.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            self.state.update(storage_error=True, storage_status='无法打开文件管理器，请复制上方路径手动打开')

    def open_model_folder(self, index):
        path = Path(self.state['models'][index]['path']).parent
        path.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.state['status'] = '无法打开文件管理器，可复制模型路径手动打开'

    def model_action(self, index, action):
        if self.model_job or self.state['hardware_busy']:
            return
        if index != self.state['model']:
            self.cancel_model()
            self.state['model'] = index
            self.save_config()
        if action == 'download': self.download_model()
        else: self.load_model()

    def theme_changed(self, value):
        self.state["theme"] = value
        self.changed()

    def launch_ui(self):
        executable = shutil.which('qs')
        if not executable:
            raise RuntimeError('需要 Quickshell 0.3.1（qs）；请先安装后重试')
        self.ui = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert('NIRI_TRANSLATE_SOCKET', self.socket_name)
        env.insert('NIRI_TRANSLATE_ICON', QUrl.fromLocalFile(str(ROOT / 'assets' / f'{APP_ID}.svg')).toString())
        env.insert('QT_QUICK_CONTROLS_STYLE', 'Material')
        # Never enable QML debugging or socket/prompt logging.
        self.ui.setProcessEnvironment(env)
        self.ui.setStandardOutputFile(QProcess.nullDevice())
        self.ui.setStandardErrorFile(str(STATE / 'drawer.log'))
        self.ui.finished.connect(self.ui_exited)
        self.ui.errorOccurred.connect(self.ui_error)
        self.ui.start(sys.executable, ['-m', 'niri_translate.runtime_child', executable,
                                      '-p', str(ROOT / 'ui' / 'shell.qml')])

    def ui_error(self, error):
        if error == QProcess.FailedToStart and not self.quitting:
            self.ui_failed()

    def ui_exited(self, *_):
        if not self.quitting:
            self.ui_failed()

    def ui_failed(self):
        QMessageBox.critical(None, '翻译抽屉无法打开', f'请检查 Quickshell/Wayland 环境。诊断日志：{STATE / "drawer.log"}')
        self.quit()

    def accept_client(self):
        while self.server.hasPendingConnections():
            client = self.server.nextPendingConnection()
            self.clients[client] = bytearray()
            client.readyRead.connect(lambda c=client: self.receive(c))
            client.disconnected.connect(lambda c=client: self.remove_client(c))
            self.send_state(client)

    def remove_client(self, client):
        self.clients.pop(client, None)
        if isValid(client): client.deleteLater()

    def receive(self, client):
        if client not in self.clients:
            return
        buffer = self.clients[client]
        buffer.extend(bytes(client.readAll()))
        if len(buffer) > 8 * 1024 * 1024:
            self.stop_translation()
            self.state.update(input_error=True, status='单次输入超过本地通信上限（8 MiB），请分批粘贴；本次未翻译')
            self.send_state(client)
            client.disconnectFromServer()
            return
        while b'\n' in buffer:
            line, _, remaining = buffer.partition(b'\n')
            buffer[:] = remaining
            try:
                self.command(json.loads(line))
            except (ValueError, TypeError, KeyError, OSError):
                self.state['status'] = '请求无效或文件不可访问，请重试'
                self.changed()

    def send_state(self, client):
        if client.state() == QLocalSocket.ConnectedState:
            if client.bytesToWrite() > 8 * 1024 * 1024:
                client.disconnectFromServer()
                return
            client.write((json.dumps(self.state, ensure_ascii=False) + '\n').encode())

    def publish(self):
        for client in list(self.clients):
            self.send_state(client)

    def changed(self):
        self.state.update(ready=self.runtime.available, translating=self.translation_job is not None,
                          model_busy=self.model_job is not None, quitting=self.quitting,
                          loading=self.runtime.loading, backend=self.runtime.backend if self.runtime.available or self.runtime.loading else '尚未加载')
        if not self.publish_timer.isActive():
            self.publish_timer.start()

    def command(self, request):
        if not isinstance(request, dict) or self.quitting:
            return
        name, value = request.get('cmd'), request.get('value')
        if name == 'show': self.reveal()
        elif name == 'hide':
            if QSystemTrayIcon.isSystemTrayAvailable(): self.state['open'] = False
            else: self.state['status'] = '系统托盘不可用，保留抽屉；可在设置底部退出'
        elif name == 'toggle': self.toggle()
        elif name == 'settings':
            self.state.update(settings=bool(value), open=True);self.refresh_models()
        elif name == 'source': self.state.update(source=str(value), input_error=False)
        elif name == 'direction':
            self.stop_translation();self.state['direction'] = int(value) % 2;self.save_config()
        elif name == 'translate': self.start_translation()
        elif name == 'stop': self.stop_translation()
        elif name == 'copy': QApplication.clipboard().setText(self.state['output'])
        elif name == 'model' and self.model_index(value) >= 0: self.select_model(self.model_index(value))
        elif name == 'load': self.load_model()
        elif name == 'download': self.download_model()
        elif name in ('model_download', 'model_load') and self.model_index(value) >= 0:
            self.model_action(self.model_index(value), 'download' if name == 'model_download' else 'load')
        elif name == 'open_folder' and self.model_index(value) >= 0: self.open_model_folder(self.model_index(value))
        elif name == 'copy_path' and self.model_index(value) >= 0:
            QApplication.clipboard().setText(self.state['models'][self.model_index(value)]['path'])
            self.state['status'] = '已复制模型完整路径'
        elif name == 'refresh_models': self.refresh_models()
        elif name == 'refresh_catalog': self.refresh_catalog()
        elif name == 'cancel_catalog' and self.catalog_job: self.catalog_job.cancel()
        elif name == 'model_source' and self.model_index(value) >= 0:
            QDesktopServices.openUrl(QUrl('https://huggingface.co/' + self.models[self.model_index(value)]['repo']))
        elif name == 'models_dir': self.set_models_directory(value)
        elif name == 'reset_models_dir': self.set_models_directory(None)
        elif name == 'open_storage': self.open_storage_folder()
        elif name == 'acceleration' and value in ('auto', 'cpu') and not self.state['hardware_busy']:
            self.state['acceleration'] = self.runtime.mode = value
            self.save_config();self.cancel_model()
            if self.model_job: self.pending_load = True
            else: self.load_if_present()
        elif name == 'cancel_model': self.cancel_model()
        elif name == 'local': self.choose_local(Path(QUrl(str(value)).toLocalFile() or str(value)))
        elif name == 'autostart':
            set_autostart(bool(value));self.state['autostart'] = autostart_path().exists()
        elif name == 'width':
            self.state['width'] = max(640, min(int(value), 1200));self.save_config()
        elif name == 'quit': self.quit()
        self.changed()

    def save_config(self):
        self.config.update(model=self.models[self.state['model']]['id'], direction=self.state['direction'],
                           drawer_width=self.state['width'], acceleration=self.state['acceleration'])
        try: atomic_json(CONFIG / 'settings.json', self.config)
        except OSError: self.state['status'] = '无法保存设置，请检查配置目录权限'

    def reveal(self):
        self.state['open'] = True
        self.changed()

    def toggle(self):
        if self.state['open']: self.command({'cmd': 'hide'})
        else: self.reveal()

    def open_settings(self):
        self.state.update(open=True, settings=True)
        self.changed()

    def check_tray(self):
        if not self.quitting and not QSystemTrayIcon.isSystemTrayAvailable():
            self.state.update(open=True, status='系统托盘不可用，保留抽屉；可在设置底部退出')
            self.changed()

    def set_model_state(self, text):
        self.state['model_status'] = text
        self.changed()

    def runtime_changed(self, text): self.set_model_state(text)

    def runtime_stopped(self):
        if self.translation_job:
            self.stop_translation()
            self.state['status'] = '推理服务已停止；原文和部分译文已保留，可重新加载后重试'
        self.changed()

    def launch_job(self, job):
        self.jobs.add(job)
        job.finished.connect(lambda: self.finish_job(job))
        job.start()

    def finish_job(self, job):
        self.jobs.discard(job)
        if self.catalog_job is job:
            self.catalog_job = None
            self.state['catalog_busy'] = False
        if self.model_job is job: self.model_job = None
        if self.translation_job is job: self.translation_job = None
        job.deleteLater()
        self.refresh_models()
        self.changed()
        if self.pending_load and self.model_job is None and not self.quitting:
            self.pending_load = False
            QTimer.singleShot(0, self.load_if_present)

    def cancel_model(self):
        self.model_epoch += 1
        self.pending_load = False
        self.stop_translation()
        if self.model_job: self.model_job.cancel()
        self.runtime.stop()
        self.set_model_state('已停止；可重新下载或加载')

    def select_model(self, index):
        self.cancel_model()
        self.state['model'] = index
        self.save_config()
        if self.model_job: self.pending_load = True
        else: self.load_if_present()

    def selected_path(self):
        model = self.models[self.state['model']]
        return Path(self.config['local_paths'].get(model['id']) or model_path(model, self.config))

    def load_if_present(self):
        if self.state['hardware_busy']: return
        self.refresh_models()
        if self.selected_path().is_file(): self.load_model()
        else: self.set_model_state('未下载 · 在设置中点击下载，或选择本地 GGUF')

    def model_task(self, text, work, done):
        if self.model_job or self.quitting or self.state['hardware_busy']: return
        self.model_epoch += 1
        epoch = self.model_epoch
        self.stop_translation()
        self.runtime.stop()
        job = Job(work, self)
        self.model_job = job
        self.state['progress'] = 0
        job.result.connect(lambda value: done(value) if epoch == self.model_epoch and not self.quitting else None)
        job.failed.connect(lambda error: self.set_model_state(error) if epoch == self.model_epoch else None)
        job.progress.connect(lambda n,total: self.model_progress(epoch,n,total))
        self.set_model_state(text)
        self.launch_job(job)

    def model_progress(self, epoch, done, total):
        if epoch == self.model_epoch:
            self.state['progress'] = round(done * 100 / total, 1)
            self.changed()

    def activate_model(self, path):
        self.invalid_files.pop(str(path), None)
        self.refresh_models()
        self.runtime.load(path, profile=self.models[self.state['model']].get('profile', 'hy-mt'))

    def mark_invalid(self, path, epoch, error):
        if epoch != self.model_epoch or not ('SHA-256' in error or '文件大小不符' in error):
            return
        try:
            stat = path.stat()
            self.invalid_files[str(path)] = (stat.st_size, stat.st_mtime_ns)
            self.refresh_models()
        except OSError:
            pass

    def load_model(self):
        if self.model_job or self.quitting or self.state['hardware_busy']: return
        path, model = self.selected_path(), self.models[self.state['model']]
        if not path.is_file():
            self.set_model_state('未下载 · 请先点击下载或选择本地文件');return
        self.model_task('校验中：正在检查模型完整性…', lambda job: verify(path,model,job.cancelled,job.progress.emit), self.activate_model)
        epoch = self.model_epoch
        self.model_job.failed.connect(lambda error: self.mark_invalid(path, epoch, error))

    def download_model(self):
        model = self.models[self.state['model']]
        target = model_path(model, self.config)
        if target.is_file() and target.stat().st_size == model['size'] and str(target) not in self.invalid_files:
            self.config['local_paths'].pop(model['id'], None);self.save_config();self.load_model();return
        def completed(path):
            self.config['local_paths'].pop(model['id'], None);self.save_config();self.refresh_models();self.activate_model(path)
        self.model_task('下载中（可取消，重试从断点继续）…', lambda job: download(model,job.cancelled,job.progress.emit,target=target), completed)

    def choose_local(self, path):
        def done(model):
            self.state['model'] = self.model_index(model['id'])
            self.config['local_paths'][model['id']] = str(path.resolve())
            self.save_config();self.activate_model(path)
        models = list(self.models)
        self.model_task('校验本地文件中…', lambda job: identify_local(path,job.cancelled,job.progress.emit,models=models), done)

    def stop_translation(self):
        self.translation_epoch += 1
        if self.translation_job:
            self.translation_job.cancel();self.translation_job = None
            self.state['status'] = '已停止 · 保留已生成的译文'
        self.changed()

    def start_translation(self):
        if self.state.get('input_error'):
            self.state['status'] = '输入超过本地通信上限，请分批粘贴后重试；不会使用旧原文翻译'
            return
        text = self.state['source']
        if not text.strip():
            self.state['status'] = '请输入原文';return
        if not self.runtime.available or self.quitting:
            self.state['status'] = '请等待模型就绪；可继续编辑原文';return
        self.stop_translation()
        epoch = self.translation_epoch
        self.state.update(output='',status='准备翻译…')
        port,key = self.runtime.port,self.runtime.key
        target = '简体中文' if self.state['direction'] == 0 else '英语'
        profile = self.models[self.state['model']].get('profile', 'hy-mt')
        started = time.monotonic()
        def work(job):
            job.client = LocalClient(port,key,job.cancelled,profile=profile)
            return translate(job.client,text,target,job.chunk.emit,job.message.emit)
        job = Job(work,self)
        self.translation_job = job
        job.chunk.connect(lambda text: self.translation_update(epoch,'output',text,append=True))
        job.message.connect(lambda text: self.translation_update(epoch,'status',text))
        job.failed.connect(lambda text: self.translation_update(epoch,'status',text))
        job.result.connect(lambda result: self.translation_update(epoch,'status',f'完成 · {result["chunks"]} 段 · {time.monotonic()-started:.2f} 秒'))
        self.launch_job(job)
        self.changed()

    def translation_update(self, epoch, field, value, append=False):
        if epoch == self.translation_epoch:
            self.state[field] = self.state[field] + value if append else value
            self.changed()

    def quit(self):
        if self.quitting: return
        self.quitting = True
        self.save_config()
        self.model_epoch += 1
        self.stop_translation()
        for job in self.jobs: job.cancel()
        self.runtime.stop()
        self.state['status'] = '正在退出并清理推理进程…'
        self.tray.hide();self.tray_timer.stop()
        if self.ui and self.ui.state() != QProcess.NotRunning:
            self.ui.terminate()
            QTimer.singleShot(3000, self, self.kill_ui)
        self.exit_timer = QTimer(self)
        self.exit_timer.timeout.connect(self.finish_quit)
        self.exit_timer.start(100)

    def kill_ui(self):
        if self.ui and self.ui.state() != QProcess.NotRunning: self.ui.kill()

    def finish_quit(self):
        if not self.jobs and self.runtime.process is None and (self.ui is None or self.ui.state() == QProcess.NotRunning):
            self.server.close()
            QApplication.instance().quit()


def main():
    parser=argparse.ArgumentParser(description='Niri Translate 本地翻译抽屉')
    parser.add_argument('--background',action='store_true')
    args=parser.parse_args()
    app=QApplication(sys.argv)
    app.setApplicationName('niri-translate');app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)
    runtime_dir=runtime_directory()
    lock=QLockFile(str(runtime_dir/'instance.lock'));lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        connection=QLocalSocket();connection.connectToServer(str(runtime_dir/'instance.sock'))
        if connection.waitForConnected(2000):
            connection.write(b'{"cmd":"show"}\n');connection.waitForBytesWritten(1000);return 0
        QMessageBox.warning(None,'Niri Translate','已有实例仍在启动或退出，请稍后重试。');return 1
    STATE.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(STATE/'client.log',maxBytes=256*1024,backupCount=1)
    logging.basicConfig(handlers=[handler],level=logging.INFO)
    logging.info('client started')
    try:
        controller=Controller(runtime_dir,args.background)
    except RuntimeError as exc:
        QMessageBox.critical(None,'Niri Translate',str(exc));return 1
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,lambda *_:controller.quit())
    timer=QTimer();timer.timeout.connect(lambda:None);timer.start(200)
    result=app.exec();lock.unlock();logging.info('client exited')
    return result


if __name__=='__main__': raise SystemExit(main())
