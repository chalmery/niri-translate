import threading
from PySide6.QtCore import QThread, Signal
from .storage import Cancelled


class Job(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(object, object)
    message = Signal(str)
    chunk = Signal(str)

    def __init__(self, work, parent=None):
        super().__init__(parent)
        self.work = work
        self.cancelled = threading.Event()
        self.client = None

    def cancel(self):
        self.cancelled.set()
        if self.client:
            self.client.cancel()

    def run(self):
        try:
            value = self.work(self)
            if self.cancelled.is_set():
                raise Cancelled()
            self.result.emit(value)
        except Cancelled:
            self.failed.emit("已停止")
        except Exception as exc:
            # Exception strings from local code contain no translated text.
            self.failed.emit(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else f"操作失败（{type(exc).__name__}），请检查连接或文件权限后重试")
