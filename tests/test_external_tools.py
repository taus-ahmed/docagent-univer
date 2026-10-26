"""Every external program the engine starts has a deadline (Run 15, item 1).

A `pdftoppm -v` that never returned froze an OCR pool worker and the whole
suite for an hour. These tests stand in a SLOW PROGRAM for pdftoppm and
Tesseract (a Python process that sleeps, and starts a grandchild that sleeps)
and pin: the call is killed, its children with it; the failure is named; the
version probes run once and are handed to pool workers; the pool has a
per-page and a total deadline, and a cancel stops it — with no process left
behind in any of those cases.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import cancellation  # noqa: E402
import core.preprocessor as preprocessor  # noqa: E402
import external_tools  # noqa: E402
import ocr_source  # noqa: E402

#: A stand-in for a hung tool: records its pid and a grandchild's, then sleeps.
SLOW = textwrap.dedent("""
    import os, subprocess, sys, time
    out = os.environ["SLOW_PIDS"]
    kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(out, "a") as fh:
        fh.write(f"{os.getpid()} {kid.pid}\\n")
    time.sleep(120)
""")


def alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return code.value == 259                      # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    with open(f"/proc/{pid}/stat") as fh:
        return fh.read().split()[2] != "Z"


def pids(path: Path) -> list:
    if not path.exists():
        return []
    return [int(p) for line in path.read_text().split("\n") if line
            for p in line.split()]


def wait_dead(all_pids, within=15.0) -> list:
    end = time.monotonic() + within
    while time.monotonic() < end:
        left = [p for p in all_pids if alive(p)]
        if not left:
            return []
        time.sleep(0.2)
    return [p for p in all_pids if alive(p)]


@pytest.fixture
def slow(tmp_path, monkeypatch):
    """Every program started through external_tools becomes SLOW."""
    script = tmp_path / "slow.py"
    script.write_text(SLOW)
    record = tmp_path / "pids.txt"
    monkeypatch.setenv("SLOW_PIDS", str(record))

    class Slow(external_tools.ToolPopen):
        def __init__(self, args, *a, **kw):
            kw.pop("startupinfo", None)
            super().__init__([sys.executable, str(script)], *a, **kw)

    monkeypatch.setattr(external_tools, "ToolPopen", Slow)
    monkeypatch.setattr(external_tools, "_PROBES", {})
    for var in ("OCR_PROBE_TIMEOUT_S", "OCR_RENDER_TIMEOUT_S",
                "OCR_TESSERACT_TIMEOUT_S"):
        monkeypatch.setenv(var, "3")
    return record


def test_run_kills_the_program_and_its_children(slow):
    t0 = time.monotonic()
    with pytest.raises(external_tools.ToolTimeout, match="OCR_PROBE_TIMEOUT_S"):
        external_tools.run(["pdftoppm", "-v"], kind="probe")
    assert time.monotonic() - t0 < 30
    started = pids(slow)
    assert len(started) == 2
    assert wait_dead(started) == []


def test_a_hung_version_probe_is_a_named_failure_not_a_hang(slow, tmp_path):
    """THE BUG: pdf2image runs `pdftoppm -v` before every render, untimed."""
    pdf = bs.PDF_DIR / "CHQ-001847.pdf"
    t0 = time.monotonic()
    import pdf2image.pdf2image as p2i
    with pytest.raises(external_tools.ToolUnavailable,
                       match="pdftoppm version probe failed: ToolTimeout"):
        p2i._get_poppler_version("pdftoppm")
    assert time.monotonic() - t0 < 30
    with pytest.raises(external_tools.ToolUnavailable):   # remembered: no wait
        p2i._get_poppler_version("pdftoppm")
    assert time.monotonic() - t0 < 30
    assert len(pids(slow)) == 2, "the probe ran once"
    assert wait_dead(pids(slow)) == []


def test_a_hung_render_is_killed_and_named(slow, monkeypatch):
    monkeypatch.setitem(external_tools._PROBES, "pdftoppm", ("ok", (23, 13)))
    pdf = bs.PDF_DIR / "CHQ-001847.pdf"
    with pytest.raises(external_tools.ToolTimeout):
        ocr_source.render_pdf_page(pdf, 1, dpi=72)
    assert wait_dead(pids(slow)) == []


def test_a_hung_render_fails_THAT_PAGE_visibly(slow, monkeypatch):
    monkeypatch.setitem(external_tools._PROBES, "pdftoppm", ("ok", (23, 13)))
    read = preprocessor._ocr_read(str(bs.PDF_DIR / "CHQ-001847.pdf"), 1, dpi=72)
    assert read["error"].startswith("ToolTimeout: ")
    assert "OCR_RENDER_TIMEOUT_S" in read["error"]
    assert wait_dead(pids(slow)) == []


def test_a_hung_tesseract_is_killed_and_named(slow, monkeypatch):
    from PIL import Image
    from packaging.version import parse
    monkeypatch.setitem(external_tools._PROBES, "tesseract",
                        ("ok", parse("5.3.0")))
    import pytesseract
    original = pytesseract.pytesseract.subprocess.Popen

    def slow_popen(args, **kw):
        if "taskkill" in str(args[0]):
            return original(args, **kw)
        return original([sys.executable, str(slow.parent / "slow.py")], **kw)
    monkeypatch.setattr(pytesseract.pytesseract.subprocess, "Popen", slow_popen)
    with pytest.raises(external_tools.ToolTimeout,
                       match="OCR_TESSERACT_TIMEOUT_S"):
        ocr_source.OcrPageSource(Image.new("RGB", (60, 60), "white"),
                                 page_number=1, dpi=300)._read()
    assert wait_dead(pids(slow)) == []


def test_probes_run_once_per_process(monkeypatch):
    calls = []
    monkeypatch.setattr(external_tools, "_PROBES", {})
    monkeypatch.setattr(external_tools, "_ORIGINAL_POPPLER_VERSION",
                        lambda c, poppler_path=None, timeout=None:
                        calls.append(c) or (23, 13))
    for _ in range(5):
        assert external_tools.poppler_version("pdftoppm") == (23, 13)
    assert calls == ["pdftoppm"]


def test_a_seeded_worker_never_probes(monkeypatch):
    monkeypatch.setattr(external_tools, "_PROBES", {})

    def boom(*a, **k):
        raise AssertionError("a worker started a probe")
    monkeypatch.setattr(external_tools, "_ORIGINAL_POPPLER_VERSION", boom)
    external_tools.seed({"pdftoppm": ("ok", (23, 13))})
    assert external_tools.poppler_version("pdftoppm") == (23, 13)


def test_the_spawn_pool_hands_workers_the_parents_answers(monkeypatch):
    seen = {}
    monkeypatch.setattr(external_tools, "snapshot",
                        lambda: {"pdftoppm": ("ok", (23, 13))})

    class Recorder:
        def __init__(self, **kw):
            seen.update(kw)
    monkeypatch.setattr(preprocessor, "ProcessPoolExecutor", Recorder)
    preprocessor._spawn_pool(2)
    assert seen["initializer"] is external_tools.seed
    assert seen["initargs"] == ({"pdftoppm": ("ok", (23, 13))},)


def test_a_failed_probe_is_retried_after_its_ttl(monkeypatch):
    monkeypatch.setattr(external_tools, "_PROBES", {
        "pdftoppm": ("error", "ToolTimeout: x", time.monotonic() - 10_000)})
    monkeypatch.setattr(external_tools, "_ORIGINAL_POPPLER_VERSION",
                        lambda c, poppler_path=None, timeout=None: (23, 13))
    assert external_tools.poppler_version("pdftoppm") == (23, 13)


# ── the pool: a stuck worker is stopped, its page read serially ──────────────

def slow_reader(file_path, page_number, dpi=None, image=None):
    """Runs IN A SPAWNED WORKER: a page that never finishes reading."""
    out = os.environ["SLOW_PIDS"]
    kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(out, "a") as fh:
        fh.write(f"{os.getpid()} {kid.pid}\n")
    time.sleep(120)


@pytest.fixture
def stuck_pool(tmp_path, monkeypatch):
    record = tmp_path / "pids.txt"
    monkeypatch.setenv("SLOW_PIDS", str(record))
    monkeypatch.setenv("OCR_WORKERS", "2")
    monkeypatch.setattr(preprocessor, "_POOL_READER", slow_reader)
    monkeypatch.setattr(external_tools, "snapshot", lambda: {})
    monkeypatch.setattr(preprocessor, "_ocr_read",
                        lambda f, n, dpi=None, image=None:
                        {"error": "serial", "stats": {}, "dpi": 300})
    return record


def _started(record, n, within=60.0):
    end = time.monotonic() + within
    while time.monotonic() < end and len(pids(record)) < 2 * n:
        time.sleep(0.2)
    return pids(record)


def test_a_stuck_page_stops_the_pool_and_falls_back(stuck_pool, monkeypatch):
    monkeypatch.setenv("OCR_PAGE_TIMEOUT_S", "20")
    t0 = time.monotonic()
    reads = preprocessor._prefetch_ocr("x.pdf", [1, 2])
    took = time.monotonic() - t0
    assert took < 60
    assert set(reads) == {("x.pdf", 1), ("x.pdf", 2)}
    for read in reads.values():
        assert "OCR_PAGE_TIMEOUT_S" in read["pool_fallback"]
    started = pids(stuck_pool)
    assert len(started) == 4, "both workers should have started their page"
    left = wait_dead(started)
    assert left == [], (started, left)


def test_the_total_deadline_bounds_the_file(stuck_pool, monkeypatch):
    monkeypatch.setenv("OCR_PAGE_TIMEOUT_S", "600")
    monkeypatch.setenv("OCR_POOL_TIMEOUT_S", "20")
    t0 = time.monotonic()
    reads = preprocessor._prefetch_ocr("x.pdf", [1, 2])
    assert time.monotonic() - t0 < 60
    assert all("pool_fallback" in r for r in reads.values())
    assert wait_dead(pids(stuck_pool)) == []


def test_a_cancel_kills_the_workers_mid_page(stuck_pool, monkeypatch):
    monkeypatch.setenv("OCR_PAGE_TIMEOUT_S", "600")
    flag = threading.Event()

    def cancel_when_started():
        _started(stuck_pool, 2)
        flag.set()
    threading.Thread(target=cancel_when_started, daemon=True).start()
    t0 = time.monotonic()
    with cancellation.watching(flag.is_set):
        with pytest.raises(cancellation.Cancelled):
            preprocessor._prefetch_ocr("x.pdf", [1, 2])
    assert time.monotonic() - t0 < 90
    started = pids(stuck_pool)
    assert started
    assert wait_dead(started) == []
