from __future__ import annotations

from dataclasses import asdict, dataclass, field

PENDING = "pending"
MACHINE = "machine"
REVIEWED = "reviewed"
ERROR = "error"
SKIP = "skip"

STATUS_LABEL = {
    PENDING: "Chờ dịch",
    MACHINE: "Máy dịch",
    REVIEWED: "Đã duyệt",
    ERROR: "Lỗi",
    SKIP: "Bỏ qua",
}

KIND_LABEL = {
    "dialogue": "Hội thoại",
    "choice": "Lựa chọn",
    "name": "Tên",
    "desc": "Mô tả",
    "ui": "Giao diện",
    "scroll": "Cuộn chữ",
    "speaker": "Người nói",
    "text": "Văn bản",
}

USABLE = (MACHINE, REVIEWED)


@dataclass
class Entry:
    key: str
    order: int
    file: str
    kind: str
    source: str
    speaker: str = ""
    translation: str = ""
    status: str = PENDING
    warn: str = ""
    locator: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.status in USABLE and bool(self.translation.strip())


@dataclass
class Term:
    src: str
    vi: str
    note: str = ""


@dataclass
class Style:
    source_lang: str = "English"
    genre: str = "Game indie kinh dị"
    tone: str = "U ám, căng thẳng, câu ngắn gọn"
    pronouns: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Style":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class UnsupportedGameError(Exception):
    """Thư mục không phải game được hỗ trợ (hoặc không đọc được dữ liệu chữ)."""


class PatchError(ValueError):
    """Không thể tạo/ghi bản vá một cách an toàn (người dùng cần xử lý rồi thử lại)."""
