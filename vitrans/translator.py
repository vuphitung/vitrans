"""Điều phối dịch: gom câu trùng, thêm ngữ cảnh, chia lô, chạy song song, kiểm tra nghiêm ngặt, thử lại."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from . import glossary as gl
from .adapters.base import Adapter
from .models import ERROR, MACHINE, PENDING, REVIEWED, Entry, Style, Term
from .providers import BatchItem, Provider, ProviderError, ProviderFatalError
from .textutil import clean_text

MAX_SOURCE = 20000        # câu gốc dài hơn mức này: không gửi đi, để người dùng tự xử lý
MAX_RATIO = 8             # bản dịch dài hơn 8 lần bản gốc (+500 ký tự) bị coi là bất thường
MAX_CONSECUTIVE_BATCH_ERRORS = 3


@dataclass
class Job:
    id: str
    source: str
    masked: str
    tokens: list[str]
    speaker: str
    context: list[str]
    entries: list[Entry]
    err: str = ""          # lỗi phía nhà cung cấp (mạng, HTTP...)
    reason: str = ""       # lý do bản dịch bị từ chối khi kiểm tra


@dataclass
class RunResult:
    translated: int = 0
    reused: int = 0
    failed: int = 0
    cancelled: bool = False


def needs_translation(e: Entry, only_keys, force: bool) -> bool:
    if only_keys is not None:
        if e.key not in only_keys:
            return False
        return True if force else e.status in (PENDING, ERROR)   # chọn tay + force: kể cả câu đang "bỏ qua"/đã duyệt
    return e.status in (PENDING, ERROR)


def estimate(entries: list[Entry], only_keys=None, force: bool = False) -> tuple[int, int]:
    """(số câu duy nhất sẽ gửi đi, tổng số ký tự) — để người dùng biết trước khi dịch."""
    known = {e.source for e in entries if e.status in (MACHINE, REVIEWED) and e.translation}
    uniq: dict[str, int] = {}
    for e in entries:
        if needs_translation(e, only_keys, force) and (force or e.source not in known):
            uniq[e.source] = len(e.source)
    return len(uniq), sum(uniq.values())


class Translator:
    def __init__(self, store, adapter: Adapter, provider: Provider, style: Style, glossary: list[Term], *,
                 batch_chars: int = 3500, batch_items: int = 25, context_lines: int = 3,
                 concurrency: int = 2, retries: int = 1):
        self.store, self.adapter, self.provider = store, adapter, provider
        self.style, self.glossary = style, glossary
        self.batch_chars, self.batch_items = batch_chars, batch_items
        self.context_lines, self.concurrency, self.retries = context_lines, max(1, concurrency), max(0, retries)
        self.prot = adapter.protector()
        self._streak_lock = threading.Lock()
        self._streak = 0
        self._last_err = ""
        self._tripped = threading.Event()      # cầu dao: quá nhiều lô lỗi liên tiếp -> ngừng gọi nhà cung cấp ngay

    def run(self, entries: list[Entry], *, only_keys=None, force: bool = False, progress=None,
            cancel: threading.Event | None = None, on_update=None) -> RunResult:
        res = RunResult()
        self._streak, self._last_err = 0, ""
        self._tripped.clear()
        ordered = sorted(entries, key=lambda e: e.order)
        pos = {e.key: i for i, e in enumerate(ordered)}
        known = {e.source: e.translation for e in ordered if e.status in (MACHINE, REVIEWED) and e.translation}
        groups: dict[str, list[Entry]] = {}
        for e in ordered:
            if needs_translation(e, only_keys, force):
                groups.setdefault(e.source, []).append(e)

        changed: list[Entry] = []

        def commit(es, text, status, warn=""):
            for e in es:
                e.translation, e.status, e.warn = text, status, warn
            changed.extend(es)

        try:
            jobs: list[Job] = []
            for src, es in groups.items():
                if not force and src in known:                  # đã có bản dịch đúng câu này: dùng lại, không tốn API
                    commit(es, known[src], MACHINE)
                    res.reused += len(es)
                    continue
                if len(src) > MAX_SOURCE:
                    commit(es, "", ERROR, f"Câu quá dài (> {MAX_SOURCE} ký tự): hãy dịch tay hoặc bỏ qua")
                    res.failed += len(es)
                    continue
                masked, tokens = self.prot.mask(src)
                if not self.prot.translatable(masked):          # chỉ gồm mã/ký hiệu: giữ nguyên
                    commit(es, src, MACHINE)
                    res.reused += len(es)
                    continue
                first = es[0]
                i = pos[first.key]
                ctx = [self.prot.plain(p.source)[:200] for p in ordered[max(0, i - self.context_lines):i]
                       if p.file == first.file]
                jobs.append(Job(str(len(jobs)), src, masked, tokens, first.speaker, ctx, es))
            self._flush(changed, on_update)

            total, done = len(jobs), 0
            if progress:
                progress(0, total, "Bắt đầu dịch" if total else "Không có câu nào cần dịch")
            pending = jobs
            for rnd in range(self.retries + 1):
                if not pending or (cancel and cancel.is_set()):
                    break
                if rnd == 0:
                    batches = self._batches(pending)
                else:       # lỗi nhà cung cấp: thử lại cả lô; lỗi kiểm tra: tách từng câu để cô lập câu hỏng
                    batches = self._batches([j for j in pending if j.err]) + [[j] for j in pending if not j.err]
                failed: list[Job] = []
                ex = ThreadPoolExecutor(max_workers=self.concurrency)
                futs = [ex.submit(self._call, b, cancel) for b in batches]
                try:
                    for fut in as_completed(futs):
                        batch, out, err = fut.result()
                        if err == "cancelled":
                            continue
                        for j in batch:
                            j.err = err or ""
                            raw = out.get(j.id)
                            acc = self._accept(j, raw) if raw is not None else None
                            if acc is None:
                                if raw is None and not err:
                                    j.reason = "Mô hình không trả kết quả cho câu này"
                                failed.append(j)
                            else:
                                commit(j.entries, acc[0], MACHINE, acc[1])
                                done += 1
                                res.translated += len(j.entries)
                        self._flush(changed, on_update)
                        if progress:
                            progress(done, total, f"Đã dịch {done}/{total}")
                        if self._tripped.is_set():
                            raise ProviderFatalError(
                                f"{MAX_CONSECUTIVE_BATCH_ERRORS} lô liên tiếp bị lỗi nên đã dừng. "
                                f"Lỗi gần nhất: {self._last_err}")
                except ProviderFatalError:
                    for f in futs:
                        f.cancel()
                    raise
                finally:
                    ex.shutdown(wait=True, cancel_futures=True)
                pending = failed
            if cancel and cancel.is_set():
                res.cancelled = True
            else:
                for j in pending:
                    commit(j.entries, "", ERROR, j.err or j.reason or "Dịch thất bại")
                    res.failed += len(j.entries)
            if progress:
                progress(done if res.cancelled else total, total, "Đã dừng" if res.cancelled else "Hoàn tất")
            return res
        finally:
            self._flush(changed, on_update)      # kể cả khi lỗi nghiêm trọng, phần đã dịch vẫn được lưu

    # --- nội bộ ------------------------------------------------------------------------------
    def _flush(self, changed: list[Entry], on_update) -> None:
        if not changed:
            return
        batch = list({e.key: e for e in changed}.values())
        changed.clear()
        self.store.update_entries(batch)
        if on_update:
            on_update([e.key for e in batch])

    def _batches(self, jobs: list[Job]) -> list[list[Job]]:
        out, cur, size = [], [], 0
        for j in jobs:
            n = len(j.masked) + sum(len(c) for c in j.context) + 40
            if cur and (size + n > self.batch_chars or len(cur) >= self.batch_items):
                out.append(cur)
                cur, size = [], 0
            cur.append(j)
            size += n
        if cur:
            out.append(cur)
        return out

    def _call(self, batch: list[Job], cancel):
        """Một lô lỗi (kể cả lỗi bất ngờ như JSON hỏng) không được làm sập cả lượt dịch."""
        if (cancel and cancel.is_set()) or self._tripped.is_set():
            return batch, {}, "cancelled"
        items = [BatchItem(j.id, j.masked, j.speaker, j.context) for j in batch]
        terms = gl.relevant(self.glossary, " ".join(j.source for j in batch))
        try:
            out = self.provider.translate_batch(items, self.style, terms)
        except ProviderFatalError:
            raise
        except ProviderError as ex:
            return batch, {}, self._record_error(str(ex))
        except Exception as ex:  # noqa: BLE001
            return batch, {}, self._record_error(f"{type(ex).__name__}: {ex}")
        with self._streak_lock:
            self._streak = 0
        return batch, out, None

    def _record_error(self, msg: str) -> str:
        with self._streak_lock:
            self._streak += 1
            self._last_err = msg
            if self._streak >= MAX_CONSECUTIVE_BATCH_ERRORS:
                self._tripped.set()
        return msg

    def _accept(self, j: Job, raw: str):
        """Kiểm tra nghiêm ngặt một bản dịch; trả về (text, cảnh báo) hoặc None kèm j.reason."""
        raw = clean_text(raw)                                   # NFC + bỏ ký tự vô hình/điều khiển (trên bản còn mã che)
        problems = self.prot.check(raw, j.tokens)
        if problems:
            j.reason = "Sai mã định dạng: " + "; ".join(problems)
            return None
        text = self.prot.unmask(raw, j.tokens).strip()
        if not text:
            j.reason = "Bản dịch trống"
            return None
        # Bản dịch không được chứa mã điều khiển/biến mà bản gốc không có (AI tự chèn = nguy cơ lỗi/độc hại)
        if sorted(self.prot.tokens_of(text)) != sorted(j.tokens):
            j.reason = "Bản dịch chứa mã điều khiển lạ hoặc sai mã so với bản gốc"
            return None
        extra = self.adapter.validate(text)
        if extra:
            j.reason = "; ".join(extra)
            return None
        if len(text) > MAX_RATIO * len(j.source) + 500:
            j.reason = "Bản dịch dài bất thường so với bản gốc"
            return None
        text = self.adapter.finalize(text)
        warns = []
        miss = gl.missing(self.glossary, j.source, text)
        if miss:
            warns.append("Chưa dùng thuật ngữ: " + ", ".join(f"{t.src}→{t.vi}" for t in miss))
        if len(text) > 1.8 * len(j.source) + 15:
            warns.append("Bản dịch dài hơn nhiều so với bản gốc")
        return text, "; ".join(warns)
