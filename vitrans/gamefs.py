"""Truy cập thư mục game an toàn: chặn thoát thư mục/symlink, sao lưu bản gốc, ghi nguyên tử, khôi phục."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

BACKUP_DIR = ".vitrans_backup"
MANIFEST = "manifest.json"
MAX_READ = 64 * 1024 * 1024          # không đọc tệp lớn hơn mức này vào bộ nhớ
MAX_FILES = 20000                    # giới hạn số tệp khi quét thư mục
_SKIP_DIRS = {BACKUP_DIR, "node_modules", ".git"}


class UnsafePathError(ValueError):
    pass


class GameFileError(ValueError):
    pass


def safe_join(root: Path, rel: str) -> Path:
    if "\x00" in rel:
        raise UnsafePathError("Đường dẫn chứa ký tự NUL")
    root = Path(root).resolve()
    p = (root / rel).resolve()
    if p != root and not p.is_relative_to(root):
        raise UnsafePathError(f"Đường dẫn ra ngoài thư mục cho phép: {rel}")
    return p


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(dest: Path, data: bytes) -> None:
    """Ghi tệp tạm cùng thư mục rồi đổi tên; giữ nguyên quyền của tệp cũ (mkstemp mặc định là 600)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o644
    try:
        if dest.exists():
            mode = stat.S_IMODE(dest.stat().st_mode)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".vitrans_tmp_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class GameFS:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(str(root))
        self.restore_skipped: list[str] = []

    @property
    def backup_root(self) -> Path:
        return self.root / BACKUP_DIR

    def path(self, rel: str) -> Path:
        return safe_join(self.root, rel)

    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    @staticmethod
    def _read_limited(p: Path) -> bytes:
        if p.stat().st_size > MAX_READ:
            raise GameFileError(f"Tệp quá lớn (> {MAX_READ // 2**20} MB): {p.name}")
        return p.read_bytes()

    def read_bytes(self, rel: str) -> bytes:
        """Trả về bản GỐC của tệp.

        Bản sao lưu chỉ được coi là bản gốc khi tệp đang nằm trong game vẫn đúng là bản mình đã ghi.
        Nếu tệp đã bị đổi từ bên ngoài (game tự cập nhật, người dùng chép lại...), tệp hiện tại mới là sự thật.
        """
        live = self.path(rel)
        m = self._load_manifest()
        if rel in m["backed_up"]:
            b = safe_join(self.backup_root, rel)
            if b.is_file():
                w = m["written"].get(rel)
                if w is not None and (not live.is_file() or _sha(self._read_limited(live)) == w):
                    return self._read_limited(b)
        return self._read_limited(live)

    def rglob(self, pattern: str, under: str = "") -> list[str]:
        base = self.path(under) if under else self.root
        out: list[str] = []
        if not base.is_dir():
            return out
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for f in filenames:
                if fnmatch.fnmatch(f, pattern):
                    fp = Path(dirpath, f)
                    if fp.is_symlink():                  # không bao giờ đi theo liên kết tượng trưng
                        continue
                    out.append(fp.relative_to(self.root).as_posix())
                    if len(out) >= MAX_FILES:
                        return sorted(out)
        return sorted(out)

    def listdir(self, under: str, pattern: str = "*") -> list[str]:
        base = self.path(under) if under else self.root
        if not base.is_dir():
            return []
        return sorted(
            (Path(under) / p.name).as_posix() if under else p.name
            for p in base.iterdir()
            if p.is_file() and not p.is_symlink() and fnmatch.fnmatch(p.name, pattern)
        )

    # --- sao lưu / ghi / khôi phục -------------------------------------------------
    def _manifest_path(self) -> Path:
        return self.backup_root / MANIFEST

    def _valid_rel(self, rel) -> bool:
        if not isinstance(rel, str) or not rel:
            return False
        try:
            safe_join(self.root, rel)
            safe_join(self.backup_root, rel)
            return True
        except ValueError:
            return False

    def _load_manifest(self) -> dict:
        """Đọc manifest và loại bỏ mọi mục không hợp lệ (manifest nằm trong thư mục game nên không được tin tưởng)."""
        m: dict = {"backed_up": [], "created": [], "written": {}}
        p = self._manifest_path()
        if p.is_file() and not p.is_symlink():
            try:
                raw = json.loads(self._read_limited(p).decode("utf-8"))
            except (OSError, ValueError, GameFileError):
                raw = {}
            if isinstance(raw, dict):
                for key in ("backed_up", "created"):
                    lst = raw.get(key)
                    if isinstance(lst, list):
                        m[key] = [r for r in lst if self._valid_rel(r)]
                w = raw.get("written")
                if isinstance(w, dict):
                    m["written"] = {k: v for k, v in w.items() if self._valid_rel(k) and isinstance(v, str)}
        return m

    def _save_manifest(self, m: dict) -> None:
        self.backup_root.mkdir(parents=True, exist_ok=True)
        _atomic_write(self._manifest_path(), json.dumps(m, indent=1).encode("utf-8"))

    def has_backup(self) -> bool:
        return self._manifest_path().is_file()

    def write_files(self, files: dict[str, bytes]) -> list[str]:
        for rel in files:                       # kiểm tra toàn bộ đường dẫn trước khi ghi bất cứ thứ gì
            self.path(rel)
            safe_join(self.backup_root, rel)
        m = self._load_manifest()
        written = []
        for rel, data in files.items():
            dest = self.path(rel)
            live_hash = _sha(self._read_limited(dest)) if dest.is_file() else None
            if rel in m["backed_up"]:
                w = m["written"].get(rel)
                if live_hash is not None and w is not None and live_hash != w:
                    # game đã tự cập nhật/chỉnh sửa tệp này sau lần vá trước: bản hiện tại là bản gốc mới
                    shutil.copy2(dest, safe_join(self.backup_root, rel))
            elif rel not in m["created"]:
                if dest.exists():
                    bp = safe_join(self.backup_root, rel)
                    bp.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, bp)
                    m["backed_up"].append(rel)
                else:
                    m["created"].append(rel)
            m["written"][rel] = _sha(data)
            self._save_manifest(m)               # lưu TRƯỚC khi ghi: nếu sập giữa chừng vẫn khôi phục được
            _atomic_write(dest, data)
            written.append(rel)
        return written

    def restore(self) -> int:
        """Trả về số tệp đã khôi phục/xóa. Tệp đã bị game cập nhật sau khi vá được giữ nguyên (xem restore_skipped)."""
        self.restore_skipped = []
        if not self.has_backup():
            return 0
        m = self._load_manifest()
        n = 0
        for rel in m["backed_up"]:
            src = safe_join(self.backup_root, rel)
            if not src.is_file():
                continue
            dest = self.path(rel)
            w = m["written"].get(rel)
            # chỉ khôi phục khi chắc chắn tệp hiện tại là bản do mình ghi (manifest nằm trong thư mục game nên không đáng tin)
            if w is None or (dest.is_file() and _sha(self._read_limited(dest)) != w):
                self.restore_skipped.append(rel)
                continue
            _atomic_write(dest, self._read_limited(src))
            n += 1
        for rel in m["created"]:
            p = self.path(rel)
            if not p.is_file():
                continue
            w = m["written"].get(rel)
            if w is None or _sha(self._read_limited(p)) != w:
                self.restore_skipped.append(rel)
                continue
            p.unlink()
            n += 1
            parent = p.parent
            while parent != self.root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        shutil.rmtree(self.backup_root, ignore_errors=True)
        return n


def export_files(out_dir, files: dict[str, bytes]) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for rel in files:
        safe_join(out, rel)
    done = []
    for rel, data in files.items():
        _atomic_write(safe_join(out, rel), data)
        done.append(rel)
    return done
