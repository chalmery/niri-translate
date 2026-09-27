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
import time

from PySide6.QtCore import QObject, QLockFile, QProcess, QProcessEnvironment, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon
from .desktop import autostart_path, set_autostart
from .download import download
from .inference import LocalClient, translate
from .jobs import Job
from .runtime import Runtime
from .theme import ThemeWatcher
from .storage import (APP_ID, CONFIG, DATA, MODELS, ROOT, STATE, atomic_json,
                      identify_local, model_path, settings, verify)


def runtime_directory():
    path = Path(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/niri-translate-{os.getuid()}')) / 'niri-translate'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


class Controller(QObject):
    def __init__(self, runtime_dir, background=False, launch_ui=True):
        super().__init__()
        self.config = settings()
        index = next((i for i,m in enumerate(MODELS) if m['id'] == self.config.get('model')), 0)
        self.state = dict(open=not background, settings=False, source='', output='',
                          direction=self.config.get('direction', 0) % 2, model=index,
                          width=max(640, min(int(self.config.get('drawer_width', 820)), 1200)),
                          status='内容仅在本机处理 · 不保存历史', model_status='准备模型…',
                          ready=False, input_error=False, translating=False, model_busy=False, progress=0,
                          autostart=autostart_path().exists(), quitting=False,
                          models=[dict(name=m['name'], size=m['size'], id=m['id']) for m in MODELS])
        self.theme = ThemeWatcher(self)
        self.state["theme"] = self.theme.current
        self.theme.updated.connect(self.theme_changed)
        self.model_job = self.translation_job = None
        self.pending_load = False
        self.jobs = set()
        self.model_epoch = self.translation_epoch = 0
        self.quitting = False
        self.clients = {}
        self.runtime = Runtime(self)
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
        QTimer.singleShot(0, self.load_if_present)

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
        client.deleteLater()

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
                          model_busy=self.model_job is not None, quitting=self.quitting)
        if not self.publish_timer.isActive():
            self.publish_timer.start()

    def command(self, request):
        if not isinstance(request, dict) or self.quitting:
            return
        name, value = request.get('cmd'), request.get('value')
        if name == 'show': self.reveal()
        elif name == 'hide':
            if QSystemTrayIcon.isSystemTrayAvailable(): self.state['open'] = False
            else: self.state['status'] = '系统托盘不可用，保留抽屉；可使用右上角菜单退出'
        elif name == 'toggle': self.toggle()
        elif name == 'settings': self.state.update(settings=bool(value), open=True)
        elif name == 'source': self.state.update(source=str(value), input_error=False)
        elif name == 'direction':
            self.stop_translation();self.state['direction'] = int(value) % 2;self.save_config()
        elif name == 'translate': self.start_translation()
        elif name == 'stop': self.stop_translation()
        elif name == 'copy': QApplication.clipboard().setText(self.state['output'])
        elif name == 'model' and 0 <= int(value) < len(MODELS): self.select_model(int(value))
        elif name == 'load': self.load_model()
        elif name == 'download': self.download_model()
        elif name == 'cancel_model': self.cancel_model()
        elif name == 'local': self.choose_local(Path(QUrl(str(value)).toLocalFile() or str(value)))
        elif name == 'autostart':
            set_autostart(bool(value));self.state['autostart'] = autostart_path().exists()
        elif name == 'width':
            self.state['width'] = max(640, min(int(value), 1200));self.save_config()
        elif name == 'quit': self.quit()
        self.changed()

    def save_config(self):
        self.config.update(model=MODELS[self.state['model']]['id'], direction=self.state['direction'],
                           drawer_width=self.state['width'])
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
            self.state.update(open=True, status='系统托盘不可用，保留抽屉；可在右上角菜单退出')
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
        if self.model_job is job: self.model_job = None
        if self.translation_job is job: self.translation_job = None
        job.deleteLater()
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
        self.config.pop('local_path', None)
        self.save_config()
        if self.model_job: self.pending_load = True
        else: self.load_if_present()

    def selected_path(self):
        return Path(self.config['local_path']) if self.config.get('local_path') else model_path(MODELS[self.state['model']])

    def load_if_present(self):
        if self.selected_path().is_file(): self.load_model()
        else: self.set_model_state('未下载 · 在设置中点击下载，或选择本地 GGUF')

    def model_task(self, text, work, done):
        if self.model_job or self.quitting: return
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

    def load_model(self):
        path, model = self.selected_path(), MODELS[self.state['model']]
        if not path.is_file():
            self.set_model_state('未下载 · 请先点击下载或选择本地文件');return
        self.model_task('校验中：正在检查模型完整性…', lambda job: verify(path,model,job.cancelled,job.progress.emit), self.runtime.load)

    def download_model(self):
        model = MODELS[self.state['model']]
        if model_path(model).is_file():
            self.config.pop('local_path', None);self.load_model();return
        def completed(path):
            self.config.pop('local_path', None);self.save_config();self.runtime.load(path)
        self.model_task('下载中（可取消，重试从断点继续）…', lambda job: download(model,job.cancelled,job.progress.emit), completed)

    def choose_local(self, path):
        def done(model):
            self.state['model'] = MODELS.index(model)
            self.config['local_path'] = str(path)
            self.save_config();self.runtime.load(path)
        self.model_task('校验本地文件中…', lambda job: identify_local(path,job.cancelled,job.progress.emit), done)

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
        started = time.monotonic()
        def work(job):
            job.client = LocalClient(port,key,job.cancelled)
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
