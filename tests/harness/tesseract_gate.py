"""Which Tesseract reads the page, and the tests whose OUTCOME depends on it
(Recheck 2, the CI failure).

Measured 2026-10-28 on the generated scan variants (tests/fixtures/
make_scan_variants.py), fields of the manifest found in the reading:

    reader                       all scan pages   scan_hard_single   scan_batch_10pages
    Tesseract 5.4.0 (Windows)    164 / 240        4 / 8 (retry)      10 records
    Tesseract 5.3.0 (Docker,     161 / 240        1 / 8 (no retry)    9 records: pages 7+8
      the production image)                                           one, flagged
    Tesseract 5.3.4 (CI)         the same three test failures as 5.3.0

Every other page reads the same field count on both. The two differences are
real readings, not geometry: on 5.3 psm 3 finds a few words on the hard scan,
so the zero-word retry (crop, psm 6) never runs; and page 8's MICR band reads
`AG06474687A … 723430980500` (a 0 read as G, the closing symbol lost), so no
band-change boundary is found. That merge fails CLOSED: the record carries
`possible_multiple_documents` and `needs_review`.

`BELOW_5_4` marks exactly those outcome tests xfail(strict=True) on an older
reader: on 5.4+ they run unchanged, and the day an older reader passes them
the unexpected pass FAILS and the marker has to go. The fail-closed outcome
is asserted on EVERY reader by tests that are never marked.
"""
from __future__ import annotations

import re


def tesseract_version():
    """(major, minor) of the Tesseract binary, or None when there is none."""
    try:
        import ocr_source
        ok, v = ocr_source.available()
    except Exception:                       # pragma: no cover - environment
        return None
    m = re.search(r"(\d+)\.(\d+)", v) if ok else None
    return (int(m.group(1)), int(m.group(2))) if m else None


_V = tesseract_version()
BELOW_5_4 = _V is not None and _V < (5, 4)
REASON = (f"Tesseract {_V and '.'.join(map(str, _V))} reads this scan worse than 5.4 "
          "(measured: tests/harness/tesseract_gate.py); the outcome is still flagged")
