"""Dòng lệnh: vitrans [gui|scan|translate|apply|export|restore|stats] GAME ..."""
from __future__ import annotations

import argparse
import sys
import threading

from .config import AppConfig
from .models import STATUS_LABEL, UnsupportedGameError
from .project import Project
from .providers import ProviderError


def _open(args) -> Project:
    return Project(args.game, engine=getattr(args, "engine", None))


def _cfg(args) -> AppConfig:
    cfg = AppConfig()
    if getattr(args, "provider", None):
        cfg["provider"] = args.provider
    if getattr(args, "font", None):
        cfg["font_path"] = args.font
    return cfg


def cmd_scan(args) -> int:
    p = _open(args)
    info = p.scan()
    print(f"Engine: {p.adapter.label} | mới {info['added']}, giữ {info['kept']}, đổi {info['changed']}, bỏ {info['removed']}")
    print(f"Tổng số câu: {len(p.entries)}")
    return 0


def cmd_stats(args) -> int:
    p = _open(args)
    for k, n in sorted(p.store.stats().items()):
        print(f"{STATUS_LABEL.get(k, k):10s} {n}")
    return 0


def cmd_translate(args) -> int:
    p, cfg = _open(args), _cfg(args)
    if not p.entries:
        p.scan()
    cancel = threading.Event()

    def progress(done, total, msg):
        print(f"\r{msg}   ", end="", flush=True)

    try:
        res = p.translate(cfg, progress=progress, cancel=cancel)
    except KeyboardInterrupt:
        cancel.set()
        print("\nĐã dừng.")
        return 130
    except ProviderError as ex:
        print(f"\nLỗi: {ex}", file=sys.stderr)
        return 2
    print(f"\nDịch mới: {res.translated} | dùng lại: {res.reused} | lỗi: {res.failed}")
    return 0 if not res.failed else 1


def cmd_apply(args) -> int:
    p, cfg = _open(args), _cfg(args)
    files = p.apply(cfg)
    print(f"Đã ghi {len(files)} tệp (bản gốc được sao lưu trong .vitrans_backup).")
    return 0


def cmd_export(args) -> int:
    p, cfg = _open(args), _cfg(args)
    files = p.export(cfg, args.out)
    print(f"Đã xuất {len(files)} tệp vào {args.out} (chỉ gồm các tệp bản vá, không chứa toàn bộ game).")
    return 0


def cmd_restore(args) -> int:
    p = _open(args)
    n = p.restore()
    print(f"Đã khôi phục {n} tệp gốc.")
    if p.fs.restore_skipped:
        print(f"Giữ nguyên {len(p.fs.restore_skipped)} tệp vì game đã cập nhật sau khi vá: "
              + ", ".join(p.fs.restore_skipped[:5]))
    return 0


def cmd_gui(args) -> int:
    from .ui.app import run_gui
    return run_gui(getattr(args, "game", None))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vitrans", description="Dịch game indie sang tiếng Việt")
    sub = ap.add_subparsers(dest="cmd")

    def add(name, fn, help_, game=True):
        sp = sub.add_parser(name, help=help_)
        if game:
            sp.add_argument("game", help="Thư mục game")
        sp.add_argument("--engine", choices=["rpgmaker", "renpy", "generic_json"], help="Ép loại game")
        sp.set_defaults(fn=fn)
        return sp

    g = add("gui", cmd_gui, "Mở giao diện", game=False)
    g.add_argument("game", nargs="?")
    add("scan", cmd_scan, "Quét và trích chữ")
    add("stats", cmd_stats, "Thống kê trạng thái")
    t = add("translate", cmd_translate, "Dịch các câu còn chờ")
    t.add_argument("--provider", choices=["anthropic", "openai", "google", "echo"])
    a = add("apply", cmd_apply, "Ghi bản dịch vào game (có sao lưu)")
    a.add_argument("--font", help="Font .ttf/.otf hỗ trợ tiếng Việt")
    e = add("export", cmd_export, "Xuất riêng bản vá")
    e.add_argument("out", help="Thư mục xuất")
    e.add_argument("--font")
    add("restore", cmd_restore, "Khôi phục bản gốc")

    args = ap.parse_args(argv)
    if not args.cmd:
        args = ap.parse_args(["gui"])
    try:
        return args.fn(args)
    except UnsupportedGameError as ex:
        print(f"Không hỗ trợ: {ex}", file=sys.stderr)
        return 3
    except ProviderError as ex:
        print(f"Lỗi nhà cung cấp dịch: {ex}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as ex:
        print(f"Lỗi: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
