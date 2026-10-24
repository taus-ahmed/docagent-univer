"""Parallel OCR in the preprocessor (docs/proposals/throughput.md, item 1).

A file's pages needing OCR are read in a process pool and folded back IN PAGE
ORDER, so the result is the serial result: same texts, same words and boxes,
same origins, same OCR metadata, same notes. A pool that cannot start or
breaks mid-file falls back to reading serially and says so on the page's OCR
record (`pool_fallback`); it never changes what was read.

The pool is exercised two ways: with injected executors (ordering, fallback —
no process start, so these run anywhere), and with the real spawn pool on a
generated multi-page scan (determinism).
"""
from __future__ import annotations

import hashlib
import os
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import core.preprocessor as preprocessor  # noqa: E402
from ocr_source import available  # noqa: E402

TESSERACT = available()[0]
needs_tesseract = pytest.mark.skipif(
    not TESSERACT, reason="Tesseract not installed: OCR cannot run")


def _scan_pdf(tmp_path: Path, n: int) -> Path:
    from PIL import Image
    src = sorted((bs.TESTS_DIR / "test_OCR").glob("chk_*_clean.png"))
    imgs = [Image.open(src[i % len(src)]).convert("RGB") for i in range(n)]
    out = tmp_path / f"scan_{n}.pdf"
    imgs[0].save(out, "PDF", save_all=True, append_images=imgs[1:],
                 resolution=150)
    return out


def snapshot(doc, drop=("pool_fallback",)):
    """Everything the preprocessor produced, images as digests."""
    d = dict(vars(doc))
    d["ocr_images"] = {
        n: (im.mode, im.size, hashlib.sha256(im.tobytes()).hexdigest(), dpi)
        for n, (im, dpi) in sorted(doc.ocr_images.items())}
    d["ocr_pages"] = [{k: v for k, v in e.items() if k not in drop}
                      for e in doc.ocr_pages]
    return d


def _run(path, monkeypatch, workers, factory=None):
    monkeypatch.setenv("OCR_WORKERS", str(workers))
    if factory is not None:
        monkeypatch.setattr(preprocessor, "_POOL_FACTORY", factory)
    return preprocessor.preprocess_file(path)


class TestWorkerCount:
    @pytest.mark.parametrize("raw,want", [
        ("1", 1), ("3", 3), ("0", 1), ("-2", 1)])
    def test_explicit(self, monkeypatch, raw, want):
        monkeypatch.setenv("OCR_WORKERS", raw)
        assert preprocessor.ocr_workers() == want

    @pytest.mark.parametrize("raw", [None, "", "four"])
    def test_default_is_min_4_cpu(self, monkeypatch, raw):
        if raw is None:
            monkeypatch.delenv("OCR_WORKERS", raising=False)
        else:
            monkeypatch.setenv("OCR_WORKERS", raw)
        assert preprocessor.ocr_workers() == min(4, os.cpu_count() or 1)


class _ReverseExecutor:
    """Runs every task in-process but resolves futures in REVERSE order of
    submission, so a fold that trusted completion order would misplace pages."""

    def __init__(self, max_workers=None, **_):
        self.jobs = []

    def submit(self, fn, *args):
        f = Future()
        self.jobs.append((f, fn, args))
        return f

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for f, fn, args in reversed(self.jobs):
            f.set_result(fn(*args))
        return False


class _ReverseThenWait(_ReverseExecutor):
    """As above, but resolves when the first result is asked for."""

    def submit(self, fn, *args):
        f = super().submit(fn, *args)
        orig = f.result

        def result(timeout=None):
            if not f.done():
                for g, fn2, a in reversed(self.jobs):
                    if not g.done():
                        g.set_result(fn2(*a))
            return orig(timeout)
        f.result = result
        return f


class _BrokenExecutor(_ReverseExecutor):
    def submit(self, fn, *args):
        f = Future()
        f.set_exception(BrokenProcessPool("a worker died"))
        return f

    def __exit__(self, *exc):
        return False


def _no_pool(**_):
    raise OSError("cannot start a process")


@needs_tesseract
class TestOrderAndFallback:
    def test_out_of_order_completion_folds_in_page_order(self, tmp_path, monkeypatch):
        pdf = _scan_pdf(tmp_path, 3)
        serial = snapshot(_run(pdf, monkeypatch, 1))
        pooled = snapshot(_run(pdf, monkeypatch, 3, _ReverseThenWait))
        assert pooled == serial
        assert [e["page"] for e in pooled["ocr_pages"]] == [1, 2, 3]

    def test_pool_that_cannot_start_falls_back_serially(self, tmp_path, monkeypatch):
        pdf = _scan_pdf(tmp_path, 2)
        serial = _run(pdf, monkeypatch, 1)
        fell = _run(pdf, monkeypatch, 2, _no_pool)
        assert snapshot(fell) == snapshot(serial)
        for e in fell.ocr_pages:
            assert "OSError" in e["pool_fallback"]
        assert all("pool_fallback" not in e for e in serial.ocr_pages)

    def test_broken_pool_mid_file_falls_back_serially(self, tmp_path, monkeypatch):
        pdf = _scan_pdf(tmp_path, 2)
        serial = _run(pdf, monkeypatch, 1)
        fell = _run(pdf, monkeypatch, 2, _BrokenExecutor)
        assert snapshot(fell) == snapshot(serial)
        assert all("BrokenProcessPool" in e["pool_fallback"]
                   for e in fell.ocr_pages)

    def test_a_page_that_fails_ocr_is_recorded_the_same_way(self, tmp_path, monkeypatch):
        """A failure INSIDE the reader is the page's failure, not the pool's:
        listed in ocr_failed_pages with the same note, no fallback mark."""
        pdf = _scan_pdf(tmp_path, 2)
        monkeypatch.setattr("ocr_source.render_pdf_page",
                            lambda *a, **k: None)
        serial = _run(pdf, monkeypatch, 1)
        pooled = _run(pdf, monkeypatch, 2, _ReverseThenWait)
        assert serial.ocr_failed_pages == [1, 2]
        assert snapshot(pooled, drop=()) == snapshot(serial, drop=())

    def test_one_page_never_starts_a_pool(self, tmp_path, monkeypatch):
        pdf = _scan_pdf(tmp_path, 1)
        doc = _run(pdf, monkeypatch, 4, _no_pool)
        assert all("pool_fallback" not in e for e in doc.ocr_pages)


@needs_tesseract
def test_spawn_pool_is_byte_identical_to_serial(tmp_path, monkeypatch):
    """The real pool (spawn, separate processes): every field identical."""
    pdf = _scan_pdf(tmp_path, 3)
    serial = snapshot(_run(pdf, monkeypatch, 1))
    monkeypatch.setenv("OCR_WORKERS", "3")
    pooled = preprocessor.preprocess_file(pdf)
    assert all("pool_fallback" not in e for e in pooled.ocr_pages), \
        [e.get("pool_fallback") for e in pooled.ocr_pages]
    assert snapshot(pooled, drop=()) == serial
