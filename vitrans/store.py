"""Cơ sở dữ liệu SQLite cho từng dự án: câu thoại, bản dịch, từ điển, cài đặt."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .models import Entry, Style, Term

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries(
  key TEXT PRIMARY KEY, ord INTEGER, file TEXT, kind TEXT, speaker TEXT,
  source TEXT, translation TEXT, status TEXT, warn TEXT, locator TEXT, meta TEXT);
CREATE INDEX IF NOT EXISTS idx_entries_ord ON entries(ord);
CREATE TABLE IF NOT EXISTS glossary(term TEXT PRIMARY KEY, vi TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
"""


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- entries ---------------------------------------------------------------
    @staticmethod
    def _row_to_entry(r) -> Entry:
        return Entry(
            key=r["key"], order=r["ord"], file=r["file"], kind=r["kind"], speaker=r["speaker"] or "",
            source=r["source"], translation=r["translation"] or "", status=r["status"],
            warn=r["warn"] or "", locator=json.loads(r["locator"] or "{}"), meta=json.loads(r["meta"] or "{}"),
        )

    def sync(self, entries: list[Entry]) -> dict:
        """Gộp kết quả quét mới với dữ liệu cũ, giữ bản dịch nếu câu gốc không đổi."""
        with self._lock:
            old = {r["key"]: r for r in self._db.execute(
                "SELECT key, source, translation, status, warn FROM entries")}
            by_source: dict[str, tuple[str, str]] = {}      # câu gốc -> (bản dịch, trạng thái), ưu tiên "đã duyệt"
            for r in old.values():
                if r["translation"] and r["status"] in ("machine", "reviewed"):
                    cur = by_source.get(r["source"])
                    if cur is None or (cur[1] != "reviewed" and r["status"] == "reviewed"):
                        by_source[r["source"]] = (r["translation"], r["status"])
            seen = set()
            added = kept = changed = carried = 0
            cur = self._db.cursor()
            for e in entries:
                seen.add(e.key)
                o = old.get(e.key)
                if o is not None and o["source"] == e.source:
                    e.translation, e.status, e.warn = o["translation"] or "", o["status"], o["warn"] or ""
                    kept += 1
                else:
                    if e.source in by_source:                # khóa đổi (vd. game cập nhật làm lệch dòng) nhưng câu vẫn còn
                        e.translation, e.status = by_source[e.source]
                        carried += 1
                    elif o is not None:
                        changed += 1
                    else:
                        added += 1
                cur.execute(
                    "INSERT OR REPLACE INTO entries VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (e.key, e.order, e.file, e.kind, e.speaker, e.source, e.translation, e.status,
                     e.warn, json.dumps(e.locator, ensure_ascii=False), json.dumps(e.meta, ensure_ascii=False)),
                )
            removed = [k for k in old if k not in seen]
            cur.executemany("DELETE FROM entries WHERE key=?", [(k,) for k in removed])
            self._db.commit()
        return {"added": added, "kept": kept, "changed": changed, "removed": len(removed), "carried": carried}

    def all_entries(self) -> list[Entry]:
        with self._lock:
            return [self._row_to_entry(r) for r in self._db.execute("SELECT * FROM entries ORDER BY ord")]

    def update_entries(self, entries: list[Entry]) -> None:
        with self._lock:
            self._db.executemany(
                "UPDATE entries SET translation=?, status=?, warn=? WHERE key=?",
                [(e.translation, e.status, e.warn, e.key) for e in entries],
            )
            self._db.commit()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {r["status"]: r["n"] for r in self._db.execute(
                "SELECT status, COUNT(*) n FROM entries GROUP BY status")}

    # --- glossary ------------------------------------------------------------------
    def glossary(self) -> list[Term]:
        with self._lock:
            return [Term(r["term"], r["vi"] or "", r["note"] or "")
                    for r in self._db.execute("SELECT * FROM glossary ORDER BY term COLLATE NOCASE")]

    def set_glossary(self, terms: list[Term]) -> None:
        with self._lock:
            self._db.execute("DELETE FROM glossary")
            self._db.executemany(
                "INSERT OR REPLACE INTO glossary VALUES(?,?,?)",
                [(t.src.strip(), t.vi.strip(), t.note.strip()) for t in terms if t.src.strip()],
            )
            self._db.commit()

    # --- settings ----------------------------------------------------------------------
    def get_setting(self, k: str, default=None):
        with self._lock:
            r = self._db.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else default

    def set_setting(self, k: str, v) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, json.dumps(v, ensure_ascii=False)))
            self._db.commit()

    def style(self) -> Style:
        return Style.from_dict(self.get_setting("style", {}) or {})

    def set_style(self, s: Style) -> None:
        self.set_setting("style", s.to_dict())
