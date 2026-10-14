"""Kiểm thử an toàn & hồi quy: mỗi test tương ứng một lỗi/rủi ro đã được tìm ra khi rà soát."""
import json
import os
import random
import re
import stat
import sys
import time
import unicodedata

import pytest

from renpy_oracle import lex_string

from vitrans import gamefs
from vitrans.adapters.renpy import eval_literal
from vitrans.config import AppConfig
from vitrans.gamefs import GameFileError, GameFS, UnsafePathError
from vitrans.models import ERROR, MACHINE, PENDING, REVIEWED, SKIP, PatchError, Style
from vitrans.paths import data_dir
from vitrans.project import Project
from vitrans.protect import GENERIC, RENPY, RPGMAKER, Protector
from vitrans.providers import (EchoProvider, OpenAICompatProvider, ProviderFatalError, build_system_prompt,
                               provider_is_remote)
from vitrans.textutil import clean_text, rpy_literal
from vitrans.translator import MAX_SOURCE, Translator, estimate

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="quyền tệp kiểu POSIX")


def _tr(p, provider, **kw):
    return Translator(p.store, p.adapter, provider, Style(), p.glossary, **kw)


def _cfg():
    c = AppConfig()
    c["provider"] = "echo"
    return c


# ---------------- ReDoS: chuỗi độc hại không được làm treo công cụ ----------------
@pytest.mark.parametrize("pats,payload", [
    (RPGMAKER, "\\a[" * 100000), (RPGMAKER, "<" * 100000), (RPGMAKER, "\\" * 100000),
    (RENPY, "[a" * 100000), (RENPY, "{a" * 100000), (GENERIC, "{a" * 100000),
])
def test_regex_stays_fast(pats, payload):
    t = time.time()
    Protector(pats).mask(payload)
    assert time.time() - t < 3


# ---------------- literal Ren'Py luôn hợp lệ ----------------
def test_rpy_literal_cases():
    assert rpy_literal("abc\\") == "abc\\\\"                 # backslash lẻ ở cuối không được nuốt dấu " đóng
    assert rpy_literal('a\\\\"b') == 'a\\\\\\"b'             # \\ giữ, " trần bị escape
    assert rpy_literal('say "hi"') == 'say \\"hi\\"'
    assert rpy_literal("a\nb") == "a\\nb"
    assert rpy_literal("\\u00e9") == "\\u00e9"
    assert rpy_literal("\\q") == "\\\\q"                     # escape lạ không được phá cú pháp


def test_rpy_literal_property():
    rnd = random.Random(1234)
    alphabet = ['\\', '"', "'", "n", "u", "0", "e", " ", "\n", "x", "é", "%", "{", "["]
    for _ in range(3000):
        s = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 14)))
        out = rpy_literal(s)
        assert rpy_literal(out) == out                       # idempotent
        i = 0
        while i < len(out):                                  # mô phỏng bộ đọc chuỗi: không được có " trần/backslash lẻ
            assert out[i] != '"', (s, out)
            assert out[i] != "\n", (s, out)
            if out[i] == "\\":
                assert i + 1 < len(out), (s, out)
                i += 1
            i += 1


def test_clean_text_nfc_and_invisible():
    nfd = unicodedata.normalize("NFD", "Việt Nam")
    assert clean_text(nfd) == "Việt Nam" and len(clean_text(nfd)) == len("Việt Nam")
    assert clean_text("a\u202eb\u200bc\x07d\ufeff") == "abcd"       # bidi override, zero-width, BEL, BOM
    assert clean_text("a\r\nb\rc") == "a\nb\nc"


# ---------------- AI không được chèn mã/đưa dữ liệu bẩn vào game ----------------
class _Mutate(EchoProvider):
    def __init__(self, fn):
        self.fn = fn

    def translate_batch(self, items, style, glossary):
        return {i.id: self.fn(i.text) for i in items}


def test_rpg_extra_control_code_rejected(rpg_game):
    p = Project(rpg_game)
    p.scan()
    _tr(p, _Mutate(lambda t: t + " \\V[9]"), retries=0).run(p.entries)
    rose = next(e for e in p.entries if e.source.startswith("\\C[2]Rose"))
    plain = next(e for e in p.entries if e.source == "Rusty Key")
    assert rose.status == ERROR and "lạ" in rose.warn           # câu có mã bị từ chối
    assert plain.status == ERROR                                # \V[9] không có trong bản gốc cũng bị từ chối


def test_renpy_injection_and_stray_brackets_rejected(renpy_game):
    p = Project(renpy_game)
    p.scan()
    _tr(p, _Mutate(lambda t: t + " {b}[x.__class__]"), retries=0).run(p.entries)
    assert all(e.status == ERROR for e in p.entries)
    for e in p.entries:
        e.status = PENDING
    _tr(p, _Mutate(lambda t: t + " dấu { lẻ"), retries=0).run(p.entries)
    assert all(e.status == ERROR for e in p.entries)
    assert not p.build_files(_cfg())["game/tl/vietnamese/vitrans_strings.rpy"].decode().count("class__")


def test_renpy_quotes_in_translation_make_valid_literal(renpy_game):
    p = Project(renpy_game)
    p.scan()
    _tr(p, _Mutate(lambda t: 'Anh ấy nói "xin chào" \\'), retries=0).run(p.entries)
    txt = p.build_files(_cfg())["game/tl/vietnamese/vitrans_strings.rpy"].decode()
    for line in txt.splitlines():
        if line.strip().startswith("new "):
            body = line.strip()[5:-1]
            i = 0
            while i < len(body):
                assert body[i] != '"'
                i += 2 if body[i] == "\\" else 1


def test_length_bomb_rejected(rpg_game):
    p = Project(rpg_game)
    p.scan()
    _tr(p, _Mutate(lambda t: "x" * 20000), retries=0).run(p.entries)
    assert all(e.status in (ERROR, MACHINE) for e in p.entries)
    assert not any(len(e.translation) > 10000 for e in p.entries)


def test_output_is_cleaned_before_storing(rpg_game):
    p = Project(rpg_game)
    p.scan()
    _tr(p, _Mutate(lambda t: unicodedata.normalize("NFD", t.replace("Rusty Key", "Chìa khóa gỉ")) + "\u202e"),
        retries=0).run(p.entries)
    key = next(e for e in p.entries if e.source == "Rusty Key")
    assert key.translation == unicodedata.normalize("NFC", "Chìa khóa gỉ")


def test_system_prompt_marks_game_text_untrusted():
    assert "untrusted" in build_system_prompt(Style(), [])


def test_source_too_long_not_sent(rpg_game):
    p = Project(rpg_game)
    p.scan()
    victim = next(e for e in p.entries if e.source == "Rusty Key")
    victim.source = "word " * (MAX_SOURCE // 4)
    seen = []

    class Spy(EchoProvider):
        def translate_batch(self, items, style, glossary):
            seen.extend(i.text for i in items)
            return super().translate_batch(items, style, glossary)

    _tr(p, Spy()).run(p.entries)
    assert victim.status == ERROR and not any(len(t) > MAX_SOURCE for t in seen)


# ---------------- độ bền của tiến trình dịch ----------------
def test_one_bad_batch_does_not_kill_run(rpg_game):
    p = Project(rpg_game)
    p.scan()
    state = {"n": 0}

    class Flaky(EchoProvider):
        def translate_batch(self, items, style, glossary):
            state["n"] += 1
            if state["n"] == 1:
                raise ValueError("JSON hỏng")                 # lỗi bất ngờ, không phải ProviderError
            return super().translate_batch(items, style, glossary)

    r = _tr(p, Flaky(), retries=1).run(p.entries)
    assert r.failed == 0 and all(e.status == MACHINE for e in p.entries if e.source.strip())


def test_circuit_breaker_stops_on_repeated_failures(rpg_game):
    p = Project(rpg_game)
    p.scan()
    calls = {"n": 0}

    class Down(EchoProvider):
        def translate_batch(self, items, style, glossary):
            calls["n"] += 1
            raise RuntimeError("mất mạng")

    with pytest.raises(ProviderFatalError):
        _tr(p, Down(), batch_items=1, concurrency=1, retries=1).run(p.entries)
    assert calls["n"] <= 4                                      # dừng sớm, không gọi hết mọi lô
    assert all(e.status == PENDING for e in p.entries)


def test_explicit_selection_can_translate_skipped(rpg_game):
    p = Project(rpg_game)
    p.scan()
    ents = {e.source: e for e in p.entries}
    ents["Rusty Key"].status = SKIP
    ents["Hallway"].status = SKIP
    _tr(p, EchoProvider()).run(p.entries, only_keys={ents["Rusty Key"].key}, force=True)
    assert ents["Rusty Key"].status == MACHINE and ents["Hallway"].status == SKIP
    _tr(p, EchoProvider()).run(p.entries)                       # chạy thường không đụng tới câu "bỏ qua"
    assert ents["Hallway"].status == SKIP


def test_estimate_counts_unique_untranslated(rpg_game):
    p = Project(rpg_game)
    p.scan()
    n, chars = estimate(p.entries)
    assert n == len({e.source for e in p.entries}) and chars > 0
    _tr(p, EchoProvider()).run(p.entries)
    assert estimate(p.entries) == (0, 0)


# ---------------- tệp: symlink, manifest giả, bản gốc lỗi thời, quyền ----------------
def test_symlinked_files_are_never_read(rpg_game, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "Map002.json").write_text(json.dumps({"displayName": "SECRET EXFIL LINE", "events": []}))
    (rpg_game / "www/data/Map002.json").symlink_to(outside / "Map002.json")
    p = Project(rpg_game)
    p.scan()
    assert not any("SECRET" in e.source for e in p.entries)


def test_symlinked_rpy_is_not_extracted(renpy_game, tmp_path):
    out = tmp_path / "secret.rpy"
    out.write_text('"SECRET NARRATION"\n')
    (renpy_game / "game/leak.rpy").symlink_to(out)
    p = Project(renpy_game)
    p.scan()
    assert not any("SECRET" in e.source for e in p.entries)


def test_symlinked_system_json_refused(tmp_path):
    root = tmp_path / "G"
    (root / "www/data").mkdir(parents=True)
    secret = tmp_path / "s.json"
    secret.write_text('{"gameTitle":"x"}')
    (root / "www/data/System.json").symlink_to(secret)
    with pytest.raises(UnsafePathError):
        Project(root)


def test_write_through_symlinked_dir_refused(tmp_path):
    root = tmp_path / "G"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "data").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePathError):
        GameFS(root).write_files({"data/x.json": b"{}"})
    assert list(outside.iterdir()) == []


def test_write_files_validates_all_paths_before_writing(tmp_path):
    root = tmp_path / "G"
    root.mkdir()
    with pytest.raises(UnsafePathError):
        GameFS(root).write_files({"ok.txt": b"1", "../evil.txt": b"2"})
    assert not (root / "ok.txt").exists() and not (tmp_path / "evil.txt").exists()


def test_tampered_manifest_cannot_escape_or_destroy(tmp_path):
    root = tmp_path / "G"
    (root / ".vitrans_backup").mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    (root / "game.txt").write_text("precious")
    (root / ".vitrans_backup/manifest.json").write_text(json.dumps({
        "backed_up": ["../victim.txt", "/etc/passwd"], "created": ["../victim.txt", "game.txt"],
        "written": {"game.txt": "deadbeef"}}))
    fs = GameFS(root)
    assert fs.restore() == 0                                      # không văng lỗi, không đụng gì
    assert victim.read_text() == "keep me" and (root / "game.txt").read_text() == "precious"


def test_manifest_without_hash_is_not_trusted(tmp_path):
    root = tmp_path / "G"
    (root / ".vitrans_backup").mkdir(parents=True)
    (root / "a.txt").write_text("live")
    (root / ".vitrans_backup/a.txt").write_text("attacker-supplied original")
    (root / ".vitrans_backup/manifest.json").write_text(json.dumps({"backed_up": ["a.txt"], "created": []}))
    fs = GameFS(root)
    assert fs.read_bytes("a.txt") == b"live"                      # backup không có mã băm thì không phải "bản gốc"
    assert fs.restore() == 0 and (root / "a.txt").read_text() == "live"


def test_game_update_after_patch_is_respected(tmp_path):
    root = tmp_path / "G"
    root.mkdir()
    (root / "d.txt").write_text("v1")
    fs = GameFS(root)
    fs.write_files({"d.txt": b"patched"})
    assert fs.read_bytes("d.txt") == b"v1"
    (root / "d.txt").write_text("v2")                             # Steam/launcher cập nhật tệp
    assert fs.read_bytes("d.txt") == b"v2"                        # bản hiện tại mới là bản gốc
    fs.write_files({"d.txt": b"patched2"})                        # áp dụng lại: backup được làm mới
    assert fs.read_bytes("d.txt") == b"v2"
    fs.restore()
    assert (root / "d.txt").read_text() == "v2"


def test_restore_keeps_files_updated_by_game(tmp_path):
    root = tmp_path / "G"
    root.mkdir()
    (root / "d.txt").write_text("v1")
    fs = GameFS(root)
    fs.write_files({"d.txt": b"patched"})
    (root / "d.txt").write_text("v2")
    assert fs.restore() == 0
    assert (root / "d.txt").read_text() == "v2" and fs.restore_skipped == ["d.txt"]


@posix_only
def test_file_mode_preserved(tmp_path):
    root = tmp_path / "G"
    root.mkdir()
    for name, mode in (("a", 0o644), ("b", 0o664), ("c", 0o600)):
        (root / name).write_text("x")
        (root / name).chmod(mode)
    GameFS(root).write_files({"a": b"1", "b": b"2", "c": b"3", "new.txt": b"4"})
    assert [stat.S_IMODE((root / n).stat().st_mode) for n in ("a", "b", "c", "new.txt")] == [0o644, 0o664, 0o600, 0o644]


def test_oversized_file_rejected(tmp_path, monkeypatch):
    root = tmp_path / "G"
    root.mkdir()
    (root / "big.json").write_bytes(b"x" * 5000)
    monkeypatch.setattr(gamefs, "MAX_READ", 1000)
    with pytest.raises(GameFileError):
        GameFS(root).read_bytes("big.json")


# ---------------- cấu hình & khóa API ----------------
@posix_only
def test_config_file_and_dir_permissions():
    old = os.umask(0)                                             # umask lỏng nhất: quyền phải do mã ép, không do may mắn
    try:
        c = AppConfig()
        c["anthropic_key"] = "sk-secret"
        c.save()
        assert stat.S_IMODE(c.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(data_dir().stat().st_mode) == 0o700
    finally:
        os.umask(old)


def test_config_key_precedence_and_unknown_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    c = AppConfig()
    assert c.anthropic_key() == "from-env"
    c["anthropic_key"] = "typed"
    assert c.anthropic_key() == "typed"
    c["__evil__"] = 1
    assert "__evil__" not in c.data


def test_api_key_never_sent_over_plain_http():
    with pytest.raises(ProviderFatalError):
        OpenAICompatProvider("http://example.com/v1", "m", "secret")
    with pytest.raises(ProviderFatalError):
        OpenAICompatProvider("file:///etc/passwd", "m")
    OpenAICompatProvider("http://localhost:11434/v1", "m", "k")   # máy mình thì được
    OpenAICompatProvider("https://api.example.com/v1", "m", "k")


def test_provider_is_remote():
    c = AppConfig()
    for prov, url, expected in (("anthropic", "", True), ("google", "", True), ("echo", "", False),
                                ("openai", "http://localhost:11434/v1", False), ("openai", "https://x.com/v1", True)):
        c["provider"], c["openai_base_url"] = prov, url or c["openai_base_url"]
        assert provider_is_remote(c) is expected


# ---------------- dữ liệu game độc hại/hỏng ----------------
def test_malformed_rpg_data_does_not_crash(tmp_path):
    root = tmp_path / "Weird"
    d = root / "www/data"
    d.mkdir(parents=True)
    (d / "System.json").write_text(json.dumps({"gameTitle": "Weird Game", "terms": "not-a-dict", "skillTypes": 5}))
    (d / "Actors.json").write_text(json.dumps({"not": "a list"}))
    (d / "Map001.json").write_text(json.dumps({"displayName": "Room", "events": [
        None, 5, {"pages": [None, {"list": None}, {"list": [
            3, None, {"code": 101, "parameters": "oops"}, {"code": 401, "parameters": []},
            {"code": 101, "parameters": ["", 0, 0, 2]}, {"code": 401, "parameters": ["Real line of text."]},
            {"code": 102, "parameters": [[1, None, "Pick me"]]}]}]}]}))
    p = Project(root)
    p.scan()
    srcs = {e.source for e in p.entries}
    assert {"Weird Game", "Room", "Real line of text.", "Pick me"} <= srcs
    cfg = _cfg()
    _tr(p, EchoProvider()).run(p.entries)
    assert p.apply(cfg)                                           # và vẫn ghi được


def test_json_bomb_is_a_clean_error(tmp_path):
    root = tmp_path / "Bomb"
    d = root / "www/data"
    d.mkdir(parents=True)
    (d / "System.json").write_text('{"gameTitle":"x"}')
    (d / "Actors.json").write_text("[" * 200000 + "]" * 200000)
    with pytest.raises(ValueError):                               # không phải RecursionError
        Project(root).scan()


def test_generic_json_skips_bomb_and_keeps_order(tmp_path):
    root = tmp_path / "J"
    root.mkdir()
    (root / "bomb.json").write_text("[" * 200000 + "]" * 200000)
    (root / "t.json").write_text(json.dumps({"lines": [f"This is sentence number {i} here" for i in range(12)]}))
    p = Project(root)
    p.scan()
    nums = [int(e.source.split()[-2]) for e in p.entries]
    assert nums == list(range(12))                                # thứ tự tự nhiên, không phải 0,1,10,11,2...


# ---------------- Ren'Py: không đè lên bản dịch có sẵn; khóa lệch dòng vẫn giữ bản dịch ----------------
def test_renpy_refuses_to_clash_with_existing_vietnamese(renpy_game):
    tl = renpy_game / "game/tl/vietnamese"
    tl.mkdir(parents=True)
    (tl / "someone_else.rpy").write_text('translate vietnamese strings:\n    old "Start"\n    new "Bắt đầu"\n')
    p = Project(renpy_game)
    p.scan()
    _tr(p, EchoProvider()).run(p.entries)
    with pytest.raises(PatchError):
        p.apply(_cfg())
    with pytest.raises(PatchError):
        p.export(_cfg(), renpy_game.parent / "out")
    assert not (tl / "vitrans_strings.rpy").exists()


def test_translations_survive_line_shift(renpy_game):
    p = Project(renpy_game)
    p.scan()
    _tr(p, EchoProvider()).run(p.entries)
    n_before = len(p.entries)
    script = renpy_game / "game/script.rpy"
    script.write_text("# dòng thêm 1\n# dòng thêm 2\n# dòng thêm 3\n" + script.read_text("utf-8"), encoding="utf-8")
    p2 = Project(renpy_game)
    info = p2.scan()
    assert len(p2.entries) == n_before and info["carried"] > 0
    assert all(e.status == MACHINE for e in p2.entries)           # không mất bản dịch dù số dòng đã lệch


def test_reviewed_translation_wins_for_duplicate_source(renpy_game):
    p = Project(renpy_game)
    p.scan()
    _tr(p, EchoProvider()).run(p.entries)
    dup = next(e for e in p.entries if e.source == "The door creaked.")
    import copy
    d2 = copy.deepcopy(dup)
    d2.key, d2.order, d2.status, d2.translation = dup.key + "x", 999, REVIEWED, "Cánh cửa kẽo kẹt."
    p.entries.append(d2)
    txt = p.build_files(_cfg())["game/tl/vietnamese/vitrans_strings.rpy"].decode()
    assert 'new "Cánh cửa kẽo kẹt."' in txt and txt.count('old "The door creaked."') == 1


# ---------------- font ----------------
def test_font_validation(rpg_game, tmp_path):
    bad = tmp_path / "evil.ttf"
    bad.write_bytes(b"#!/bin/sh\necho pwned\n")
    p = Project(rpg_game)
    p.scan()
    _tr(p, EchoProvider()).run(p.entries)
    cfg = _cfg()
    for path in (bad, tmp_path / "missing.ttf", tmp_path / "notfont.txt"):
        if path.name == "notfont.txt":
            path.write_bytes(b"\x00\x01\x00\x00")
        cfg["font_path"] = str(path)
        before = (rpg_game / "www/data/Map001.json").read_bytes()
        with pytest.raises(ValueError):
            p.apply(cfg)
        assert (rpg_game / "www/data/Map001.json").read_bytes() == before     # lỗi font thì game không bị đụng tới
    assert not (rpg_game / ".vitrans_backup").exists()


# ---------------- Ren'Py: các phát hiện khi đối chiếu với mã nguồn & game Ren'Py thật ----------------
def test_rpy_literal_lexes_as_one_renpy_string():
    """Mọi kết quả phải được CHÍNH bộ phân tích của Ren'Py đọc thành đúng một chuỗi, không tràn qua dấu " đóng."""
    rnd = random.Random(99)
    alphabet = ['\\', '"', "'", "n", "u", "x", "N", "0", "1", "a", "F", " ", "\n", "\t", "é", "%", "{", "["]
    for _ in range(8000):
        s = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 16)))
        lit = '"' + rpy_literal(s) + '"'
        res = lex_string(lit)
        assert res is not None and res[1] == len(lit), (s, lit)
        if "\\" not in s:                      # văn bản thường: giá trị Ren'Py đọc ra == văn bản gốc (khoảng trắng gộp)
            assert res[0] == re.sub(r" +", " ", s), (s, lit, res)


def test_eval_literal_matches_renpy_lexer():
    rnd = random.Random(7)
    pieces = ["a", "b", " ", "  ", "\\n", '\\"', "\\\\", "\\u00e9", "\\u12", "\\x", "\\{", "\\[", "\\%", "{", "[", "%",
              "\n", "é", "\\ "]
    for _ in range(5000):
        body = "".join(rnd.choice(pieces) for _ in range(rnd.randint(0, 10)))
        res = lex_string('"' + body + '"')
        if res is not None and res[1] == len(body) + 2:
            assert eval_literal(body) == res[0], body


def test_real_patterns_extraction(renpy_real_patterns):
    p = Project(renpy_real_patterns)
    p.scan()
    by = {e.source: e for e in p.entries}
    # tên nhân vật bọc trong _() là "name" và vào gợi ý từ điển
    assert by["Sylvie"].kind == "name" and by["Me"].kind == "name"
    assert {t.src for t in p.suggest_glossary()} == {"Sylvie", "Me"}
    # nút chọn ngôn ngữ không được đưa đi dịch
    assert not {"English", "Français", "日本語"} & set(by)
    # câu thoại, lựa chọn, giao diện vẫn đủ; lệnh play/scene không lọt vào
    assert by["Hello [m]! It is 100%% real."].kind == "dialogue" and by["Ask her"].kind == "choice"
    assert "illurock.opus" not in by and "bg lecturehall" not in by


def test_format_only_strings_never_extracted_or_sent(renpy_real_patterns):
    p = Project(renpy_real_patterns)
    p.scan()
    srcs = {e.source for e in p.entries}
    assert not any("%A" in t or "version" in t for t in srcs)       # chuỗi định dạng ngày, [config.version!t]\n: để nguyên
    sent = []

    class Spy(EchoProvider):
        def translate_batch(self, items, style, glossary):
            sent.extend(i.text for i in items)
            return super().translate_batch(items, style, glossary)

    _tr(p, Spy()).run(p.entries)
    assert not any("%A" in t for t in sent)
    hello = next(e for e in p.entries if e.source.startswith("Hello"))
    assert "100%%" in hello.translation and "[m]" in hello.translation   # %% và [biến] được bảo vệ


def test_renpy_language_file_forces_language_by_default(renpy_real_patterns):
    p = Project(renpy_real_patterns)
    p.scan()
    _tr(p, EchoProvider()).run(p.entries)
    cfg = _cfg()
    files = p.build_files(cfg)
    assert 'config.language = "vietnamese"' in files["game/vitrans_language.rpy"].decode()
    assert "default_language" not in files["game/vitrans_language.rpy"].decode()
    cfg["renpy_force_language"] = False
    files = p.build_files(cfg)
    assert 'config.default_language = "vietnamese"' in files["game/vitrans_language.rpy"].decode()


def test_renpy_font_patch_and_clean_restore(renpy_real_patterns, tmp_path):
    font = tmp_path / "Viet.ttf"
    font.write_bytes(b"\x00\x01\x00\x00FAKE")
    p = Project(renpy_real_patterns)
    p.scan()
    _tr(p, EchoProvider()).run(p.entries)
    cfg = _cfg()
    cfg["font_path"] = str(font)
    written = set(p.apply(cfg))
    assert {"game/tl/vietnamese/vitrans_strings.rpy", "game/vitrans_language.rpy",
            "game/tl/vietnamese/vitrans_font.rpy", "game/fonts/vitrans-font.ttf"} <= written
    fontrpy = (renpy_real_patterns / "game/tl/vietnamese/vitrans_font.rpy").read_text()
    assert 'gui.system_font = "fonts/vitrans-font.ttf"' in fontrpy and "translate vietnamese python:" in fontrpy
    p.restore()
    assert sorted(x.name for x in (renpy_real_patterns / "game").iterdir()) == ["script.rpy"]   # dọn sạch, không để lại thư mục rỗng


def _strings_pairs(txt):
    olds, news = [], []
    for line in txt.splitlines():
        t = line.strip()
        if t.startswith(("old ", "new ")):
            res = lex_string(t[4:])
            assert res is not None and res[1] == len(t[4:]), t       # Ren'Py đọc được trọn dòng
            (olds if t.startswith("old ") else news).append(res[0])
    return olds, news


def test_generated_strings_file_has_unique_valid_old_strings(renpy_real_patterns):
    p = Project(renpy_real_patterns)
    p.scan()
    _tr(p, EchoProvider()).run(p.entries)
    olds, news = _strings_pairs(p.build_files(_cfg())["game/tl/vietnamese/vitrans_strings.rpy"].decode())
    assert olds and len(olds) == len(news) == len(set(olds))         # Ren'Py ném lỗi nếu một khóa được dịch hai lần


def test_keys_that_differ_only_by_whitespace_are_emitted_once(tmp_path):
    root = tmp_path / "WS"
    (root / "game").mkdir(parents=True)
    (root / "game/script.rpy").write_text(
        'define e = Character("E")\nlabel start:\n'
        '    e "Hello.  How are you?"\n    e "Hello. How are you?"\n    e "Hello.   How are you?"\n',
        encoding="utf-8")
    p = Project(root)
    p.scan()
    assert len([e for e in p.entries if e.kind == "dialogue"]) == 3
    _tr(p, EchoProvider()).run(p.entries)
    olds, _ = _strings_pairs(p.build_files(_cfg())["game/tl/vietnamese/vitrans_strings.rpy"].decode())
    assert olds.count("Hello. How are you?") == 1 and len(olds) == len(set(olds))


def test_single_quoted_strings_supported(tmp_path):
    root = tmp_path / "SQ"
    (root / "game").mkdir(parents=True)
    (root / "game/script.rpy").write_text(
        "define e = Character('Eileen')\nlabel start:\n"
        "    e 'Hello there, it\\'s me.'\n    'Narration with \"quotes\" inside.'\n"
        "    menu:\n        'Don\\'t go':\n            pass\n",
        encoding="utf-8")
    p = Project(root)
    p.scan()
    srcs = {e.kind: e.source for e in p.entries}
    assert {e.source for e in p.entries} >= {"Eileen", "Hello there, it's me.", 'Narration with \\"quotes\\" inside.',
                                              "Don't go"}
    _tr(p, EchoProvider()).run(p.entries)
    olds, _ = _strings_pairs(p.build_files(_cfg())["game/tl/vietnamese/vitrans_strings.rpy"].decode())
    # giá trị Ren'Py sẽ tra bảng = đúng chuỗi người chơi thấy trong game
    assert "Hello there, it's me." in olds and 'Narration with "quotes" inside.' in olds and "Don't go" in olds
    assert srcs


# ---------------- kiểm tra bản dịch gõ tay, chuyển hướng, gợi ý từ điển ----------------
def test_manual_edit_gets_same_quality_warnings(rpg_game):
    p = Project(rpg_game)
    p.scan()
    p.save_glossary([__import__("vitrans.models", fromlist=["Term"]).Term("Rose", "Hoa Hồng")])
    rose = next(e for e in p.entries if e.source.startswith("\\C[2]Rose"))
    p.set_translation(rose, "Rose: Bạn có nghe thấy không?", REVIEWED)          # thiếu \C[2], \C[0] và không dùng từ điển
    assert "Mã điều khiển" in rose.warn and "Hoa Hồng" in rose.warn and rose.status == REVIEWED
    p.set_translation(rose, "\\C[2]Hoa Hồng\\C[0]: Bạn có nghe thấy không?", REVIEWED)
    assert rose.warn == ""


def test_renpy_manual_stray_brace_blocks_apply(renpy_game):
    p = Project(renpy_game)
    p.scan()
    _tr(p, EchoProvider()).run(p.entries)
    door = next(e for e in p.entries if e.source == "The door creaked.")
    p.set_translation(door, "Cánh cửa { kẽo kẹt", REVIEWED)
    assert "lẻ" in door.warn                                                    # cảnh báo ngay khi gõ
    with pytest.raises(PatchError):
        p.apply(_cfg())
    assert not (renpy_game / "game/tl").exists() and not (renpy_game / ".vitrans_backup").exists()
    p.set_translation(door, "Cánh cửa kẽo kẹt", REVIEWED)
    assert p.apply(_cfg())


def test_provider_never_follows_redirects(monkeypatch):
    import types
    prov = OpenAICompatProvider("https://api.example.com/v1", "m", "secret")
    seen = {}

    def fake_request(method, url, **kw):
        seen.update(kw)
        return types.SimpleNamespace(status_code=302, headers={"location": "https://evil.example"}, text="")

    monkeypatch.setattr(prov.session, "request", fake_request)
    from vitrans.providers import BatchItem
    with pytest.raises(ProviderFatalError):
        prov.translate_batch([BatchItem("1", "Hello")], Style(), [])
    assert seen.get("allow_redirects") is False


def test_glossary_suggestions_rpg(rpg_game):
    p = Project(rpg_game)
    p.scan()
    assert {t.src for t in p.suggest_glossary()} == {"Rose"}                     # chỉ tên riêng, không phải mọi vật phẩm
