"""Ren'Py: đọc các tệp .rpy và sinh tệp dịch `translate vietnamese strings`."""
from __future__ import annotations

import re
from pathlib import Path

from ..fonts import validate_font_file
from ..gamefs import GameFS
from ..models import REVIEWED, Entry, PatchError, UnsupportedGameError
from ..protect import RENPY, Protector
from ..textutil import clean_text, rpy_literal
from .base import Adapter, PatchOptions

LANG = "vietnamese"
MAX_LINE = 4000          # dòng dài hơn mức này bị bỏ qua (tránh regex chạy chậm với tệp độc hại)
# Ren'Py chấp nhận chuỗi nháy kép "..." và nháy đơn '...' (renpy/lexer.py, Lexer.string)
_S = r"""(?:"(?P<dq>(?:[^"\\]|\\.)*)"|'(?P<sq>(?:[^'\\]|\\.)*)')"""
SAY_RE = re.compile(r'^\s*(?:(?P<who>[A-Za-z_]\w*)(?P<attrs>(?:\s+[@A-Za-z_][\w@.]*)*)\s+)?' + _S +
                    r'(?:\s+(?:with\s+\S+|nointeract|id\s+\S+))*\s*$')
CHOICE_RE = re.compile(r'^\s*' + _S + r'(?:\s+if\s+.+?)?\s*:\s*$')
UI_RE = re.compile(r'^\s*(?:text|textbutton|label|tooltip)\s+' + _S)
TR_RE = re.compile(r'\b_\(\s*' + _S + r'\s*\)')
CHAR_RE = re.compile(r'^\s*(?:define|default|\$)\s+(?:[A-Za-z_]\w*\.)?(?P<var>[A-Za-z_]\w*)\s*=\s*'
                     r'(?:Character|DynamicCharacter|NVLCharacter|ADVCharacter)\(\s*(?:_\(\s*)?'
                     r"""(?:"(?P<name>(?:[^"\\]|\\.)*)"|'(?P<sname>(?:[^'\\]|\\.)*)'|(?P<other>[^,)]*))""")
PY_BLOCK_RE = re.compile(r'^\s*(?:init(?:\s+-?\d+)?\s+)?python\b[^:]*:\s*$')
EXTRA_SPEAKERS = {"extend", "narrator", "centered", "nvl"}

fix_quotes = rpy_literal          # tên cũ, giữ để tương thích

_DEQUOTE = re.compile(r"\\(u([0-9a-fA-F]{1,4})|.)", re.S)


def sq_to_dq(body: str) -> str:
    """Nội dung chuỗi nháy đơn -> nội dung tương đương đặt trong nháy kép."""
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            out.append("'" if body[i + 1] == "'" else body[i:i + 2])
            i += 2
        elif c == '"':
            out.append('\\"')
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _lit(m) -> str:
    return m["dq"] if m["dq"] is not None else sq_to_dq(m["sq"])


def eval_literal(body: str) -> str:
    """Giá trị Ren'Py thực sự dùng làm khóa tra bảng dịch (chuyển thể từ Lexer.string trong renpy/lexer.py):
    dãy khoảng trắng/xuống dòng gộp thành một dấu cách, rồi xử lý escape. Hai chuỗi thô khác nhau có thể cho cùng
    một khóa, và Ren'Py ném lỗi "A translation ... already exists" nếu một khóa được dịch hai lần."""
    s = re.sub(r"[ \n]+", " ", body)

    def dequote(m):
        c = m.group(1)
        if c == "{":
            return "{{"
        if c == "[":
            return "[["
        if c == "%":
            return "%%"
        if c == "n":
            return "\n"
        if c[0] == "u":
            return chr(int(m.group(2), 16)) if m.group(2) else ""
        return c

    return _DEQUOTE.sub(dequote, s)


class RenPyAdapter(Adapter):
    id = "renpy"
    label = "Ren'Py"
    patterns = RENPY

    @classmethod
    def detect(cls, fs: GameFS) -> int:
        if fs.rglob("*.rpy", "game"):
            return 90
        if fs.rglob("*.rpyc", "game") or fs.exists("renpy"):
            return 60
        return 0

    @staticmethod
    def _skip(rel: str) -> bool:
        return "/tl/" in rel or rel.startswith("game/renpy/") or rel.startswith("game/cache/")

    def extract(self, fs: GameFS) -> list[Entry]:
        files = [p for p in fs.rglob("*.rpy", "game") if not self._skip(p)]
        if not files:
            raise UnsupportedGameError(
                "Game này chỉ có tệp đã biên dịch (.rpyc), không có mã nguồn .rpy. "
                "Cần giải mã .rpyc bằng công cụ riêng (ví dụ unrpyc) trước, nếu tác giả cho phép.")
        texts = {p: fs.read_bytes(p).decode("utf-8-sig", errors="replace") for p in files}
        chars = set(EXTRA_SPEAKERS)
        names: dict[str, str] = {}
        for t in texts.values():
            for ln in t.splitlines():
                if len(ln) > MAX_LINE:
                    continue
                m = CHAR_RE.match(ln)
                if m:
                    chars.add(m["var"])
                    if m["name"]:
                        names[m["var"]] = m["name"]
        prot = self.protector()

        def worth(s: str) -> bool:
            return Protector.translatable(prot.mask(s)[0])

        entries: list[Entry] = []
        seen_ui: set[str] = set()

        def add(rel, ln, kind, text, speaker="", idx=0, gloss=False):
            entries.append(Entry(key=f"{rel}:{ln}:{idx}", order=len(entries) + 1, file=rel, kind=kind, source=text,
                                 speaker=speaker, locator={"type": "string", "file": rel, "line": ln},
                                 meta={"gloss": True} if gloss else {}))

        for rel in sorted(texts):
            in_triple = False
            py_indent: int | None = None
            for ln, raw in enumerate(texts[rel].splitlines(), 1):
                if len(raw) > MAX_LINE:
                    continue
                line = raw.rstrip().expandtabs(4)
                s = line.strip()
                if in_triple:
                    if '"""' in line:
                        in_triple = False
                    continue
                if s.count('"""') % 2 == 1:
                    in_triple = True
                    continue
                if not s or s.startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip())
                in_py = False
                if py_indent is not None:
                    if indent > py_indent:
                        in_py = True
                    else:
                        py_indent = None
                if not in_py and PY_BLOCK_RE.match(line):
                    py_indent = indent
                    continue
                if "Language(" in line:          # nút chọn ngôn ngữ: nhãn cố ý viết bằng chính ngôn ngữ đó, không dịch
                    continue
                # tên nhân vật (kể cả khi bọc trong _()) -> loại "name", đưa vào gợi ý từ điển
                cm = CHAR_RE.match(line)
                cname = (cm["name"] if cm["name"] is not None else sq_to_dq(cm["sname"]) if cm["sname"] is not None
                         else None) if cm else None
                if cname and worth(cname) and cname not in seen_ui:
                    seen_ui.add(cname)
                    add(rel, ln, "name", cname, idx=9, gloss=True)
                # chuỗi bọc trong _("...") ở bất kỳ đâu (kể cả trong khối python)
                used = False
                for k, m in enumerate(TR_RE.finditer(line)):
                    used = True
                    t = _lit(m)
                    if worth(t) and t not in seen_ui:
                        seen_ui.add(t)
                        add(rel, ln, "ui", t, idx=k + 1)
                if cm or in_py or s.startswith("$") or used:
                    continue
                m = CHOICE_RE.match(line)
                if m:
                    if worth(_lit(m)):
                        add(rel, ln, "choice", _lit(m))
                    continue
                m = UI_RE.match(line)
                if m:
                    t = _lit(m)
                    if worth(t) and t not in seen_ui:
                        seen_ui.add(t)
                        add(rel, ln, "ui", t)
                    continue
                m = SAY_RE.match(line)
                if m and (m["who"] is None or m["who"] in chars) and worth(_lit(m)):
                    who = m["who"] or ""
                    add(rel, ln, "dialogue", _lit(m), speaker=names.get(who, who))
        if not entries:
            raise UnsupportedGameError("Không trích được câu thoại nào từ các tệp .rpy.")
        return entries

    # --- kiểm tra bản dịch (cú pháp Ren'Py) ----------------------------------------------------
    def validate(self, text: str) -> list[str]:
        masked, _ = self.protector().mask(text)
        if "{" in masked or "[" in masked:
            return ["Có dấu { hoặc [ lẻ: Ren'Py sẽ báo lỗi khi hiển thị. Muốn hiện nguyên dấu thì viết {{ hoặc [["]
        return []

    def finalize(self, text: str) -> str:
        return rpy_literal(text)

    # --- ghi bản vá -----------------------------------------------------------------------------------
    def build_patch(self, fs: GameFS, entries: list[Entry], opts: PatchOptions) -> dict[str, bytes]:
        base = f"game/tl/{LANG}"
        foreign = [p for p in fs.rglob("*.rpy", base) if not Path(p).name.startswith("vitrans_")]
        if foreign:
            raise PatchError(
                f"Game đã có bản dịch tiếng Việt khác tại {base} ({Path(foreign[0]).name}…). Ghi thêm sẽ gây lỗi "
                "trùng chuỗi và game không khởi động được. Hãy đổi tên/xóa thư mục đó trước, hoặc dùng 'Xuất bản vá'.")
        # Mỗi khóa tra bảng chỉ được có MỘT bản dịch (trùng là Ren'Py không khởi động được). Khóa là giá trị sau khi
        # Ren'Py chuẩn hóa (vd. "A.  B" và "A. B" là cùng khóa); trong các câu trùng khóa, ưu tiên câu đã duyệt.
        chosen: dict[str, Entry] = {}
        for e in entries:
            if not e.usable:
                continue
            k = eval_literal(e.source)
            cur = chosen.get(k)
            if cur is None or (cur.status != REVIEWED and e.status == REVIEWED):
                chosen[k] = e
        bad = [e for e in chosen.values() if self.validate(clean_text(e.translation))]
        if bad:
            raise PatchError(
                f"{len(bad)} bản dịch có dấu {{ hoặc [ lẻ nên Ren'Py sẽ báo lỗi khi hiển thị, ví dụ: "
                + "; ".join(repr(e.source[:40]) for e in bad[:3])
                + ". Hãy sửa các câu này (lọc theo 'Có cảnh báo') rồi áp dụng lại.")
        out_lines = ["# Tạo bởi ViTrans - đừng sửa tay, hãy dịch lại bằng công cụ.", f"translate {LANG} strings:", ""]
        for e in chosen.values():
            new = rpy_literal(clean_text(e.translation).strip())
            out_lines += [f"    # {e.locator.get('file')}:{e.locator.get('line')}",
                          f'    old "{e.source}"', f'    new "{new}"', ""]
        files = {f"{base}/vitrans_strings.rpy": ("\n".join(out_lines) + "\n").encode("utf-8")}
        # Ngôn ngữ: config.language áp dụng MỌI lần khởi động (00start.rpy: _init_language). config.default_language chỉ
        # có tác dụng ở lần chạy đầu của game (00defaults.rpy: persistent._set_preferences) nên dễ không hiệu lực.
        lang_var = "language" if opts.renpy_force_language else "default_language"
        files["game/vitrans_language.rpy"] = (
            f'# Tạo bởi ViTrans\ninit python:\n    config.{lang_var} = "{LANG}"\n').encode("utf-8")
        if opts.font_path:
            validate_font_file(opts.font_path)
            font_rel = f"game/fonts/vitrans-font{Path(opts.font_path).suffix.lower()}"
            files[font_rel] = Path(opts.font_path).read_bytes()
            ref = font_rel[len("game/"):]
            names = ("system_font", "main_font", "text_font", "name_text_font", "interface_text_font",
                     "button_text_font", "choice_button_text_font")
            font_lines = ["# Tạo bởi ViTrans", f"translate {LANG} python:"] + [f'    gui.{n} = "{ref}"' for n in names]
            files[f"{base}/vitrans_font.rpy"] = ("\n".join(font_lines) + "\n").encode("utf-8")
        return files
