from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    role = QPalette.ColorRole
    p.setColor(role.Window, QColor(37, 38, 43))
    p.setColor(role.WindowText, QColor(225, 227, 232))
    p.setColor(role.Base, QColor(28, 29, 33))
    p.setColor(role.AlternateBase, QColor(35, 36, 41))
    p.setColor(role.Text, QColor(225, 227, 232))
    p.setColor(role.Button, QColor(52, 54, 62))
    p.setColor(role.ButtonText, QColor(225, 227, 232))
    p.setColor(role.ToolTipBase, QColor(52, 54, 62))
    p.setColor(role.ToolTipText, QColor(225, 227, 232))
    p.setColor(role.Highlight, QColor(76, 125, 214))
    p.setColor(role.HighlightedText, QColor(255, 255, 255))
    p.setColor(role.PlaceholderText, QColor(140, 143, 150))
    app.setPalette(p)
    app.setStyleSheet("""
        QToolBar { spacing: 6px; padding: 4px; border: 0; }
        QToolButton { padding: 5px 9px; border-radius: 5px; }
        QToolButton:hover { background: #3b3e49; }
        QTableView { gridline-color: #34363e; selection-background-color: #3a5fa8; }
        QHeaderView::section { background: #2d2f37; padding: 4px; border: 0; border-right: 1px solid #3a3c45; }
        QPlainTextEdit, QLineEdit, QTextEdit { border: 1px solid #3f424d; border-radius: 4px; padding: 3px; }
        QStatusBar { color: #aab0bd; }
    """)
