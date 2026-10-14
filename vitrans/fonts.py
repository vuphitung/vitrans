"""Kiểm tra / tìm font hỗ trợ tiếng Việt (game cũ hay dùng font không có dấu)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

VI_SAMPLE = ("ăâđêôơưĂÂĐÊÔƠƯàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ")
RISKY_NAMES = ("arial", "segoe", "tahoma", "times", "calibri", "verdana", "helvetica", "microsoft", "consola", "cambria")
PREFERRED = ("notosans", "be vietnam", "bevietnam", "roboto", "opensans", "dejavusans", "liberation", "ubuntu", "lato")


MAX_FONT_BYTES = 32 * 1024 * 1024
_FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true")


def validate_font_file(path: str) -> None:
    """Chỉ cho phép sao chép đúng tệp font thật (tránh chép nhầm/độc hại vào thư mục game)."""
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"Không tìm thấy tệp font: {path}")
    if p.suffix.lower() not in (".ttf", ".otf"):
        raise ValueError("Font phải có đuôi .ttf hoặc .otf")
    if p.stat().st_size > MAX_FONT_BYTES:
        raise ValueError("Tệp font quá lớn (> 32 MB)")
    with open(p, "rb") as f:
        if f.read(4) not in _FONT_MAGIC:
            raise ValueError("Tệp này không phải font TrueType/OpenType hợp lệ")


def supports_vietnamese(path: str) -> bool | None:
    """True/False nếu kiểm tra được, None nếu chưa cài fontTools."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    try:
        font = TTFont(path, lazy=True, fontNumber=0)
        cmap = font.getBestCmap() or {}
        return all(ord(c) in cmap for c in VI_SAMPLE)
    except Exception:
        return False


def license_warning(path: str) -> str:
    name = Path(path).name.lower()
    if any(r in name for r in RISKY_NAMES):
        return ("Font này có vẻ là font thương mại của hệ điều hành; không nên đóng kèm khi chia sẻ bản dịch. "
                "Nên dùng font mở như Noto Sans, Be Vietnam Pro, Roboto (giấy phép OFL/Apache).")
    return ""


def _font_dirs() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        return [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", home / "AppData/Local/Microsoft/Windows/Fonts"]
    if sys.platform == "darwin":
        return [Path("/Library/Fonts"), Path("/System/Library/Fonts"), home / "Library/Fonts"]
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".local/share/fonts", home / ".fonts"]


def find_system_fonts(limit: int = 25) -> list[str]:
    """Font hệ thống có đủ dấu tiếng Việt, ưu tiên font mở."""
    cands: list[Path] = []
    for d in _font_dirs():
        if d.is_dir():
            for p in d.rglob("*"):
                if p.suffix.lower() in (".ttf", ".otf"):
                    cands.append(p)
    cands.sort(key=lambda p: (not any(k in p.name.lower().replace("-", "") for k in PREFERRED), p.name.lower()))
    found: list[str] = []
    for p in cands[:600]:
        ok = supports_vietnamese(str(p))
        if ok:
            found.append(str(p))
            if len(found) >= limit:
                break
    return found
