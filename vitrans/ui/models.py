from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QColor

from ..models import ERROR, KIND_LABEL, MACHINE, REVIEWED, SKIP, STATUS_LABEL, Entry

COLS = ["#", "Tệp", "Loại", "Người nói", "Tiếng Anh", "Tiếng Việt", "Trạng thái"]
TRANS_COL = 5
_BG = {
    ERROR: QColor(200, 70, 70, 70),
    REVIEWED: QColor(70, 160, 90, 55),
    MACHINE: QColor(70, 120, 200, 35),
    SKIP: QColor(120, 120, 120, 40),
}
_WARN = QColor(220, 170, 40, 70)


def one_line(s: str, n: int = 160) -> str:
    s = s.replace("\n", " ⏎ ")
    return s if len(s) <= n else s[: n - 1] + "…"


class EntryModel(QAbstractTableModel):
    def __init__(self, on_edit, parent=None):
        super().__init__(parent)
        self.entries: list[Entry] = []
        self._index: dict[str, int] = {}
        self._on_edit = on_edit

    def set_entries(self, entries: list[Entry]) -> None:
        self.beginResetModel()
        self.entries = entries
        self._index = {e.key: i for i, e in enumerate(entries)}
        self.endResetModel()

    def refresh_keys(self, keys) -> None:
        rows = sorted(self._index[k] for k in keys if k in self._index)
        if not rows:
            return
        if len(rows) > 300:
            self.dataChanged.emit(self.index(rows[0], 0), self.index(rows[-1], len(COLS) - 1))
            return
        for r in rows:
            self.dataChanged.emit(self.index(r, 0), self.index(r, len(COLS) - 1))

    # --- Qt API -------------------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLS[section]
        return None

    def flags(self, index):
        # Chỉnh bản dịch ở khung bên phải (đa dòng); ô trong bảng một dòng sẽ làm mất xuống dòng
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [str(index.row() + 1), e.file.rsplit("/", 1)[-1], KIND_LABEL.get(e.kind, e.kind), e.speaker,
                    one_line(e.source), one_line(e.translation), STATUS_LABEL.get(e.status, e.status)][c]
        if role == Qt.ItemDataRole.EditRole and c == TRANS_COL:
            return e.translation
        if role == Qt.ItemDataRole.ToolTipRole:
            tip = e.source if c == 4 else (e.translation if c == TRANS_COL else e.file)
            return f"{tip}\n\n⚠ {e.warn}" if e.warn and c in (TRANS_COL, 6) else tip
        if role == Qt.ItemDataRole.BackgroundRole:
            if e.warn and e.status != ERROR:
                return _WARN
            return _BG.get(e.status)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole and index.column() == TRANS_COL:
            self._on_edit(self.entries[index.row()], str(value))
            self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), len(COLS) - 1))
            return True
        return False


class EntryProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.status = ""      # "", pending, machine, reviewed, error, skip, warn
        self.kind = ""
        self.text = ""

    def set_filters(self, status: str, kind: str, text: str) -> None:
        self.status, self.kind, self.text = status, kind, text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        e = self.sourceModel().entries[row]
        if self.status == "warn":
            if not e.warn:
                return False
        elif self.status and e.status != self.status:
            return False
        if self.kind and e.kind != self.kind:
            return False
        if self.text and self.text not in (e.source + "\n" + e.translation + "\n" + e.speaker).lower():
            return False
        return True
