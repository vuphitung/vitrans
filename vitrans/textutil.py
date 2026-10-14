"""Làm sạch văn bản do AI/người dùng tạo ra trước khi ghi vào tệp game."""
from __future__ import annotations

import re
import unicodedata

# Ký tự định dạng vô hình (zero-width, điều khiển chiều chữ kiểu "Trojan Source"), soft-hyphen, BOM
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HEX4 = re.compile(r"[0-9a-fA-F]{4}")
_RPY_KEEP = set('\\"\' nt%')


def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s)          # dấu tiếng Việt dựng sẵn, tránh lỗi font với dấu rời
    s = _INVISIBLE.sub("", s)
    s = _CONTROL.sub("", s)
    return s.replace("\r\n", "\n").replace("\r", "\n")


def rpy_literal(s: str) -> str:
    """Biến văn bản thành nội dung hợp lệ bên trong chuỗi "..." của Ren'Py.

    Giữ lại các cặp escape hợp lệ đã có (\\" \\\\ \\n ...), escape dấu " trần, backslash lẻ ở cuối
    và xuống dòng thật. Idempotent: chạy lại trên kết quả không đổi gì.
    """
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            nxt = s[i + 1] if i + 1 < n else ""
            if nxt == "u" and _HEX4.fullmatch(s[i + 2:i + 6]):
                out.append(s[i:i + 6])
                i += 6
            elif nxt and nxt in _RPY_KEEP:
                out.append(c + nxt)
                i += 2
            else:                                   # backslash lẻ / escape lạ: hiển thị nguyên dạng, không phá cú pháp
                out.append("\\\\")
                i += 1
        elif c == '"':
            out.append('\\"')
            i += 1
        elif c == "\n":
            out.append("\\n")
            i += 1
        elif c == "\r":
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)
