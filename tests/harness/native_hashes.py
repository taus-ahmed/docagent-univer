"""Fingerprint of the preprocessor's reading of every corpus PDF.

sha256 (first 16 hex) of each PDF's page texts, page origins, word lists
(text, x0, top) and extracted text. The recorded set is
tests/reports/native_hashes.json; a change to any reading changes its hash.

    python -m tests.harness.native_hashes OUT.json            # write
    python -m tests.harness.native_hashes --check             # compare
"""
import contextlib
import hashlib
import io
import json
import sys

from tests.harness import bootstrap as bs

bs.bootstrap()
from core.preprocessor import preprocess_file  # noqa: E402

BASELINE = bs.TESTS_DIR / "reports" / "native_hashes.json"


def fingerprints() -> dict:
    out = {}
    for p in sorted(bs.PDF_DIR.rglob("*.pdf")):
        with contextlib.redirect_stdout(io.StringIO()):
            d = preprocess_file(p)
        words = [[[(w.get("text"), round(float(w.get("x0", 0)), 2),
                    round(float(w.get("top", 0)), 2)) for w in ln] for ln in pg]
                 for pg in d.page_lines]
        blob = json.dumps({"t": d.page_texts, "o": d.page_origins, "w": words,
                           "x": d.extracted_text}, ensure_ascii=False, default=str)
        out[p.relative_to(bs.PDF_DIR).as_posix()] = hashlib.sha256(
            blob.encode("utf-8")).hexdigest()[:16]
    return out


def main(argv) -> int:
    got = fingerprints()
    if argv and argv[0] == "--check":
        want = json.loads(BASELINE.read_text(encoding="utf-8"))
        same = sum(1 for k in want if got.get(k) == want[k])
        print(f"native hashes identical {same} / {len(want)}"
              f"{'' if set(got) == set(want) else ' (file set differs)'}")
        return 0 if same == len(want) and set(got) == set(want) else 1
    json.dump(got, open(argv[0], "w", encoding="utf-8"), indent=1, sort_keys=True)
    print(len(got))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
