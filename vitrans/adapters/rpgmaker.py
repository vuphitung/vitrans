"""RPG Maker MV / MZ: chữ nằm trong các tệp JSON ở thư mục data."""
from __future__ import annotations

import copy
import re
from pathlib import Path

from ..fonts import validate_font_file
from ..gamefs import GameFS
from ..models import Entry, UnsupportedGameError
from ..protect import RPGMAKER
from ..textutil import clean_text
from ..wrapping import wrap
from .base import Adapter, PatchOptions
from .jsonfields import dumps, get_path, has_letter, keep_ws, loads, set_path

DB_FIELDS = {
    "Actors": (("name", "name"), ("nickname", "name"), ("profile", "desc")),
    "Classes": (("name", "name"),),
    "Items": (("name", "name"), ("description", "desc")),
    "Weapons": (("name", "name"), ("description", "desc")),
    "Armors": (("name", "name"), ("description", "desc")),
    "Skills": (("name", "name"), ("description", "desc"), ("message1", "desc"), ("message2", "desc")),
    "Enemies": (("name", "name"),),
    "States": (("name", "name"), ("message1", "desc"), ("message2", "desc"),
               ("message3", "desc"), ("message4", "desc")),
}
GLOSSARY_FILES = {"Actors": ("name", "nickname"), "Enemies": ("name",)}     # tên riêng nên gợi ý vào từ điển
SYSTEM_LISTS = ("skillTypes", "weaponTypes", "armorTypes", "equipTypes")
FILE_LIKE = re.compile(r"\.(png|jpe?g|ogg|m4a|wav|json|js|webm|mp4)$", re.I)
LIST_MARK = re.compile(r"^\s*([-*•·>]|\d+[.)])\s")


def _worth(s) -> bool:
    return isinstance(s, str) and bool(s.strip()) and has_letter(s) and not FILE_LIKE.search(s.strip())


def _cmd(c) -> tuple:
    """(code, parameters) an toàn với dữ liệu game bị hỏng/cố ý sai cấu trúc."""
    if not isinstance(c, dict):
        return None, []
    p = c.get("parameters")
    return c.get("code"), (p if isinstance(p, list) else [])


def _flowing(lines: list[str]) -> bool:
    """Các dòng là một đoạn văn bị ngắt theo độ rộng hộp thoại (nên gộp lại) hay là danh sách."""
    if len(lines) < 2:
        return True
    if any(not ln.strip() for ln in lines):
        return False
    return not any(LIST_MARK.match(ln) for ln in lines[1:])


class RPGMakerAdapter(Adapter):
    id = "rpgmaker"
    label = "RPG Maker MV/MZ"
    patterns = RPGMAKER

    def __init__(self):
        self.data_root = "www/data"
        self.mz = False
        self._entries: list[Entry] = []
        self._order = 0

    # --- nhận diện -----------------------------------------------------------------
    @staticmethod
    def _find_data_root(fs: GameFS) -> str | None:
        for cand in ("www/data", "data", "resources/app/data"):
            if fs.exists(f"{cand}/System.json"):
                return cand
        return None

    @classmethod
    def detect(cls, fs: GameFS) -> int:
        root = cls._find_data_root(fs)
        if not root:
            return 0
        return 95 if (fs.exists(f"{root}/Actors.json") or fs.exists(f"{root}/MapInfos.json")) else 60

    def _prepare(self, fs: GameFS) -> None:
        root = self._find_data_root(fs)
        if not root:
            raise UnsupportedGameError("Không tìm thấy data/System.json của RPG Maker.")
        self.data_root = root
        system = loads(fs.read_bytes(f"{root}/System.json"))
        if not isinstance(system, dict):
            raise UnsupportedGameError("System.json không đúng định dạng RPG Maker.")
        self.mz = "advanced" in system or "tileSize" in system

    # --- trích chữ ------------------------------------------------------------------
    def extract(self, fs: GameFS) -> list[Entry]:
        self._prepare(fs)
        self._entries, self._order = [], 0
        names = [p.rsplit("/", 1)[1] for p in fs.listdir(self.data_root, "*.json")]

        def rank(n: str):
            stem = n[:-5]
            if stem == "System":
                return (0, 0, n)
            if stem in DB_FIELDS:
                return (1, 0, n)
            if stem == "CommonEvents":
                return (2, 0, n)
            if stem == "Troops":
                return (3, 0, n)
            m = re.fullmatch(r"Map(\d+)", stem)
            return (4, int(m.group(1)), n) if m else (9, 0, n)

        for n in sorted(names, key=rank):
            stem = n[:-5]
            rel = f"{self.data_root}/{n}"
            if rank(n)[0] == 9:
                continue
            data = loads(fs.read_bytes(rel))
            if stem == "System" and isinstance(data, dict):
                self._system(rel, data)
            elif stem in DB_FIELDS and isinstance(data, list):
                self._database(rel, stem, data)
            elif stem == "CommonEvents" and isinstance(data, list):
                for i, ev in enumerate(data):
                    if isinstance(ev, dict) and isinstance(ev.get("list"), list):
                        self._commands(rel, ev["list"], [i, "list"])
            elif stem == "Troops" and isinstance(data, list):
                for i, tr in enumerate(data):
                    pages = tr.get("pages") if isinstance(tr, dict) else None
                    for j, page in enumerate(pages if isinstance(pages, list) else []):
                        if isinstance(page, dict) and isinstance(page.get("list"), list):
                            self._commands(rel, page["list"], [i, "pages", j, "list"])
            elif isinstance(data, dict):
                self._map(rel, data)
        if not self._entries:
            raise UnsupportedGameError("Không tìm thấy đoạn chữ nào trong dữ liệu game (có thể đã mã hóa).")
        return self._entries

    def _add(self, rel, kind, source, locator, key, speaker="", meta=None):
        self._order += 1
        self._entries.append(Entry(key=key, order=self._order, file=rel, kind=kind, source=source,
                                   speaker=speaker, locator=locator, meta=meta or {}))

    def _field(self, rel, kind, path, value, speaker="", gloss=False):
        if _worth(value):
            self._add(rel, kind, value, {"type": "field", "file": rel, "path": path},
                      f"{rel}:{'/'.join(map(str, path))}", speaker, {"gloss": True} if gloss else None)

    def _system(self, rel, system):
        self._field(rel, "ui", ["gameTitle"], system.get("gameTitle"))
        self._field(rel, "ui", ["currencyUnit"], system.get("currencyUnit"))
        for k in SYSTEM_LISTS:
            lst = system.get(k)
            for i, v in enumerate(lst if isinstance(lst, list) else []):
                self._field(rel, "ui", [k, i], v)
        terms = system.get("terms")
        terms = terms if isinstance(terms, dict) else {}
        for group in ("basic", "commands", "params"):
            lst = terms.get(group)
            for i, v in enumerate(lst if isinstance(lst, list) else []):
                self._field(rel, "ui", ["terms", group, i], v)
        msgs = terms.get("messages")
        for k, v in (msgs.items() if isinstance(msgs, dict) else []):
            self._field(rel, "ui", ["terms", "messages", k], v)

    def _database(self, rel, stem, data):
        gloss_fields = GLOSSARY_FILES.get(stem, ())
        for i, obj in enumerate(data):
            if isinstance(obj, dict):
                for fld, kind in DB_FIELDS[stem]:
                    self._field(rel, kind, [i, fld], obj.get(fld), gloss=fld in gloss_fields)

    def _map(self, rel, mp):
        self._field(rel, "name", ["displayName"], mp.get("displayName"))
        events = mp.get("events")
        for i, ev in enumerate(events if isinstance(events, list) else []):
            pages = ev.get("pages") if isinstance(ev, dict) else None
            for j, page in enumerate(pages if isinstance(pages, list) else []):
                if isinstance(page, dict) and isinstance(page.get("list"), list):
                    self._commands(rel, page["list"], ["events", i, "pages", j, "list"])

    def _commands(self, rel, cmds, path):
        i = 0
        while i < len(cmds):
            code, p = _cmd(cmds[i])
            if code in (101, 105):
                body_code = 401 if code == 101 else 405
                j, lines = i + 1, []
                while j < len(cmds) and _cmd(cmds[j])[0] == body_code:
                    bp = _cmd(cmds[j])[1]
                    lines.append(str(bp[0]) if bp else "")
                    j += 1
                speaker = ""
                if code == 101 and len(p) > 4 and isinstance(p[4], str) and p[4].strip():
                    speaker = p[4]
                    self._field(rel, "speaker", path + [i, "parameters", 4], speaker, gloss=True)
                if lines and any(_worth(x) for x in lines):
                    flow = code == 101 and _flowing(lines)
                    source = " ".join(x.strip() for x in lines) if flow else "\n".join(lines)
                    face = bool(code == 101 and p and isinstance(p[0], str) and p[0])
                    loc = {"type": "block", "file": rel, "path": path, "start": i + 1, "count": len(lines),
                           "code": body_code, "face": face}
                    self._add(rel, "dialogue" if code == 101 else "scroll", source, loc,
                              f"{rel}:{'/'.join(map(str, path))}#{i + 1}", speaker, {"flow": flow})
                i = j
                continue
            if code == 102 and p and isinstance(p[0], list):
                for k, ch in enumerate(p[0]):
                    self._field(rel, "choice", path + [i, "parameters", 0, k], ch)
            elif code in (320, 324, 325) and len(p) > 1:
                self._field(rel, "name", path + [i, "parameters", 1], p[1])
            i += 1

    # --- áp dụng bản dịch -----------------------------------------------------------------
    def build_patch(self, fs: GameFS, entries: list[Entry], opts: PatchOptions) -> dict[str, bytes]:
        self._prepare(fs)
        by_file: dict[str, list[Entry]] = {}
        for e in entries:
            if e.usable and e.locator.get("file"):
                by_file.setdefault(e.locator["file"], []).append(e)
        system_rel = f"{self.data_root}/System.json"
        files = set(by_file)
        font_name = None
        if opts.font_path:
            validate_font_file(opts.font_path)
            font_name = "vitrans-font" + Path(opts.font_path).suffix.lower()
            if self.mz:
                files.add(system_rel)
        out: dict[str, bytes] = {}
        for rel in sorted(files):
            obj = loads(fs.read_bytes(rel))
            es = by_file.get(rel, [])
            for e in (x for x in es if x.locator["type"] == "field"):
                path, text = e.locator["path"], clean_text(e.translation)
                try:
                    orig = get_path(obj, path)
                except (KeyError, IndexError, TypeError):
                    continue
                set_path(obj, path, keep_ws(orig, text) if isinstance(orig, str) else text)
            groups: dict[tuple, list[Entry]] = {}
            for e in (x for x in es if x.locator["type"] == "block"):
                groups.setdefault(tuple(e.locator["path"]), []).append(e)
            for path, blocks in groups.items():
                try:
                    lst = get_path(obj, list(path))
                except (KeyError, IndexError, TypeError):
                    continue
                if not isinstance(lst, list):
                    continue
                for e in sorted(blocks, key=lambda x: -x.locator["start"]):
                    self._replace_block(lst, e, opts)
            if font_name and rel == system_rel and isinstance(obj, dict):
                adv = obj.get("advanced")
                if isinstance(adv, dict):
                    adv["mainFontFilename"] = font_name
            out[rel] = dumps(obj)
        if font_name:
            out.update(self._font_files(fs, opts, font_name))
        return out

    @staticmethod
    def _replace_block(lst: list, e: Entry, opts: PatchOptions) -> None:
        loc = e.locator
        start, count, code = loc["start"], loc["count"], loc["code"]
        header_code = 101 if code == 401 else 105
        if (start < 1 or start + count > len(lst) or _cmd(lst[start - 1])[0] != header_code
                or any(_cmd(lst[start + k])[0] != code for k in range(count))):
            return  # dữ liệu game đã đổi so với lúc quét: bỏ qua cho an toàn
        header = lst[start - 1]
        first = lst[start]
        indent = first.get("indent", header.get("indent", 0)) if isinstance(first, dict) else 0
        text = clean_text(e.translation)
        if code == 401:
            width = opts.wrap_width_face if loc.get("face") else opts.wrap_width
            lines = wrap(text, width) or [""]
            per = max(1, opts.max_lines)
            new: list = []
            for k in range(0, len(lines), per):
                if k:
                    new.append(copy.deepcopy(header))       # trang mới lặp lại tiêu đề (ảnh mặt, vị trí...)
                for ln in lines[k:k + per]:
                    new.append({"code": 401, "indent": indent, "parameters": [ln]})
        else:
            new = [{"code": 405, "indent": indent, "parameters": [ln]} for ln in text.split("\n")]
        lst[start:start + count] = new

    def _font_files(self, fs: GameFS, opts: PatchOptions, font_name: str) -> dict[str, bytes]:
        fonts_dir = (Path(self.data_root).parent / "fonts").as_posix()
        fonts_dir = "fonts" if fonts_dir == "." else fonts_dir
        css_rel = f"{fonts_dir}/gamefont.css"
        family = "rmmz-mainfont" if self.mz else "GameFont"
        try:
            css = fs.read_bytes(css_rel).decode("utf-8", errors="replace")
        except OSError:
            css = ""
        block = re.compile(r"(@font-face\s*\{[^}]*font-family:\s*(?:GameFont|rmmz-mainfont)[^}]*?src:\s*)url\([^)]*\)",
                           re.S | re.I)
        if block.search(css):
            css = block.sub(lambda m: m.group(1) + f'url("{font_name}")', css, count=1)
        else:
            css += f'\n@font-face {{\n    font-family: {family};\n    src: url("{font_name}");\n}}\n'
        return {css_rel: css.encode("utf-8"), f"{fonts_dir}/{font_name}": Path(opts.font_path).read_bytes()}

    def preview_width(self, entry: Entry, opts: PatchOptions):
        if entry.locator.get("code") == 401:
            return opts.wrap_width_face if entry.locator.get("face") else opts.wrap_width
        return None
