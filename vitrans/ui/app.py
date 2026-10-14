from __future__ import annotations

import sys


def run_gui(game: str | None = None) -> int:
    from PyQt6.QtWidgets import QApplication

    from ..config import AppConfig
    from .main_window import MainWindow
    from .theme import apply_theme

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    cfg = AppConfig()
    win = MainWindow(cfg)
    win.show()
    if game:
        win.open_project(game)
    return app.exec()
