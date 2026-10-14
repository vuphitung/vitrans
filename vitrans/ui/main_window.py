from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
                             QMessageBox, QProgressBar, QSplitter, QTableView, QTabWidget, QToolBar, QVBoxLayout,
                             QWidget)

from .. import adapters
from ..config import AppConfig
from ..models import (ERROR, KIND_LABEL, MACHINE, PENDING, REVIEWED, SKIP, STATUS_LABEL, Entry,
                      UnsupportedGameError)
from ..project import Project
from ..providers import PROVIDER_NAMES, ProviderFatalError, make_provider, provider_is_remote
from .models import EntryModel, EntryProxy
from .panels import EditPanel, GlossaryPanel, StylePanel
from .settings_dialog import SettingsDialog
from .workers import Worker


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig | None = None):
        super().__init__()
        self.cfg = cfg or AppConfig()
        self.project: Project | None = None
        self.worker: Worker | None = None
        self._remote_ok: set[str] = set()      # nhà cung cấp bên ngoài đã được người dùng cho phép gửi văn bản (trong phiên)
        self.setWindowTitle("ViTrans — Dịch game sang tiếng Việt")
        self.resize(1400, 820)
        self._build_ui()
        self._build_actions()
        self._sync_enabled()

    # ---------------- dựng giao diện ----------------------------------------------------------
    def _build_ui(self) -> None:
        self.model = EntryModel(self._on_edit)
        self.proxy = EntryProxy()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, w in enumerate((46, 100, 80, 90, 300, 300, 80)):
            self.table.setColumnWidth(i, w)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        hh.setStretchLastSection(False)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm trong bản gốc / bản dịch / người nói…")
        self.f_status = QComboBox()
        self.f_status.addItem("Mọi trạng thái", "")
        for k in (PENDING, MACHINE, REVIEWED, ERROR, SKIP):
            self.f_status.addItem(STATUS_LABEL[k], k)
        self.f_status.addItem("Có cảnh báo", "warn")
        self.f_kind = QComboBox()
        self.f_kind.addItem("Mọi loại", "")
        for k, v in KIND_LABEL.items():
            self.f_kind.addItem(v, k)
        for w in (self.search,):
            w.textChanged.connect(self._apply_filters)
        for c in (self.f_status, self.f_kind):
            c.currentIndexChanged.connect(self._apply_filters)
        fbar = QHBoxLayout()
        fbar.addWidget(self.search, 1)
        fbar.addWidget(self.f_status)
        fbar.addWidget(self.f_kind)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(fbar)
        ll.addWidget(self.table)

        self.edit = EditPanel(self._preview_opt)
        self.table.doubleClicked.connect(lambda *_: self.edit.trans.setFocus())   # sửa bản dịch ở khung bên phải
        self.glossary = GlossaryPanel()
        self.style_panel = StylePanel()
        tabs = QTabWidget()
        tabs.addTab(self.edit, "Chỉnh sửa")
        tabs.addTab(self.glossary, "Từ điển")
        tabs.addTab(self.style_panel, "Phong cách")
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(tabs)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([900, 480])
        self.setCentralWidget(split)

        self.edit.save_requested.connect(self._save_entry)
        self.edit.retranslate_requested.connect(self._retranslate_one)
        self.edit.skip_toggled.connect(self._toggle_skip)
        self.glossary.changed.connect(self._save_glossary)
        self.glossary.suggest_requested.connect(self._suggest_glossary)
        self.style_panel.changed.connect(self._save_style)

        self.status_label = QLabel("Chưa mở game")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.setVisible(False)
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)

    def _build_actions(self) -> None:
        tb = QToolBar("Chính")
        tb.setMovable(False)
        self.addToolBar(tb)

        def act(text, slot, shortcut=None, tip=""):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setToolTip(tip or text)
            a.triggered.connect(slot)
            tb.addAction(a)
            return a

        self.a_open = act("📂 Mở game", self.choose_game, "Ctrl+O", "Chọn thư mục game")
        self.a_scan = act("🔄 Quét lại", self.start_scan, "F5")
        tb.addSeparator()
        self.a_translate = act("🌐 Dịch phần chờ", self.translate_pending, "Ctrl+T",
                               "Dịch mọi câu đang chờ/lỗi (câu trùng chỉ dịch một lần)")
        self.a_translate_sel = act("Dịch mục chọn", self.translate_selected, "Ctrl+Shift+T")
        self.a_stop = act("⏹ Dừng", self.stop_worker, "Esc")
        tb.addSeparator()
        self.a_approve = act("✔ Duyệt mục chọn", self.approve_selected, "Ctrl+D",
                             "Đánh dấu các dòng đang chọn là đã duyệt")
        tb.addSeparator()
        self.a_apply = act("✅ Áp dụng vào game", self.apply_to_game, None,
                           "Ghi bản dịch vào game (tự sao lưu bản gốc)")
        self.a_export = act("📦 Xuất bản vá", self.export_patch, None, "Xuất riêng các tệp đã dịch để chia sẻ")
        self.a_restore = act("↩ Khôi phục gốc", self.restore_game)
        tb.addSeparator()
        self.engine_combo = QComboBox()
        for a in adapters.ADAPTERS:
            self.engine_combo.addItem(a.label, a.id)
        self.engine_combo.setToolTip("Loại game (tự nhận diện; đổi nếu nhận sai)")
        self.engine_combo.activated.connect(self._engine_changed)
        tb.addWidget(self.engine_combo)
        tb.addSeparator()
        self.a_settings = act("⚙ Cài đặt", self.open_settings, "Ctrl+,")

    def _sync_enabled(self) -> None:
        has = self.project is not None
        busy = self.worker is not None and self.worker.isRunning()
        for a in (self.a_scan, self.a_translate, self.a_translate_sel, self.a_approve, self.a_apply,
                  self.a_export, self.a_restore):
            a.setEnabled(has and not busy)
        self.edit.set_busy(busy)
        self.a_open.setEnabled(not busy)
        self.a_stop.setEnabled(busy)
        self.engine_combo.setEnabled(has and not busy)
        self.a_settings.setEnabled(not busy)

    # ---------------- mở / quét ----------------------------------------------------------------
    def choose_game(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục game", self.cfg["last_game"] or str(Path.home()))
        if path:
            self.open_project(path)

    def open_project(self, path: str, engine: str | None = None) -> bool:
        try:
            proj = Project(path, engine=engine)
        except UnsupportedGameError as ex:
            QMessageBox.warning(self, "Không hỗ trợ", str(ex))
            return False
        except (OSError, ValueError, KeyError) as ex:
            QMessageBox.critical(self, "Lỗi", f"Không mở được thư mục: {ex}")
            return False
        if self.project:
            self.project.close()
        self.project = proj
        self.cfg["last_game"] = str(proj.root)
        self.cfg.save()
        self.setWindowTitle(f"ViTrans — {proj.root.name}")
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(proj.adapter.id)))
        self.glossary.set_terms(proj.glossary)
        self.style_panel.set_style(proj.style)
        self.model.set_entries(proj.entries)
        self._update_status()
        self.start_scan()
        return True

    def _engine_changed(self) -> None:
        if self.project:
            self.open_project(str(self.project.root), self.engine_combo.currentData())

    def start_scan(self) -> None:
        if not self.project or self._busy():
            return
        proj = self.project

        def job(w: Worker):
            return proj.scan()

        self._run(job, "Đang quét game…", self._scan_done)

    def _scan_done(self, info: dict) -> None:
        self.model.set_entries(self.project.entries)
        self._update_status(f"Quét xong: {info['added']} mới, {info['kept']} giữ nguyên bản dịch")

    # ---------------- luồng nền ------------------------------------------------------------------
    def _busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _run(self, fn, message: str, on_done, indeterminate: bool = True) -> None:
        w = Worker(fn, self)
        self.worker = w
        self.progress.setVisible(True)
        self.progress.setRange(0, 0 if indeterminate else 100)
        self.status_label.setText(message)
        w.progress.connect(self._on_progress)
        w.updated.connect(self.model.refresh_keys)
        w.done.connect(lambda r: self._finish(w, on_done, r))
        w.failed.connect(lambda m: self._fail(w, m))
        w.start()
        self._sync_enabled()

    def _finish(self, w: Worker, on_done, result) -> None:
        self._end(w)
        on_done(result)

    def _fail(self, w: Worker, msg: str) -> None:
        self._end(w)
        self._update_status()
        QMessageBox.critical(self, "Lỗi", msg)

    def _end(self, w: Worker) -> None:
        w.wait()
        self.progress.setVisible(False)
        self.worker = None
        self._sync_enabled()

    def stop_worker(self) -> None:
        if self._busy():
            self.worker.cancel.set()
            self.status_label.setText("Đang dừng… (xong lô hiện tại)")

    def _on_progress(self, done: int, total: int, msg: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.status_label.setText(f"{msg}")

    # ---------------- dịch -----------------------------------------------------------------------------
    def _commit_side_panels(self) -> None:
        self.edit.commit_pending()
        self._save_glossary()
        self._save_style()

    def translate_pending(self) -> None:
        self._start_translate(None, False, "Đang dịch…")

    def translate_selected(self) -> None:
        keys = self._selected_keys()
        if not keys:
            QMessageBox.information(self, "Dịch", "Hãy chọn một hoặc nhiều dòng trước.")
            return
        self._start_translate(set(keys), True, "Đang dịch mục chọn…")

    def _retranslate_one(self, entry: Entry) -> None:
        self._start_translate({entry.key}, True, "Đang dịch lại…")

    def _start_translate(self, only_keys, force: bool, message: str) -> None:
        if not self.project or self._busy():
            return
        self._commit_side_panels()
        proj, cfg = self.project, self.cfg
        try:
            make_provider(cfg)                      # kiểm tra cấu hình (khóa API, địa chỉ) trước khi chạy
        except ProviderFatalError as ex:
            if QMessageBox.question(self, "Chưa cấu hình dịch", f"{ex}\n\nMở Cài đặt ngay?"
                                    ) == QMessageBox.StandardButton.Yes:
                self.open_settings()
            return
        n, chars = proj.estimate(only_keys, force)
        if n == 0:
            QMessageBox.information(self, "Dịch", "Không có câu nào cần dịch.")
            return
        if force and only_keys:
            by_key = {e.key: e for e in proj.entries}
            if any(by_key[k].status == REVIEWED for k in only_keys if k in by_key):
                if QMessageBox.question(self, "Ghi đè", "Có câu đã duyệt trong số được chọn. Dịch lại sẽ ghi đè. Tiếp tục?"
                                        ) != QMessageBox.StandardButton.Yes:
                    return
        if provider_is_remote(cfg) and cfg["provider"] not in self._remote_ok:
            name = PROVIDER_NAMES.get(cfg["provider"], cfg["provider"])
            if QMessageBox.question(
                    self, "Gửi văn bản ra ngoài?",
                    f"Sẽ gửi khoảng {n} câu (~{chars:,} ký tự) văn bản của game tới {name} để dịch.\n"
                    "Chỉ tiếp tục nếu bạn đồng ý để dịch vụ đó nhận nội dung này (có thể tính phí theo dịch vụ)."
            ) != QMessageBox.StandardButton.Yes:
                return
            self._remote_ok.add(cfg["provider"])

        def job(w: Worker):
            return proj.translate(cfg, only_keys=only_keys, force=force, progress=w.progress.emit,
                                  cancel=w.cancel, on_update=w.updated.emit)

        self._run(job, message, self._translate_done, indeterminate=False)

    def _translate_done(self, res) -> None:
        self._update_status()
        self.edit.load(self.edit.entry)
        msg = f"Dịch mới {res.translated} · dùng lại {res.reused} · lỗi {res.failed}"
        if res.cancelled:
            msg = "Đã dừng. " + msg
        self.status_label.setText(msg)
        if res.failed:
            QMessageBox.information(self, "Có câu lỗi",
                                    f"{res.failed} câu chưa dịch được (thường do mất mã định dạng). "
                                    "Lọc theo trạng thái 'Lỗi' để dịch lại hoặc sửa tay.")

    # ---------------- chỉnh sửa tay ----------------------------------------------------------------------
    def _on_edit(self, entry: Entry, text: str) -> None:
        self._save_entry(entry, text, refresh=False)

    def _save_entry(self, entry: Entry, text: str, refresh: bool = True) -> None:
        if not self.project:
            return
        text = text.strip()
        status = REVIEWED if text else PENDING
        self.project.set_translation(entry, text, status)
        if refresh:
            self.model.refresh_keys([entry.key])
        self._update_status()

    def _toggle_skip(self, entry: Entry) -> None:
        new = PENDING if entry.status == SKIP else SKIP
        entry.status = new
        self.project.store.update_entries([entry])
        self.model.refresh_keys([entry.key])
        self.edit.load(entry)
        self._update_status()

    def approve_selected(self) -> None:
        ents = [e for e in self._selected_entries() if e.translation.strip() and e.status in (MACHINE, ERROR)]
        for e in ents:
            e.status, e.warn = REVIEWED, ""
        if ents:
            self.project.store.update_entries(ents)
            self.model.refresh_keys([e.key for e in ents])
            self._update_status()

    def _selected_entries(self) -> list[Entry]:
        rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        return [self.model.entries[r] for r in sorted(rows)]

    def _selected_keys(self) -> list[str]:
        return [e.key for e in self._selected_entries()]

    def _on_selection(self) -> None:
        ents = self._selected_entries()
        self.edit.load(ents[0] if len(ents) == 1 else None)

    def _apply_filters(self) -> None:
        self.proxy.set_filters(self.f_status.currentData() or "", self.f_kind.currentData() or "", self.search.text())

    def _preview_opt(self, entry: Entry | None):
        if entry is None:
            return int(self.cfg["max_lines"])
        if self.project is None:
            return None
        return self.project.adapter.preview_width(entry, self.project.patch_options(self.cfg))

    # ---------------- từ điển / phong cách -----------------------------------------------------------------
    def _save_glossary(self) -> None:
        if self.project:
            self.project.save_glossary(self.glossary.terms())

    def _save_style(self) -> None:
        if self.project:
            self.project.save_style(self.style_panel.style())

    def _suggest_glossary(self) -> None:
        if not self.project:
            return
        sug = self.project.suggest_glossary()
        if not sug:
            QMessageBox.information(self, "Gợi ý", "Không có tên riêng mới để thêm.")
            return
        self.glossary.add_terms(sug)

    # ---------------- ghi vào game ---------------------------------------------------------------------------------
    def apply_to_game(self) -> None:
        if not self.project or self._busy():
            return
        self._commit_side_panels()
        proj = self.project
        usable = sum(1 for e in proj.entries if e.usable)
        warned = sum(1 for e in proj.entries if e.usable and e.warn)
        if not usable:
            QMessageBox.information(self, "Áp dụng", "Chưa có bản dịch nào để ghi vào game.")
            return
        if QMessageBox.question(
                self, "Áp dụng vào game",
                f"Ghi {usable} câu đã dịch vào thư mục game?"
                + (f"\n({warned} câu đang có cảnh báo chưa xử lý.)" if warned else "")
                + "\nBản gốc được sao lưu trong '.vitrans_backup' và có thể khôi phục bất cứ lúc nào."
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            files = proj.apply(self.cfg)
        except (OSError, ValueError) as ex:
            QMessageBox.critical(self, "Lỗi ghi tệp", str(ex))
            return
        self.status_label.setText(f"Đã ghi {len(files)} tệp vào game")
        QMessageBox.information(self, "Xong", f"Đã ghi {len(files)} tệp. Mở game lên để kiểm tra.")

    def export_patch(self) -> None:
        if not self.project:
            return
        self._commit_side_panels()
        out = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất bản vá", str(Path.home()))
        if not out:
            return
        try:
            files = self.project.export(self.cfg, out)
        except (OSError, ValueError) as ex:
            QMessageBox.critical(self, "Lỗi", str(ex))
            return
        QMessageBox.information(self, "Xong", f"Đã xuất {len(files)} tệp vào:\n{out}\n\nChỉ gồm các tệp bản vá, "
                                              "không chứa toàn bộ game.")

    def restore_game(self) -> None:
        if not self.project:
            return
        if not self.project.fs.has_backup():
            QMessageBox.information(self, "Khôi phục", "Chưa có bản sao lưu nào (chưa áp dụng vào game).")
            return
        if QMessageBox.question(self, "Khôi phục", "Trả game về bản gốc tiếng Anh?") != QMessageBox.StandardButton.Yes:
            return
        n = self.project.restore()
        skipped = self.project.fs.restore_skipped
        msg = f"Đã khôi phục {n} tệp gốc"
        if skipped:
            msg += f"; giữ nguyên {len(skipped)} tệp vì game đã cập nhật sau khi vá"
        self.status_label.setText(msg)

    def open_settings(self) -> None:
        if SettingsDialog(self.cfg, self).exec():
            self.edit.load(self.edit.entry)

    # ---------------- trạng thái ------------------------------------------------------------------------------------------
    def _update_status(self, prefix: str = "") -> None:
        if not self.project:
            return
        counts: dict[str, int] = {}
        for e in self.project.entries:
            counts[e.status] = counts.get(e.status, 0) + 1
        total = len(self.project.entries)
        done = counts.get(MACHINE, 0) + counts.get(REVIEWED, 0)
        text = (f"{self.project.adapter.label} · {total} câu · đã dịch {done} · đã duyệt {counts.get(REVIEWED, 0)} · "
                f"chờ {counts.get(PENDING, 0)} · lỗi {counts.get(ERROR, 0)}")
        self.status_label.setText(f"{prefix} — {text}" if prefix else text)

    def closeEvent(self, ev) -> None:
        if self._busy():
            if QMessageBox.question(self, "Thoát", "Đang chạy tác vụ. Dừng và thoát?") != QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
            self.worker.cancel.set()
            self.worker.wait(5000)
        self.edit.commit_pending()
        self._save_glossary()
        self._save_style()
        if self.project:
            self.project.close()
        ev.accept()
