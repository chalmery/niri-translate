import os
from pathlib import Path
import secrets
import socket
import sys
import time
from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from .storage import DATA


class Runtime(QObject):
    changed = Signal(str)
    ready = Signal()
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.stopping = False
        self.desired = None
        self.port, self.key = 0, ""
        self.available = False
        self.devices = []
        self.mode = 'auto'
        self.backend = 'CPU'
        self.loaded_path = None
        self.loading = False
        self.fallback = False
        self.started_at = 0
        self.load_seconds = 0
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.poll)

    def load(self, path):
        self.desired = Path(path)
        self.fallback = False
        self.available = False
        if self.process:
            self.changed.emit("正在卸载旧模型…")
            self._terminate()
        else:
            self._start()

    def stop(self):
        self.desired = None
        self.loading = False
        self.available = False
        self.timer.stop()
        self._terminate()

    def _terminate(self):
        self.stopping = True
        self.timer.stop()
        if self.reply:
            self.reply.abort()
        if self.process:
            proc = self.process
            proc.terminate()
            QTimer.singleShot(3000, self, lambda: self._kill_if_current(proc))
        else:
            self.stopped.emit()

    def _kill_if_current(self, proc):
        if self.process is proc and proc.state() != QProcess.NotRunning:
            proc.kill()

    def _start(self):
        if self.desired is None:
            self.stopped.emit()
            return
        binary = DATA / "runtime" / "bin" / "llama-server"
        if not binary.is_file():
            self.changed.emit("推理运行时未安装，请运行 scripts/build-runtime.sh")
            return
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.stopping = False
        self.loading = True
        self.loaded_path = self.desired
        device = self.devices[0] if self.mode == 'auto' and self.devices and not self.fallback else None
        self.backend = ('GPU · ' + device['name']) if device else 'CPU'
        device_args = ['--device', device['id'], '-ngl', '999', '--fit', 'off'] if device else ['--device', 'none', '-ngl', '0']
        self.key = secrets.token_urlsafe(32)
        proc = QProcess(self)
        self.process = proc
        proc.setStandardOutputFile(QProcess.nullDevice())
        proc.setStandardErrorFile(QProcess.nullDevice())  # Never persist prompts/server request dumps.
        proc.finished.connect(lambda code, status: self._finished(proc, code))
        proc.errorOccurred.connect(lambda error: self._error(proc, error))
        proc.setProgram(sys.executable)
        proc.setArguments(["-m", "niri_translate.runtime_child", str(binary), "-m", str(self.desired),
                           "--host", "127.0.0.1", "--port", str(self.port), *device_args,
                           "-t", str(min(8, os.cpu_count() or 4)), "-c", "8192", "-np", "1",
                           "--jinja", "--no-context-shift", "--no-webui", "--offline",
                           "--log-disable", "--api-key", self.key])
        self.desired = None
        self.started_at = time.monotonic()
        prefix = 'GPU 加载失败，已自动切回 CPU · ' if self.fallback else ''
        self.changed.emit(f"{prefix}加载中：{self.backend}…")
        proc.start()
        self.timer.start()

    def _error(self, proc, error):
        if error == QProcess.FailedToStart and self.process is proc:
            self.timer.stop()
            self.process = None
            self.loading = False
            proc.deleteLater()
            self.changed.emit("启动失败：请检查运行时及其动态库是否安装完整")
            self.stopped.emit()

    def _finished(self, proc, code):
        if self.process is not proc:
            return
        self.available = False
        self.timer.stop()
        self.process = None
        if self.reply:
            self.reply.abort()
        self.loading = False
        proc.deleteLater()
        if not self.stopping and self.backend.startswith('GPU') and not self.fallback:
            self.fallback = True
            self.desired = self.loaded_path
        if self.desired:
            self._start()
        else:
            if not self.stopping:
                self.changed.emit(f"推理服务意外退出（{code}）；请在设置中重新加载模型")
            self.stopped.emit()

    def poll(self):
        if self.reply or not self.process:
            return
        if time.monotonic() - self.started_at > 180:
            if self.backend.startswith('GPU') and not self.fallback:
                self.fallback = True
                self.desired = self.loaded_path
                self._terminate()
                self.changed.emit('GPU 加载超时，正在切回 CPU…')
            else:
                self.stop()
                self.changed.emit("模型加载超时（180 秒）；可在设置中重试")
            return
        request = QNetworkRequest(QUrl(f"http://127.0.0.1:{self.port}/health"))
        request.setRawHeader(b"Authorization", ("Bearer " + self.key).encode())
        request.setTransferTimeout(1500)
        reply = self.network.get(request)
        self.reply = reply
        proc = self.process
        reply.finished.connect(lambda: self._health(reply, proc))

    def _health(self, reply, proc):
        code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if self.reply is reply:
            self.reply = None
        reply.deleteLater()
        if code == 200 and self.process is proc and not self.desired and not self.stopping:
            self.available = True
            self.loading = False
            self.load_seconds = time.monotonic() - self.started_at
            self.timer.stop()
            self.changed.emit(f"可使用 · {self.backend} · 加载 {self.load_seconds:.2f} 秒" + (" · GPU 失败后回退" if self.fallback else ""))
            self.ready.emit()
