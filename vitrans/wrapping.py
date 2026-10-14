"""Ngắt dòng theo độ rộng hiển thị, bỏ qua mã điều khiển RPG Maker khi đo độ dài."""
from __future__ import annotations

import re

_CODE = re.compile(r"\\[A-Za-z]+\[[^\]\n]*\]|\\[.!|^<>{}$]|\\[A-Za-z](?![A-Za-z])")


def visible_len(s: str) -> int:
    return len(_CODE.sub("", s))


def wrap(text: str, width: int) -> list[str]:
    width = max(10, int(width))
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        cur_len = visible_len(cur)
        for w in words[1:]:
            wl = visible_len(w)
            if cur_len + 1 + wl > width:
                lines.append(cur)
                cur, cur_len = w, wl
            else:
                cur += " " + w
                cur_len += 1 + wl
        lines.append(cur)
    while lines and lines[-1] == "":
        lines.pop()
    return lines
