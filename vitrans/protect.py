"""Che mã điều khiển/biến trước khi dịch rồi trả lại sau, kiểm tra không bị mất hay bị chèn thêm.

Mọi vế lặp đều có giới hạn độ dài để chuỗi độc hại trong game không gây regex chạy chậm (ReDoS).
"""
from __future__ import annotations

import re

COMMON = [r"%\d+", r"%\([A-Za-z_]\w{0,40}\)[sdif]"]

RPGMAKER = [
    r"\\\\",
    r"\\[A-Za-z]{1,20}\[[^\]\n]{0,40}\]",
    r"\\[.!|^<>{}$]",
    r"\\[A-Za-z](?![A-Za-z])",
    r"<[^<>\n]{1,40}>",
] + COMMON

RENPY = [
    r"\{\{",
    r"\[\[",
    r"%%",
    r"%[-#0-9.]{0,5}[A-Za-z]",
    r"\{[^{}\n]{0,200}\}",
    r"\[[^\[\]\n]{0,200}\]",
    r"%\([A-Za-z_]\w{0,40}\)[sdif]",
]

GENERIC = [r"\{[^{}\n]{0,100}\}", r"<[^<>\n]{1,40}>", r"\\[nrt]"] + COMMON

_TOKEN = re.compile(r"⟦\s*(\d+)\s*⟧")


class Protector:
    def __init__(self, patterns: list[str]):
        self._re = re.compile("|".join(f"(?:{p})" for p in patterns)) if patterns else None

    def mask(self, text: str) -> tuple[str, list[str]]:
        tokens: list[str] = []
        if not self._re:
            return text, tokens

        def sub(m: re.Match) -> str:
            tokens.append(m.group(0))
            return f"⟦{len(tokens) - 1}⟧"

        return self._re.sub(sub, text), tokens

    def tokens_of(self, text: str) -> list[str]:
        """Các mã điều khiển đang có trong một văn bản thật (đã trả mã)."""
        return [m.group(0) for m in self._re.finditer(text)] if self._re else []

    def unmask(self, text: str, tokens: list[str]) -> str:
        def sub(m: re.Match) -> str:
            i = int(m.group(1))
            return tokens[i] if i < len(tokens) else m.group(0)

        return _TOKEN.sub(sub, text)

    def check(self, masked_out: str, tokens: list[str]) -> list[str]:
        found = sorted(int(x) for x in _TOKEN.findall(masked_out))
        expected = list(range(len(tokens)))
        if found == expected:
            return []
        problems = []
        for i in expected:
            c = found.count(i)
            if c == 0:
                problems.append(f"thiếu mã {tokens[i]!r}")
            elif c > 1:
                problems.append(f"lặp mã {tokens[i]!r}")
        for i in set(found) - set(expected):
            problems.append(f"mã lạ ⟦{i}⟧")
        return problems

    def plain(self, text: str) -> str:
        if not self._re:
            return text
        return re.sub(r"\s+", " ", self._re.sub("", text)).strip()

    @staticmethod
    def translatable(masked: str) -> bool:
        rest = re.sub(r"\\.", "", _TOKEN.sub("", masked))     # bỏ mã đã che và escape đơn lẻ như \n
        return any(ch.isalpha() for ch in rest)
