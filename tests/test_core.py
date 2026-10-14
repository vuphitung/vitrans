import json
import threading

import pytest

from vitrans.config import AppConfig
from vitrans.gamefs import GameFS, UnsafePathError, safe_join
from vitrans.models import ERROR, MACHINE, PENDING, REVIEWED, SKIP, Style, Term, UnsupportedGameError
from vitrans.project import Project
from vitrans.protect import Protector, RPGMAKER, RENPY
from vitrans.providers import EchoProvider, ProviderAuthError, parse_items_json
from vitrans.translator import Translator
from vitrans.wrapping import visible_len, wrap


# ---------------- che mã / ngắt dòng ----------------
def test_protect_roundtrip_rpg():
    p = Protector(RPGMAKER)
    src = "\\C[2]Rose\\C[0]: You have \\V[1] coins, %1 left.\\!"
    masked, tokens = p.mask(src)
    assert "\\" not in masked and "⟦0⟧" in masked
    assert p.unmask(masked, tokens) == src
    assert p.check(masked, tokens) == []
    assert p.check(masked.replace("⟦1⟧", ""), tokens)  # thiếu mã bị phát hiện


def test_protect_renpy_tags():
    p = Protector(RENPY)
    src = 'He said \\"hi\\" {i}to[name]{/i} 100%% sure'
    masked, tokens = p.mask(src)
    assert "{i}" not in masked and "[name]" not in masked and "%%" not in masked
    assert p.unmask(masked, tokens) == src


def test_translatable():
    p = Protector(RPGMAKER)
    assert not p.translatable(p.mask("\\C[2]...")[0])
    assert p.translatable(p.mask("\\C[2]Hi")[0])


def test_wrap_ignores_codes():
    assert visible_len("\\C[2]Rose\\C[0]") == 4
    lines = wrap("\\C[2]Rose\\C[0]: " + "word " * 30, 40)
    assert all(visible_len(x) <= 40 for x in lines) and len(lines) > 1
    assert wrap("a\n\nb", 20) == ["a", "", "b"]


# ---------------- an toàn đường dẫn / sao lưu ----------------
def test_safe_join(tmp_path):
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, "../evil")
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, "/etc/passwd")


def test_backup_restore_and_idempotent(tmp_path):
    root = tmp_path / "g"
    root.mkdir()
    (root / "a.txt").write_text("orig")
    fs = GameFS(root)
    fs.write_files({"a.txt": b"new", "sub/b.txt": b"created"})
    assert (root / "a.txt").read_text() == "new"
    assert fs.read_bytes("a.txt") == b"orig"            # đọc bản gốc từ backup
    fs.write_files({"a.txt": b"newer"})
    assert fs.restore() == 2
    assert (root / "a.txt").read_text() == "orig"
    assert not (root / "sub").exists() and not fs.has_backup()


# ---------------- RPG Maker ----------------
def test_rpg_extract(rpg_game):
    p = Project(rpg_game)
    assert p.adapter.id == "rpgmaker"
    info = p.scan()
    by_src = {e.source: e for e in p.entries}
    # hai dòng 401 gộp thành 1 đoạn
    flow = "\\C[2]Rose\\C[0]: Did you hear that? It came from the cellar..."
    assert flow in by_src and by_src[flow].kind == "dialogue"
    assert "Go down" in by_src and by_src["Go down"].kind == "choice"
    assert "Rusty Key" in by_src and "Dark House" in by_src and "Hallway" in by_src
    assert "Never touched" not in by_src
    assert info["added"] == len(p.entries)


def test_rpg_patch_wrap_chunk_and_idempotent(rpg_game):
    p = Project(rpg_game)
    p.scan()
    cfg = AppConfig()
    cfg["provider"] = "echo"
    res = p.translate(cfg)
    assert res.failed == 0
    # biến câu dài thành bản dịch dài để buộc ngắt thành nhiều trang
    long_e = next(e for e in p.entries if e.source.startswith("I do not think"))
    p.set_translation(long_e, "Tôi không nghĩ chúng ta nên xuống đó tối nay, tiếng động ngày càng lớn hơn và " * 5, REVIEWED)
    files1 = p.apply(cfg)
    assert "www/data/Map001.json" in files1
    mp = json.loads((rpg_game / "www/data/Map001.json").read_text("utf-8"))
    cmds = mp["events"][1]["pages"][0]["list"]
    bodies = {}
    cur = []
    for c in cmds:
        if c["code"] == 101:
            cur = []
            bodies.setdefault(len(bodies), cur)
        elif c["code"] == 401:
            cur.append(c["parameters"][0])
    assert all(len(v) <= 4 for v in bodies.values())            # mỗi trang ≤ 4 dòng
    assert sum(1 for c in cmds if c["code"] == 101) > 3         # đoạn dài đã tách thêm trang
    assert any("\\C[2]" in l and "(VI)" in l for v in bodies.values() for l in v)   # mã màu còn nguyên
    assert mp["displayName"].startswith("(VI)")
    snapshot = (rpg_game / "www/data/Map001.json").read_bytes()
    p.apply(cfg)                                                  # áp dụng lần 2 không được chồng lên nhau
    assert (rpg_game / "www/data/Map001.json").read_bytes() == snapshot
    p.restore()
    orig = json.loads((rpg_game / "www/data/Map001.json").read_text("utf-8"))
    assert orig["displayName"] == "Hallway"
    # quét lại sau khi áp dụng/khôi phục vẫn ra bản tiếng Anh
    p2 = Project(rpg_game)
    p2.scan()
    assert all("(VI)" not in e.source for e in p2.entries)


def test_rpg_font_patch(rpg_game, tmp_path):
    fonts = rpg_game / "www/fonts"
    fonts.mkdir()
    (fonts / "gamefont.css").write_text('@font-face {\n    font-family: GameFont;\n    src: url("mplus-1m-regular.ttf");\n}\n')
    font = tmp_path / "Viet.ttf"
    font.write_bytes(b"\x00\x01\x00\x00FAKEFONT")
    p = Project(rpg_game)
    p.scan()
    cfg = AppConfig()
    cfg["provider"], cfg["font_path"] = "echo", str(font)
    p.translate(cfg)
    p.apply(cfg)
    assert (fonts / "vitrans-font.ttf").read_bytes() == b"\x00\x01\x00\x00FAKEFONT"
    assert "vitrans-font.ttf" in (fonts / "gamefont.css").read_text()
    p.restore()
    assert "mplus-1m-regular.ttf" in (fonts / "gamefont.css").read_text()
    assert not (fonts / "vitrans-font.ttf").exists()


# ---------------- Ren'Py ----------------
def test_renpy_extract(renpy_game):
    p = Project(renpy_game)
    assert p.adapter.id == "renpy"
    p.scan()
    got = {(e.kind, e.source) for e in p.entries}
    assert ("name", "Eileen") in got
    assert ("ui", "Dark Manor") in got and ("ui", "Start") in got and ("ui", "Version 1.0") in got
    assert ("dialogue", "I heard a noise from the {i}cellar{/i}, [player_name].") in got
    assert ("dialogue", "The door creaked.") in got and ("dialogue", "You wait.") in got
    assert ("choice", "Go downstairs") in got and ("choice", "Stay here") in got
    srcs = {s for _, s in got}
    assert "Apple" not in srcs and "audio/theme.ogg" not in srcs
    e = next(x for x in p.entries if x.source.startswith("I heard"))
    assert e.speaker == "Eileen"


def test_renpy_patch(renpy_game, tmp_path):
    p = Project(renpy_game)
    p.scan()
    cfg = AppConfig()
    cfg["provider"] = "echo"
    p.translate(cfg)
    out = tmp_path / "patch"
    p.export(cfg, out)
    txt = (out / "game/tl/vietnamese/vitrans_strings.rpy").read_text("utf-8")
    assert "translate vietnamese strings:" in txt
    assert 'old "The door creaked."' in txt and 'new "(VI) The door creaked."' in txt
    assert "{i}cellar{/i}" in txt
    assert 'config.language = "vietnamese"' in (out / "game/vitrans_language.rpy").read_text()
    assert not (renpy_game / "game/tl").exists()               # export không đụng vào game


def test_renpy_rpyc_only(tmp_path):
    root = tmp_path / "Compiled"
    (root / "game").mkdir(parents=True)
    (root / "game/script.rpyc").write_bytes(b"x")
    with pytest.raises(UnsupportedGameError):
        Project(root).scan()


# ---------------- JSON chung ----------------
def test_generic_json(json_game):
    p = Project(json_game)
    assert p.adapter.id == "generic_json"
    p.scan()
    srcs = {e.source for e in p.entries}
    assert srcs == {"The Long Night", "You wake up in a cold room."} or "You wake up in a cold room." in srcs
    assert "abc_123" not in srcs and "img/a.png" not in srcs and "ok" not in srcs


def test_unknown_game(tmp_path):
    (tmp_path / "x").mkdir()
    with pytest.raises(UnsupportedGameError):
        Project(tmp_path / "x")


# ---------------- dịch ----------------
def _translator(p, provider, **kw):
    return Translator(p.store, p.adapter, provider, Style(), p.glossary, **kw)


def test_translate_reuse_and_resume(rpg_game):
    p = Project(rpg_game)
    p.scan()
    tr = _translator(p, EchoProvider())
    r1 = tr.run(p.entries)
    assert r1.failed == 0 and r1.translated > 0
    assert all(e.status == MACHINE for e in p.entries if e.kind != "name" or e.translation)
    r2 = tr.run(p.entries)                                       # chạy lại: không còn gì để dịch
    assert r2.translated == 0
    p2 = Project(rpg_game)                                       # nạp lại từ DB: bản dịch còn
    assert any(e.translation.startswith("(VI)") for e in p2.entries)
    p2.scan()                                                    # quét lại: bản dịch được giữ
    assert any(e.status == MACHINE for e in p2.entries)


def test_duplicates_translated_once(rpg_game):
    p = Project(rpg_game)
    p.scan()
    calls = []

    class Counting(EchoProvider):
        def translate_batch(self, items, style, glossary):
            calls.extend(i.text for i in items)
            return super().translate_batch(items, style, glossary)

    # nhân đôi một câu để có hai mục trùng nguồn
    dup = next(e for e in p.entries if e.source == "Go down")
    import copy
    d2 = copy.deepcopy(dup)
    d2.key, d2.order = dup.key + "_dup", 9999
    p.entries.append(d2)
    _translator(p, Counting()).run(p.entries)
    assert calls.count("Go down") == 1
    assert d2.translation == dup.translation and d2.status == MACHINE


def test_retry_on_broken_tokens(rpg_game):
    p = Project(rpg_game)
    p.scan()
    state = {"n": 0}

    class Flaky(EchoProvider):
        def translate_batch(self, items, style, glossary):
            out = super().translate_batch(items, style, glossary)
            if state["n"] == 0:                                   # lượt đầu: làm mất mã định dạng
                out = {k: v.replace("⟦0⟧", "") for k, v in out.items()}
            state["n"] += 1
            return out

    r = _translator(p, Flaky(), retries=1).run(p.entries)
    assert r.failed == 0
    rose = next(e for e in p.entries if e.source.startswith("\\C[2]Rose"))
    assert rose.translation.count("\\C[2]") == 1


def test_error_marks_and_never_patches(rpg_game):
    p = Project(rpg_game)
    p.scan()

    class Broken(EchoProvider):
        def translate_batch(self, items, style, glossary):
            return {i.id: "mất hết mã" for i in items}

    _translator(p, Broken(), retries=0).run(p.entries)
    rose = next(e for e in p.entries if e.source.startswith("\\C[2]Rose"))
    assert rose.status == ERROR and rose.warn
    assert rose.translation == ""
    cfg = AppConfig()
    cfg["provider"] = "echo"
    p.apply(cfg)
    mp = (rpg_game / "www/data/Map001.json").read_text("utf-8")
    assert "Did you hear that?" in mp                 # câu lỗi giữ nguyên tiếng Anh, không bị ghi đè


def test_auth_error_aborts(rpg_game):
    p = Project(rpg_game)
    p.scan()

    class Denied(EchoProvider):
        def translate_batch(self, items, style, glossary):
            raise ProviderAuthError("sai khóa")

    with pytest.raises(ProviderAuthError):
        _translator(p, Denied()).run(p.entries)


def test_cancel(rpg_game):
    p = Project(rpg_game)
    p.scan()
    ev = threading.Event()
    ev.set()
    r = _translator(p, EchoProvider()).run(p.entries, cancel=ev)
    assert r.cancelled and all(e.status == PENDING for e in p.entries if e.source.strip())


def test_glossary_warning_and_skip(rpg_game):
    p = Project(rpg_game)
    p.scan()
    p.save_glossary([Term("Rose", "Hoa Hồng", "tên nhân vật")])
    skip = next(e for e in p.entries if e.source == "Rusty Key")
    skip.status = SKIP
    p.store.update_entries([skip])
    _translator(p, EchoProvider()).run(p.entries)
    rose = next(e for e in p.entries if e.source.startswith("\\C[2]Rose"))
    assert "Hoa Hồng" in rose.warn
    assert skip.status == SKIP and skip.translation == ""


def test_parse_items_json():
    assert parse_items_json('```json\n[{"id":"1","vi":"a"}]\n```') == {"1": "a"}
    assert parse_items_json('Đây:\n[{"id": 2, "vi": "b"}]') == {"2": "b"}
