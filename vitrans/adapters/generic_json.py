"""Phương án dự phòng: quét mọi chuỗi giống câu văn trong các tệp JSON của game."""
from __future__ import annotations

import re

from ..gamefs import GameFS
from ..models import Entry, UnsupportedGameError
from ..protect import GENERIC
from ..textutil import clean_text
from .base import Adapter, PatchOptions
from .jsonfields import dumps, get_path, keep_ws, loads, set_path

URLISH = re.compile(r"^(https?://|[A-Za-z]:\\|/|\w+\.\w{2,4}$)")
IGNORE_FILES = ("package.json", "package-lock.json", "tsconfig.json", "manifest.json")
MAX_DEPTH = 40
MAX_JSON_BYTES = 8_000_000


def looks_like_text(s: str) -> bool:
    s = s.strip()
    if len(s) < 8 or " " not in s or URLISH.match(s):
        return False
    letters = sum(ch.isalpha() for ch in s)
    words = [w for w in re.split(r"\s+", s) if any(c.isalpha() for c in w)]
    return letters / len(s) >= 0.6 and len(words) >= 2


class GenericJsonAdapter(Adapter):
    id = "generic_json"
    label = "JSON chung (quét tự động)"
    patterns = GENERIC

    @classmethod
    def detect(cls, fs: GameFS) -> int:
        return 5 if fs.rglob("*.json") else 0

    def extract(self, fs: GameFS) -> list[Entry]:
        entries: list[Entry] = []

        def walk(rel, path, node, depth):
            if depth > MAX_DEPTH:
                return
            items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
            for k, v in items:
                if isinstance(v, str):
                    if looks_like_text(v):
                        p = path + [k]
                        entries.append(Entry(key=f"{rel}:{'/'.join(map(str, p))}", order=len(entries) + 1, file=rel,
                                             kind="text", source=v,
                                             locator={"type": "field", "file": rel, "path": p}))
                elif isinstance(v, (dict, list)):
                    walk(rel, path + [k], v, depth + 1)

        for rel in fs.rglob("*.json"):
            if rel.rsplit("/", 1)[-1] in IGNORE_FILES:
                continue
            try:
                raw = fs.read_bytes(rel)
                if len(raw) > MAX_JSON_BYTES:
                    continue
                obj = loads(raw)
            except (ValueError, OSError):
                continue
            walk(rel, [], obj, 0)
        if not entries:
            raise UnsupportedGameError("Không tìm thấy chuỗi văn bản nào trong các tệp JSON.")
        return entries

    def build_patch(self, fs: GameFS, entries: list[Entry], opts: PatchOptions) -> dict[str, bytes]:
        by_file: dict[str, list[Entry]] = {}
        for e in entries:
            if e.usable:
                by_file.setdefault(e.locator["file"], []).append(e)
        out = {}
        for rel, es in by_file.items():
            obj = loads(fs.read_bytes(rel))
            for e in es:
                try:
                    orig = get_path(obj, e.locator["path"])
                except (KeyError, IndexError, TypeError):
                    continue
                text = clean_text(e.translation)
                set_path(obj, e.locator["path"], keep_ws(orig, text) if isinstance(orig, str) else text)
            out[rel] = dumps(obj)
        return out
