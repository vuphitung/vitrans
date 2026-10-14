from __future__ import annotations

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..config import AppConfig
from ..fonts import find_system_fonts, license_warning, supports_vietnamese, validate_font_file
from ..models import Style
from ..providers import BatchItem, ProviderError, make_provider

PROVIDERS = [
    ("anthropic", "Claude (Anthropic) — chất lượng cao nhất, cần khóa API"),
    ("openai", "OpenAI-tương thích / Ollama (chạy máy mình, miễn phí)"),
    ("google", "Google Dịch (miễn phí, chất lượng thấp, không có ngữ cảnh)"),
    ("echo", "Chế độ thử (không dịch thật, chỉ thêm [VI] để kiểm tra quy trình)"),
]


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Cài đặt")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.provider = QComboBox()
        for k, label in PROVIDERS:
            self.provider.addItem(label, k)
        self.provider.setCurrentIndex(max(0, [k for k, _ in PROVIDERS].index(cfg["provider"])))
        self.a_model = QLineEdit(cfg["anthropic_model"])
        self.a_key = QLineEdit(cfg["anthropic_key"])
        self.a_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.a_key.setPlaceholderText("Hoặc đặt biến môi trường ANTHROPIC_API_KEY")
        self.o_url = QLineEdit(cfg["openai_base_url"])
        self.o_model = QLineEdit(cfg["openai_model"])
        self.o_key = QLineEdit(cfg["openai_key"])
        self.o_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.concurrency = QSpinBox(minimum=1, maximum=8, value=int(cfg["concurrency"]))
        self.wrap = QSpinBox(minimum=15, maximum=200, value=int(cfg["wrap_width"]))
        self.wrap_face = QSpinBox(minimum=15, maximum=200, value=int(cfg["wrap_width_face"]))
        self.max_lines = QSpinBox(minimum=1, maximum=10, value=int(cfg["max_lines"]))
        self.font = QLineEdit(cfg["font_path"])
        self.force_lang = QCheckBox("Ren'Py: luôn dùng tiếng Việt mỗi lần mở game (khuyên dùng)")
        self.force_lang.setChecked(bool(cfg["renpy_force_language"]))
        self.force_lang.setToolTip("Bỏ chọn = chỉ đặt tiếng Việt làm mặc định ở lần chạy ĐẦU TIÊN của game; "
                                   "nếu bạn đã chạy game bản gốc trước đó thì sẽ không có tác dụng.")
        form.addRow("Nhà cung cấp dịch", self.provider)
        form.addRow("Claude: model", self.a_model)
        form.addRow("Claude: khóa API", self.a_key)
        form.addRow("OpenAI/Ollama: địa chỉ", self.o_url)
        form.addRow("OpenAI/Ollama: model", self.o_model)
        form.addRow("OpenAI/Ollama: khóa (nếu có)", self.o_key)
        form.addRow("Số luồng dịch song song", self.concurrency)
        form.addRow("RPG Maker: ký tự/dòng (không ảnh mặt)", self.wrap)
        form.addRow("RPG Maker: ký tự/dòng (có ảnh mặt)", self.wrap_face)
        form.addRow("RPG Maker: số dòng tối đa/trang", self.max_lines)
        frow = QHBoxLayout()
        frow.addWidget(self.font)
        b1, b2 = QPushButton("Chọn…"), QPushButton("Tìm font có dấu")
        frow.addWidget(b1)
        frow.addWidget(b2)
        w = QWidget()
        w.setLayout(frow)
        frow.setContentsMargins(0, 0, 0, 0)
        form.addRow("Font tiếng Việt (tùy chọn)", w)
        form.addRow("", self.force_lang)
        lay.addLayout(form)
        self.font_note = QLabel("Chỉ cần khi game hiện ô vuông thay vì chữ có dấu. Dùng font mở (Noto Sans, Be Vietnam Pro...).")
        self.font_note.setWordWrap(True)
        lay.addWidget(self.font_note)
        test = QPushButton("Thử kết nối nhà cung cấp")
        lay.addWidget(test)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        lay.addWidget(bb)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        b1.clicked.connect(self._pick_font)
        b2.clicked.connect(self._find_fonts)
        test.clicked.connect(self._test)

    def _collect(self) -> dict:
        return {
            "provider": self.provider.currentData(), "anthropic_model": self.a_model.text().strip(),
            "anthropic_key": self.a_key.text().strip(), "openai_base_url": self.o_url.text().strip(),
            "openai_model": self.o_model.text().strip(), "openai_key": self.o_key.text().strip(),
            "concurrency": self.concurrency.value(), "wrap_width": self.wrap.value(),
            "wrap_width_face": self.wrap_face.value(), "max_lines": self.max_lines.value(),
            "font_path": self.font.text().strip(),
            "renpy_force_language": self.force_lang.isChecked(),
        }

    def _ok(self) -> None:
        font = self.font.text().strip()
        if font:
            try:
                validate_font_file(font)
            except ValueError as ex:
                QMessageBox.warning(self, "Font", str(ex))
                return
            ok = supports_vietnamese(font)
            if ok is False:
                QMessageBox.warning(self, "Font", "Font này thiếu một số ký tự tiếng Việt. Hãy chọn font khác.")
                return
            warn = license_warning(font)
            if warn:
                QMessageBox.information(self, "Giấy phép font", warn)
        self.cfg.update(self._collect())
        self.cfg.save()
        self.accept()

    def _pick_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn font", "", "Font (*.ttf *.otf)")
        if path:
            self.font.setText(path)

    def _find_fonts(self) -> None:
        self.font_note.setText("Đang tìm font hỗ trợ tiếng Việt trong hệ thống…")
        self.repaint()
        fonts = find_system_fonts()
        if not fonts:
            self.font_note.setText("Không tìm thấy font phù hợp (hoặc chưa cài fontTools: pip install fonttools).")
            return
        self.font_note.setText(f"Tìm thấy {len(fonts)} font. Đã chọn: {fonts[0]}")
        self.font.setText(fonts[0])

    def _test(self) -> None:
        tmp = AppConfig(path=self.cfg.path)
        tmp.update(self._collect())
        try:
            prov = make_provider(tmp)
            if hasattr(prov, "timeout"):            # chạy ở luồng giao diện: không để treo lâu khi mất mạng
                prov.timeout, prov.max_retries = 20, 0
            out = prov.translate_batch([BatchItem("1", "Hello, can you hear me?")], Style(), [])
        except ProviderError as ex:
            QMessageBox.warning(self, "Kết nối thất bại", str(ex))
            return
        QMessageBox.information(self, "Kết nối OK", f"Kết quả thử: {out.get('1', '(trống)')}")
