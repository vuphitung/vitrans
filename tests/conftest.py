import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("VITRANS_HOME", str(tmp_path / "home"))


def _w(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


@pytest.fixture
def rpg_game(tmp_path):
    root = tmp_path / "DarkHouse"
    d = root / "www" / "data"
    _w(d / "System.json", {"gameTitle": "Dark House", "currencyUnit": "G", "versionId": 1,
                           "skillTypes": ["", "Magic"], "weaponTypes": ["", "Dagger"], "armorTypes": [""],
                           "equipTypes": [""], "terms": {"basic": ["Level", "Lv", None],
                           "commands": ["Fight", "Escape", None], "params": ["Max HP"],
                           "messages": {"actionFailure": "There was no effect on %1!"}}})
    _w(d / "Actors.json", [None, {"id": 1, "name": "Rose", "nickname": "", "profile": "A quiet girl."}])
    _w(d / "Items.json", [None, {"id": 1, "name": "Rusty Key", "description": "Opens the cellar door."}])
    long_text = ("I do not think we should go down there tonight, the noises are getting louder and louder "
                 "and I really do not like the way the shadows move when the candle flickers.")
    page = [
        {"code": 101, "indent": 0, "parameters": ["Actor1", 0, 0, 2]},
        {"code": 401, "indent": 0, "parameters": ["\\C[2]Rose\\C[0]: Did you hear that?"]},
        {"code": 401, "indent": 0, "parameters": ["It came from the cellar..."]},
        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
        {"code": 401, "indent": 0, "parameters": [long_text]},
        {"code": 102, "indent": 0, "parameters": [["Go down", "Stay here"], 1, 0, 2, 0]},
        {"code": 402, "indent": 0, "parameters": [0, "Go down"]},
        {"code": 401, "indent": 1, "parameters": ["Never touched"]},
        {"code": 0, "indent": 0, "parameters": []},
        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
        {"code": 401, "indent": 0, "parameters": ["You have \\V[1] coins."]},
        {"code": 0, "indent": 0, "parameters": []},
    ]
    # bỏ 402/401 lẻ cho đơn giản: viết lại danh sách sạch
    page = [c for c in page if not (c["code"] == 402 or (c["code"] == 401 and c["indent"] == 1))]
    _w(d / "Map001.json", {"displayName": "Hallway", "events": [None, {"id": 1, "pages": [{"list": page}]}]})
    _w(d / "MapInfos.json", [None, {"id": 1, "name": "Hallway"}])
    return root


@pytest.fixture
def renpy_game(tmp_path):
    root = tmp_path / "ManorGame"
    g = root / "game"
    g.mkdir(parents=True)
    (g / "script.rpy").write_text('''define e = Character("Eileen", color="#c8ffc8")
define config.name = _("Dark Manor")
default brave = False

label start:
    scene bg room
    play music "audio/theme.ogg"
    e "I heard a noise from the {i}cellar{/i}, [player_name]."
    "The door creaked."
    menu:
        "Go downstairs":
            jump cellar
        "Stay here" if not brave:
            "You wait."
    return

screen main_menu():
    textbutton _("Start") action Start()
    text "Version 1.0"

init python:
    items = [
        "Apple"
    ]
''', encoding="utf-8")
    return root


@pytest.fixture
def json_game(tmp_path):
    root = tmp_path / "JsonGame"
    _w(root / "lang" / "en.json", {"title": "The Long Night", "id": "abc_123", "path": "img/a.png",
                                   "lines": ["You wake up in a cold room.", "ok"]})
    return root


@pytest.fixture
def renpy_real_patterns(tmp_path):
    """Các mẫu mã gặp trong game Ren'Py thật (The Question): tên bọc _(), nút ngôn ngữ, chuỗi định dạng ngày..."""
    root = tmp_path / "RealPatterns"
    g = root / "game"
    g.mkdir(parents=True)
    (g / "script.rpy").write_text('''define s = Character(_("Sylvie"), color="#c8ffc8")
define m = Character(_("Me"), color="#c8c8ff")
define config.name = _("The Question")
default book = False

screen preferences():
    vbox:
        label _("Language")
        textbutton "English" action Language(None)
        textbutton "Français" action Language("french")
        textbutton "日本語" action Language("japanese")
    text _("Page {}")
    text _("{#file_time}%A, %B %d %Y, %H:%M")
    text _("[config.version!t]\\n")

label start:
    play music "illurock.opus"
    scene bg lecturehall
    with fade
    s "Hello [m]! It is 100%% real."
    m "I'm {i}fine{/i}."
    menu:
        "Ask her":
            jump ask
        "Stay quiet":
            pass
    return
''', encoding="utf-8")
    return root
