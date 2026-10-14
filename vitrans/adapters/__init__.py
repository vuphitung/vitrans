from __future__ import annotations

from ..gamefs import GameFS
from .base import Adapter, PatchOptions
from .generic_json import GenericJsonAdapter
from .renpy import RenPyAdapter
from .rpgmaker import RPGMakerAdapter

ADAPTERS: list[type[Adapter]] = [RPGMakerAdapter, RenPyAdapter, GenericJsonAdapter]


def detect(fs: GameFS) -> list[tuple[type[Adapter], int]]:
    scored = [(a, a.detect(fs)) for a in ADAPTERS if a is not GenericJsonAdapter]
    scored = sorted([x for x in scored if x[1] > 0], key=lambda x: -x[1])
    if not scored:                          # phương án dự phòng: chỉ quét khi không có engine nào khớp
        s = GenericJsonAdapter.detect(fs)
        if s:
            scored = [(GenericJsonAdapter, s)]
    return scored


def get_adapter(adapter_id: str) -> type[Adapter]:
    for a in ADAPTERS:
        if a.id == adapter_id:
            return a
    raise KeyError(adapter_id)


__all__ = ["Adapter", "PatchOptions", "ADAPTERS", "detect", "get_adapter"]
