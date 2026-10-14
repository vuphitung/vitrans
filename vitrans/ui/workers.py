from __future__ import annotations

import threading
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from ..providers import ProviderError


class Worker(QThread):
    """Chạy một hàm nặng ở luồng nền. fn(worker) -> kết quả; dùng worker.progress/updated/cancel."""
    progress = pyqtSignal(int, int, str)
    updated = pyqtSignal(list)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            result = self.fn(self)
        except ProviderError as ex:
            self.failed.emit(str(ex))
        except Exception as ex:  # noqa: BLE001 - mọi lỗi phải hiện lên giao diện, không được làm sập luồng
            traceback.print_exc()
            self.failed.emit(f"{type(ex).__name__}: {ex}")
        else:
            self.done.emit(result)
