"""Proof for the Image.getdata replacement in ocr_source._profile_variance.

Runs the preprocessor over every PDF and image under tests/ (and the three
tier PDFs built from tests/test_OCR) with OCR_WORKERS=1, so every skew
measurement happens in this process, and for every projection profile the
engine computes, compares the deprecated `getdata()` reading with the
`tobytes()` reading the engine now uses. Prints a JSON summary; exit 1 on any
difference.

    python -m tests.harness.getdata_identity
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

from tests.harness import bootstrap as bs

bs.bootstrap()

from core import preprocessor  # noqa: E402
from tests.harness.ocr_parallel_identity import IMAGES, tier_pdfs  # noqa: E402


def main() -> int:
    from PIL import Image
    os.environ["OCR_WORKERS"] = "1"
    stats = {"calls": 0, "differ": 0, "modes": {}}
    orig_resize = Image.Image.resize

    def resize(self, size, *a, **k):
        out = orig_resize(self, size, *a, **k)
        if size[0] == 1 and size[1] == self.height:       # the profile column
            stats["calls"] += 1
            stats["modes"][out.mode] = stats["modes"].get(out.mode, 0) + 1
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                old = list(out.getdata())
            if old != list(out.tobytes()):
                stats["differ"] += 1
        return out

    files = sorted(p for p in bs.TESTS_DIR.rglob("*")
                   if p.is_file() and (p.suffix.lower() == ".pdf"
                                       or p.suffix.lower() in IMAGES)
                   and "llm_cache" not in p.parts)
    files += tier_pdfs(Path(tempfile.mkdtemp()))
    Image.Image.resize = resize
    errors = 0
    try:
        for p in files:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    preprocessor.preprocess_file(p)
            except Exception:
                errors += 1
    finally:
        Image.Image.resize = orig_resize
    import PIL
    summary = {"pillow": PIL.__version__, "files": len(files), "errors": errors,
               **stats}
    print(json.dumps(summary), flush=True)
    return 1 if stats["differ"] or not stats["calls"] else 0


if __name__ == "__main__":
    sys.exit(main())
