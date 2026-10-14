"""Vị trí lưu dữ liệu của ứng dụng (cơ sở dữ liệu dự án, cấu hình)."""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("VITRANS_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "vitrans"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "vitrans"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "vitrans"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform != "win32":
        try:
            os.chmod(base, 0o700)            # thư mục chứa cấu hình/khóa API: chỉ chủ sở hữu truy cập
        except OSError:
            pass
    return base


def project_db_path(game_root: Path) -> Path:
    root = Path(game_root).resolve()
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^\w.-]", "_", root.name) or "game"
    d = data_dir() / "projects"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d / f"{safe}-{digest}.db"
