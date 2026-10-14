import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from vitrans.config import AppConfig
from vitrans.models import MACHINE, REVIEWED, SKIP
from vitrans.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait(win, app, timeout=15000):
    import time
    t = time.time()
    while win.worker is not None and time.time() - t < timeout / 1000:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert win.worker is None, "worker chưa kết thúc"


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    # tự trả lời "Yes" cho mọi hộp thoại hỏi, bỏ qua hộp thoại thông tin
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    cfg = AppConfig(path=tmp_path / "cfg.json")
    cfg["provider"] = "echo"
    w = MainWindow(cfg)
    w.show()
    yield w
    w.close()


def test_full_flow_rpg(win, app, rpg_game):
    assert win.open_project(str(rpg_game))
    wait(win, app)
    assert win.model.rowCount() >= 8
    assert win.proxy.rowCount() == win.model.rowCount()

    win.translate_pending()
    wait(win, app)
    assert all(e.status == MACHINE for e in win.model.entries if e.source.strip())

    # chỉnh tay một dòng -> trạng thái "đã duyệt", lưu vào DB
    row = next(i for i, e in enumerate(win.model.entries) if e.source == "Rusty Key")
    idx = win.model.index(row, 5)
    win.model.setData(idx, "Chìa khóa gỉ", Qt.ItemDataRole.EditRole)
    assert win.model.entries[row].status == REVIEWED
    assert next(e for e in win.project.store.all_entries() if e.source == "Rusty Key").translation == "Chìa khóa gỉ"

    # bộ lọc
    win.f_status.setCurrentIndex(win.f_status.findData(REVIEWED))
    assert win.proxy.rowCount() == 1
    win.f_status.setCurrentIndex(0)
    win.search.setText("cellar")
    assert 0 < win.proxy.rowCount() < win.model.rowCount()
    win.search.setText("")

    # chọn một dòng -> panel chỉnh sửa hiện bản xem trước ngắt dòng
    win.table.selectRow(0)
    app.processEvents()
    win.table.selectRow(win.proxy.mapFromSource(win.model.index(
        next(i for i, e in enumerate(win.model.entries) if e.kind == "dialogue"), 0)).row())
    app.processEvents()
    assert win.edit.entry is not None and win.edit.preview.toPlainText()

    # bỏ qua một câu
    ent = win.edit.entry
    win._toggle_skip(ent)
    assert ent.status == SKIP

    # áp dụng vào game rồi khôi phục
    win.apply_to_game()
    mp = json.loads((rpg_game / "www/data/Map001.json").read_text("utf-8"))
    assert mp["displayName"].startswith("(VI)")
    win.restore_game()
    assert json.loads((rpg_game / "www/data/Map001.json").read_text("utf-8"))["displayName"] == "Hallway"


def test_stop_and_reopen_keeps_translations(win, app, rpg_game):
    win.open_project(str(rpg_game))
    wait(win, app)
    win.translate_pending()
    wait(win, app)
    win.project.close()
    win.project = None
    win.open_project(str(rpg_game))
    wait(win, app)
    assert any(e.status == MACHINE for e in win.model.entries)


def test_renpy_via_ui(win, app, renpy_game, tmp_path):
    assert win.open_project(str(renpy_game))
    wait(win, app)
    win.translate_pending()
    wait(win, app)
    win.apply_to_game()
    assert (renpy_game / "game/tl/vietnamese/vitrans_strings.rpy").exists()
    win.restore_game()
    assert not (renpy_game / "game/tl").exists()


def test_unsupported_folder(win, app, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert win.open_project(str(empty)) is False


# ---------------- sửa đổi sau rà soát ----------------
from PyQt6.QtTest import QTest


def _select_dialogue(win, app):
    row = next(i for i, e in enumerate(win.model.entries) if e.kind == "dialogue")
    win.table.selectRow(win.proxy.mapFromSource(win.model.index(row, 0)).row())
    app.processEvents()
    return win.model.entries[row]


def test_ctrl_enter_saves_and_approves(win, app, rpg_game):
    win.open_project(str(rpg_game))
    wait(win, app)
    win.translate_pending()
    wait(win, app)
    ent = _select_dialogue(win, app)
    win.edit.trans.setPlainText("Bạn có nghe thấy không?")
    win.edit.trans.setFocus()
    win.activateWindow()
    app.processEvents()
    QTest.keyClick(win.edit.trans, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert ent.status == REVIEWED and ent.translation == "Bạn có nghe thấy không?"


def test_apply_has_no_global_shortcut(win):
    assert win.a_apply.shortcut().isEmpty()        # Ctrl+Enter không được kích hoạt "Áp dụng vào game"


def test_translation_cell_is_not_editable_in_table(win, app, rpg_game):
    win.open_project(str(rpg_game))
    wait(win, app)
    flags = win.model.flags(win.model.index(0, 5))
    assert not (flags & Qt.ItemFlag.ItemIsEditable)


def test_edit_panel_locked_while_busy(win, app, rpg_game):
    win.open_project(str(rpg_game))
    wait(win, app)
    _select_dialogue(win, app)
    assert win.edit.isEnabled()
    win.edit.set_busy(True)
    assert not win.edit.isEnabled()
    win.edit.trans.setPlainText("sửa dở")
    win.edit.commit_pending()                       # đang bận: không được ghi
    assert win.edit.entry.translation == ""
    win.edit.set_busy(False)
    assert win.edit.isEnabled()


def test_missing_api_key_blocks_translation(win, app, rpg_game, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    win.cfg["provider"], win.cfg["anthropic_key"] = "anthropic", ""
    opened = []
    monkeypatch.setattr(win, "open_settings", lambda: opened.append(1))
    win.open_project(str(rpg_game))
    wait(win, app)
    win.translate_pending()
    assert win.worker is None and opened == [1]     # không chạy, mà mời mở Cài đặt
    assert all(e.status == "pending" for e in win.model.entries)


def test_remote_provider_requires_consent(win, app, rpg_game, monkeypatch):
    win.cfg["provider"] = "google"                  # dịch vụ bên ngoài: phải hỏi trước, không gọi mạng khi từ chối
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win.open_project(str(rpg_game))
    wait(win, app)
    win.translate_pending()
    assert win.worker is None
    assert all(e.status == "pending" for e in win.model.entries)
    assert "google" not in win._remote_ok


def test_style_source_language_roundtrip(win, app, rpg_game):
    win.open_project(str(rpg_game))
    wait(win, app)
    win.style_panel.src_lang.setText("Japanese")
    assert win.project.style.source_lang == "Japanese"
