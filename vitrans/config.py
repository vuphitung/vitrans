"""Cấu hình ứng dụng (nhà cung cấp dịch, khóa API, độ rộng dòng...)."""
from __future__ import annotations

import json
import os
import sys

from .paths import data_dir

DEFAULTS = {
    "provider": "anthropic",          # anthropic | openai | google | echo
    "anthropic_model": "claude-sonnet-5-5",
    "anthropic_key": "",
    "openai_base_url": "http://localhost:11434/v1",
    "openai_model": "qwen2.5:7b",
    "openai_key": "",
    "concurrency": 2,
    "batch_chars": 3500,
    "batch_items": 25,
    "context_lines": 3,
    "retries": 1,
    "wrap_width": 54,
    "wrap_width_face": 42,
    "max_lines": 4,
    "font_path": "",
    "renpy_force_language": True,
    "last_game": "",
}


class AppConfig:
    def __init__(self, path=None):
        self.path = path or (data_dir() / "config.json")
        self.data = dict(DEFAULTS)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def __getitem__(self, k):
        return self.data[k]

    def get(self, k, default=None):
        return self.data.get(k, default)

    def __setitem__(self, k, v):
        if k in DEFAULTS:
            self.data[k] = v

    def update(self, d: dict) -> None:
        for k, v in d.items():
            self[k] = v

    def save(self) -> None:
        """Ghi nguyên tử; tệp được tạo thẳng với quyền 600 (không có khoảng hở khi khóa API còn đọc được)."""
        tmp = str(self.path) + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            if sys.platform != "win32":
                os.fchmod(fd, 0o600)          # phòng trường hợp tệp tạm cũ còn sót với quyền rộng hơn
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        os.replace(tmp, self.path)

    # Khóa API: giá trị nhập trong Cài đặt được ưu tiên, nếu trống thì lấy từ biến môi trường
    def anthropic_key(self) -> str:
        return self.data["anthropic_key"] or os.environ.get("ANTHROPIC_API_KEY", "")

    def openai_key(self) -> str:
        return self.data["openai_key"] or os.environ.get("OPENAI_API_KEY", "")
