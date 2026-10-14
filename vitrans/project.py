from __future__ import annotations

from pathlib import Path

from . import adapters
from . import glossary as gl
from .adapters.base import Adapter, PatchOptions
from .fonts import validate_font_file
from .gamefs import GameFS, export_files
from .models import Entry, Style, Term, UnsupportedGameError
from .paths import project_db_path
from .providers import make_provider
from .store import Store
from .translator import Translator, estimate


class Project:
    def __init__(self, root, engine: str | None = None, store_path=None):
        self.root = Path(root).resolve()
        self.fs = GameFS(self.root)
        cands = adapters.detect(self.fs)
        if engine:
            cls = adapters.get_adapter(engine)
        elif cands:
            cls = cands[0][0]
        else:
            raise UnsupportedGameError(
                "Không nhận ra loại game. Hiện hỗ trợ RPG Maker MV/MZ, Ren'Py (có .rpy) và JSON chung.")
        self.adapter: Adapter = cls()
        self.detected = [(c.id, c.label, s) for c, s in cands]
        self.store = Store(store_path or project_db_path(self.root))
        self.entries: list[Entry] = self.store.all_entries()

    # --- quét ----------------------------------------------------------------------------
    def scan(self) -> dict:
        found = self.adapter.extract(self.fs)
        info = self.store.sync(found)
        self.entries = self.store.all_entries()
        return info

    # --- từ điển / phong cách ----------------------------------------------------------------
    @property
    def style(self) -> Style:
        return self.store.style()

    def save_style(self, s: Style) -> None:
        self.store.set_style(s)

    @property
    def glossary(self) -> list[Term]:
        return self.store.glossary()

    def save_glossary(self, terms: list[Term]) -> None:
        self.store.set_glossary(terms)

    def suggest_glossary(self) -> list[Term]:
        have = {t.src.lower() for t in self.glossary}
        seen, out = set(), []
        for e in self.entries:
            if e.meta.get("gloss"):                       # tên nhân vật/kẻ địch/người nói do bộ trích chữ đánh dấu
                s = e.source.strip()
                if s and s.lower() not in have and s.lower() not in seen and len(s) <= 40:
                    seen.add(s.lower())
                    out.append(Term(s, s, "tên riêng (giữ nguyên, sửa nếu muốn Việt hóa)"))
        return out

    # --- dịch ------------------------------------------------------------------------------------
    def make_translator(self, cfg) -> Translator:
        return Translator(self.store, self.adapter, make_provider(cfg), self.style, self.glossary,
                          batch_chars=cfg["batch_chars"], batch_items=cfg["batch_items"],
                          context_lines=cfg["context_lines"], concurrency=cfg["concurrency"], retries=cfg["retries"])

    def translate(self, cfg, **kw):
        return self.make_translator(cfg).run(self.entries, **kw)

    def check_translation(self, entry: Entry, text: str) -> str:
        """Cảnh báo cho bản dịch (gõ tay hoặc máy): mã điều khiển lệch, lỗi cú pháp engine, thuật ngữ chưa dùng."""
        text = text.strip()
        if not text:
            return ""
        prot = self.adapter.protector()
        warns = []
        if sorted(prot.tokens_of(text)) != sorted(prot.tokens_of(entry.source)):
            warns.append("Mã điều khiển/biến khác bản gốc")
        warns += self.adapter.validate(text)
        miss = gl.missing(self.glossary, entry.source, text)
        if miss:
            warns.append("Chưa dùng thuật ngữ: " + ", ".join(f"{t.src}→{t.vi}" for t in miss))
        return "; ".join(warns)

    def set_translation(self, entry: Entry, text: str, status: str) -> None:
        entry.translation, entry.status = text, status
        entry.warn = self.check_translation(entry, text)
        self.store.update_entries([entry])

    def estimate(self, only_keys=None, force: bool = False) -> tuple[int, int]:
        return estimate(self.entries, only_keys, force)

    # --- ghi vào game -------------------------------------------------------------------------------
    @staticmethod
    def patch_options(cfg) -> PatchOptions:
        return PatchOptions(wrap_width=cfg["wrap_width"], wrap_width_face=cfg["wrap_width_face"],
                            max_lines=cfg["max_lines"], font_path=cfg["font_path"] or "",
                            renpy_force_language=bool(cfg["renpy_force_language"]))

    def build_files(self, cfg) -> dict[str, bytes]:
        opts = self.patch_options(cfg)
        if opts.font_path:
            validate_font_file(opts.font_path)
        return self.adapter.build_patch(self.fs, self.entries, opts)

    def apply(self, cfg) -> list[str]:
        files = self.build_files(cfg)
        if not files:
            return []
        return self.fs.write_files(files)

    def export(self, cfg, out_dir) -> list[str]:
        return export_files(out_dir, self.build_files(cfg))

    def restore(self) -> int:
        return self.fs.restore()

    def close(self) -> None:
        self.store.close()
