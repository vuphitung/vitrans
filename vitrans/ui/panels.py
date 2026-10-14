from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..models import KIND_LABEL, SKIP, STATUS_LABEL, Entry, Style, Term
from ..wrapping import wrap


class EditPanel(QWidget):
    save_requested = pyqtSignal(object, str)       # entry, text  -> đánh dấu đã duyệt
    retranslate_requested = pyqtSignal(object)
    skip_toggled = pyqtSignal(object)

    def __init__(self, get_opts, parent=None):
        super().__init__(parent)
        self._get_opts = get_opts
        self.entry: Entry | None = None
        self._loading = False
        self._dirty = False
        self._busy = False
        lay = QVBoxLayout(self)
        self.meta = QLabel("Chọn một câu ở bảng bên trái")
        self.meta.setWordWrap(True)
        self.source = QPlainTextEdit(readOnly=True)
        self.source.setPlaceholderText("Bản gốc")
        self.source.setMaximumHeight(110)
        self.trans = QPlainTextEdit()
        self.trans.setPlaceholderText("Bản dịch tiếng Việt (Ctrl+Enter để lưu & duyệt)")
        self.warn = QLabel()
        self.warn.setStyleSheet("color:#e0b03a")
        self.warn.setWordWrap(True)
        self.preview = QPlainTextEdit(readOnly=True)
        self.preview.setMaximumHeight(110)
        self.preview_info = QLabel()
        row = QHBoxLayout()
        self.btn_save = QPushButton("Lưu && duyệt")
        self.btn_ai = QPushButton("Dịch lại bằng AI")
        self.btn_skip = QPushButton("Bỏ qua câu này")
        for b in (self.btn_save, self.btn_ai, self.btn_skip):
            row.addWidget(b)
        for w in (self.meta, QLabel("Bản gốc"), self.source, QLabel("Bản dịch"), self.trans, self.warn,
                  self.preview_info, self.preview):
            lay.addWidget(w)
        lay.addLayout(row)
        lay.addStretch(1)
        self.btn_save.clicked.connect(self._save)
        self.btn_ai.clicked.connect(lambda: self.entry and self.retranslate_requested.emit(self.entry))
        self.btn_skip.clicked.connect(lambda: self.entry and self.skip_toggled.emit(self.entry))
        self.trans.textChanged.connect(self._on_text)
        # Ctrl+Enter lưu & duyệt. Dùng QShortcut gắn vào ô soạn thảo (QPlainTextEdit tự nuốt phím Enter).
        self._shortcuts = []
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            sc = QShortcut(QKeySequence(seq), self.trans)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._save)
            self._shortcuts.append(sc)
        self._refresh_enabled()

    def set_busy(self, busy: bool) -> None:
        """Đang dịch nền: khóa chỉnh sửa để người dùng và tiến trình dịch không ghi đè lẫn nhau."""
        self._busy = busy
        self._refresh_enabled()

    def _refresh_enabled(self) -> None:
        self.setEnabled(self.entry is not None and not self._busy)

    def load(self, entry: Entry | None) -> None:
        self.commit_pending()
        self.entry = entry
        self._loading = True
        if entry is None:
            self.meta.setText("Chọn một câu ở bảng bên trái")
            self.source.clear()
            self.trans.clear()
            self.warn.clear()
        else:
            who = f" · {entry.speaker}" if entry.speaker else ""
            self.meta.setText(f"{KIND_LABEL.get(entry.kind, entry.kind)}{who} · {STATUS_LABEL.get(entry.status)} · "
                              f"{entry.file}")
            self.source.setPlainText(entry.source)
            self.trans.setPlainText(entry.translation)
            self.warn.setText(f"⚠ {entry.warn}" if entry.warn else "")
            self.btn_skip.setText("Bỏ đánh dấu bỏ qua" if entry.status == SKIP else "Bỏ qua câu này")
        self._loading = False
        self._dirty = False
        self._refresh_enabled()
        self._update_preview()

    def commit_pending(self) -> None:
        if self.entry is not None and self._dirty and not self._busy:
            self._save()

    def _on_text(self) -> None:
        if not self._loading:
            self._dirty = True
        self._update_preview()

    def _save(self) -> None:
        if self.entry is None or self._busy:
            return
        self._dirty = False
        self.save_requested.emit(self.entry, self.trans.toPlainText())

    def _update_preview(self) -> None:
        e = self.entry
        text = self.trans.toPlainText()
        if e is None or not text.strip():
            self.preview.clear()
            self.preview_info.setText("")
            return
        width = self._get_opts(e)
        if width is None:
            self.preview_info.setText("Xem trước")
            self.preview.setPlainText(text)
            return
        lines = wrap(text, width)
        max_lines = self._get_opts(None)
        over = f" — vượt {max_lines} dòng, sẽ tách thành nhiều trang" if len(lines) > max_lines else ""
        self.preview_info.setText(f"Xem trước trong hộp thoại (rộng ~{width} ký tự, {len(lines)} dòng){over}")
        self.preview.setPlainText("\n".join(lines))


class GlossaryPanel(QWidget):
    changed = pyqtSignal()
    suggest_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Từ điển: tên riêng/thuật ngữ cần dịch nhất quán. Cột 'Tiếng Việt' để trống = giữ nguyên."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Tiếng Anh", "Tiếng Việt", "Ghi chú"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 160)
        row = QHBoxLayout()
        add, rem, sug = QPushButton("Thêm"), QPushButton("Xóa dòng"), QPushButton("Gợi ý từ tên nhân vật")
        for b in (add, rem, sug):
            row.addWidget(b)
        lay.addWidget(self.table)
        lay.addLayout(row)
        add.clicked.connect(lambda: self._add_row("", "", ""))
        rem.clicked.connect(self._remove)
        sug.clicked.connect(self.suggest_requested)
        self.table.itemChanged.connect(lambda *_: self.changed.emit())
        self._block = False

    def _add_row(self, a: str, b: str, c: str) -> None:
        self._block = True
        r = self.table.rowCount()
        self.table.insertRow(r)
        for i, v in enumerate((a, b, c)):
            self.table.setItem(r, i, QTableWidgetItem(v))
        self._block = False
        self.changed.emit()

    def _remove(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self.changed.emit()

    def set_terms(self, terms: list[Term]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for t in terms:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for i, v in enumerate((t.src, t.vi, t.note)):
                self.table.setItem(r, i, QTableWidgetItem(v))
        self.table.blockSignals(False)

    def add_terms(self, terms: list[Term]) -> None:
        for t in terms:
            self._add_row(t.src, t.vi, t.note)

    def terms(self) -> list[Term]:
        out = []
        for r in range(self.table.rowCount()):
            cell = [(self.table.item(r, c).text() if self.table.item(r, c) else "") for c in range(3)]
            if cell[0].strip():
                out.append(Term(cell[0], cell[1], cell[2]))
        return out


class StylePanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        self.src_lang = QLineEdit()
        self.src_lang.setPlaceholderText("VD: English, Japanese, Chinese")
        self.genre = QLineEdit()
        self.tone = QLineEdit()
        self.pron = QLineEdit()
        self.pron.setPlaceholderText("VD: nhân vật chính xưng 'tôi', gọi người lạ là 'anh/chị'; quái vật xưng 'ta'")
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(110)
        form.addRow("Ngôn ngữ gốc của game", self.src_lang)
        form.addRow("Thể loại", self.genre)
        form.addRow("Giọng văn", self.tone)
        form.addRow("Cách xưng hô", self.pron)
        form.addRow("Ghi chú thêm", self.notes)
        form.addRow(QLabel("Các thông tin này được gửi kèm mỗi lô dịch để AI giữ đúng giọng và xưng hô."))
        for w in (self.src_lang, self.genre, self.tone, self.pron):
            w.textChanged.connect(self.changed)
        self.notes.textChanged.connect(self.changed)

    def set_style(self, s: Style) -> None:
        for w in (self.src_lang, self.genre, self.tone, self.pron, self.notes):
            w.blockSignals(True)
        self.src_lang.setText(s.source_lang)
        self.genre.setText(s.genre)
        self.tone.setText(s.tone)
        self.pron.setText(s.pronouns)
        self.notes.setPlainText(s.notes)
        for w in (self.src_lang, self.genre, self.tone, self.pron, self.notes):
            w.blockSignals(False)

    def style(self) -> Style:
        return Style(self.src_lang.text().strip() or "English", self.genre.text(), self.tone.text(),
                     self.pron.text(), self.notes.toPlainText())
