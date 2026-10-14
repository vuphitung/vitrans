from __future__ import annotations

import json


def loads(data: bytes):
    """Đọc JSON từ dữ liệu không đáng tin: lỗi/độ sâu quá mức đều quy về ValueError."""
    try:
        return json.loads(data.decode("utf-8-sig"))
    except RecursionError as ex:
        raise ValueError("JSON lồng nhau quá sâu") from ex
    except UnicodeDecodeError as ex:
        raise ValueError(f"Không phải UTF-8: {ex}") from ex


def dumps(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def get_path(obj, path):
    for p in path:
        obj = obj[p]
    return obj


def set_path(obj, path, value) -> None:
    get_path(obj, path[:-1])[path[-1]] = value


def keep_ws(orig: str, new: str) -> str:
    lead = orig[: len(orig) - len(orig.lstrip())]
    trail = orig[len(orig.rstrip()):]
    return lead + new.strip() + trail


def has_letter(s: str) -> bool:
    return any(ch.isalpha() for ch in s)
