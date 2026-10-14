from __future__ import annotations

import re

from .models import Term


def _pattern(src: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(src) + r"(?!\w)", re.IGNORECASE)


def relevant(terms: list[Term], text: str) -> list[Term]:
    return [t for t in terms if t.src and _pattern(t.src).search(text)]


def missing(terms: list[Term], source: str, translation: str) -> list[Term]:
    """Thuật ngữ xuất hiện ở bản gốc nhưng bản dịch không dùng đúng cách dịch đã chốt."""
    out = []
    for t in relevant(terms, source):
        if t.vi and t.vi.lower() not in translation.lower():
            out.append(t)
    return out
