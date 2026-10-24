# Measurement script for docs/proposals/throughput.md (run: python tests/harness/throughput.py OUT.json).
"""Throughput of the OCR path on synthetic cheque pages (no model call).
Times render, orientation, skew detection + straighten, OCR (tesseract), and
the reader seam's line building, per page, for 1, 10 and 50 pages; then a
parallel run of the same 50 pages with a process pool.
usage: python throughput.py OUT.json"""
import contextlib, io, json, os, sys, time, tempfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, ".")
from tests.harness import bootstrap as bs
bs.bootstrap()

T = defaultdict(float)


def timed(mod, name, key):
    f = getattr(mod, name)
    def w(*a, **k):
        t = time.perf_counter()
        try:
            return f(*a, **k)
        finally:
            T[key] += time.perf_counter() - t
    setattr(mod, name, w)


def build(n, path):
    from PIL import Image
    imgs = []
    files = sorted((bs.TESTS_DIR / "test_OCR").glob("chk_*_clean.png"))
    files += sorted((bs.TESTS_DIR / "test_OCR").glob("chk_*_moderate.jpg"))
    for i in range(n):
        imgs.append(Image.open(files[i % len(files)]).convert("RGB"))
    imgs[0].save(path, "PDF", save_all=True, append_images=imgs[1:], resolution=150)


def run_one(path):
    import ocr_source, pytesseract
    from core import preprocessor
    import text_layer
    timed(ocr_source, "render_pdf_page", "render")
    timed(preprocessor, "render_pdf_page", "render") if hasattr(preprocessor, "render_pdf_page") else None
    timed(ocr_source, "orientation", "orientation")
    timed(ocr_source, "skew_angle", "deskew_detect")
    timed(ocr_source, "straighten", "straighten_total")
    timed(pytesseract, "image_to_data", "tesseract")
    timed(preprocessor, "read_page", "read_page_total")
    t = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        doc = preprocessor.preprocess_file(path)
    total = time.perf_counter() - t
    return total, len(doc.page_texts), dict(T)


def page_task(args):
    path, n = args
    import ocr_source
    from core.preprocessor import ProcessedDocument, _ocr_page
    d = ProcessedDocument(source_path=str(path), filename="x", file_type="pdf", total_pages=0)
    with contextlib.redirect_stdout(io.StringIO()):
        text, lines, _r = _ocr_page(Path(path), n, d, {})
    return n, sum(len(l) for l in lines)


if __name__ == "__main__":
    out = {"cpu_count": os.cpu_count()}
    tmp = Path(tempfile.mkdtemp())
    for n in (1, 10, 50):
        p = tmp / f"cheques_{n}.pdf"
        build(n, p)
        T.clear()
        total, pages, parts = run_one(p) if n == 1 else (None, None, None)
        if n != 1:
            import importlib
            T.clear()
            from core import preprocessor
            t = time.perf_counter()
            with contextlib.redirect_stdout(io.StringIO()):
                doc = preprocessor.preprocess_file(p)
            total, pages, parts = time.perf_counter() - t, len(doc.page_texts), dict(T)
        out[f"serial_{n}"] = {"pages": pages, "seconds": round(total, 2),
                              "per_page": round(total / max(pages, 1), 2),
                              "parts": {k: round(v, 2) for k, v in parts.items()}}
        print(n, out[f"serial_{n}"], flush=True)
    p = tmp / "cheques_50.pdf"
    for workers in (2, 4):
        t = time.perf_counter()
        with ProcessPoolExecutor(max_workers=workers) as ex:
            words = dict(ex.map(page_task, [(str(p), k) for k in range(1, 51)]))
        el = time.perf_counter() - t
        out[f"pool_{workers}_50"] = {"seconds": round(el, 2), "per_page": round(el / 50, 2),
                                     "pages_with_words": sum(1 for v in words.values() if v)}
        print(workers, out[f"pool_{workers}_50"], flush=True)
    json.dump(out, open(sys.argv[1], "w"), indent=1)
