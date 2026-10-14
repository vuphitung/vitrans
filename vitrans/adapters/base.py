from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..gamefs import GameFS
from ..models import Entry
from ..protect import Protector


@dataclass
class PatchOptions:
    wrap_width: int = 54
    wrap_width_face: int = 42
    max_lines: int = 4
    font_path: str = ""
    renpy_force_language: bool = True      # Ren'Py: ép ngôn ngữ mọi lần mở game (config.language) thay vì chỉ lần đầu


class Adapter(ABC):
    id = ""
    label = ""
    patterns: list[str] = []

    @classmethod
    @abstractmethod
    def detect(cls, fs: GameFS) -> int:
        """Điểm tin cậy 0..100 rằng thư mục là loại game này."""

    @abstractmethod
    def extract(self, fs: GameFS) -> list[Entry]:
        ...

    @abstractmethod
    def build_patch(self, fs: GameFS, entries: list[Entry], opts: PatchOptions) -> dict[str, bytes]:
        """Trả về {đường dẫn tương đối: nội dung} cho các tệp cần ghi."""

    def protector(self) -> Protector:
        if not hasattr(self, "_prot"):
            self._prot = Protector(self.patterns)
        return self._prot

    def validate(self, text: str) -> list[str]:
        """Lỗi cú pháp riêng của engine trong bản dịch (trả về danh sách lý do từ chối)."""
        return []

    def finalize(self, text: str) -> str:
        return text

    def preview_width(self, entry: Entry, opts: PatchOptions) -> int | None:
        return None
