"""Dev tool: add reason codes to BOTH places that must name them.

    python scripts/dev/add_reason.py reasons.json

reasons.json: [{"code", "meaning", "effect", "label", "tooltip"}]. Inserts a
row at the end of the table in docs/OCR-READER-SEAM-DESIGN.md §12 and an entry
at the end of `REASONS` in backend/app/core/review.py
(tests/test_review_reasons.py checks they agree). A code already present is
skipped. Not used at runtime.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "OCR-READER-SEAM-DESIGN.md"
PY = ROOT / "backend" / "app" / "core" / "review.py"


def main(path):
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    doc = DOC.read_text(encoding="utf-8")
    py = PY.read_text(encoding="utf-8")
    start = doc.index("## 12. Review reason codes")
    head = doc.index("| code | meaning | level effect |", start)
    end = doc.index("\n\n", head)
    for it in items:
        code = it["code"]
        if f"| `{code}` |" not in doc[start:]:
            row = f"\n| `{code}` | {it['meaning']} | {it['effect']} |"
            doc = doc[:end] + row + doc[end:]
            end += len(row)
        if f'    "{code}": (' not in py:
            i = py.index("REASONS: dict")
            close = py.index("\n}\n", i)
            entry = (f'\n    "{code}": (\n        {json.dumps(it["label"], ensure_ascii=False)},\n'
                     f'        {json.dumps(it["tooltip"], ensure_ascii=False)}),')
            py = py[:close] + entry + py[close:]
    DOC.write_text(doc, encoding="utf-8")
    PY.write_text(py, encoding="utf-8")
    print(f"{len(items)} reason(s) present in both files")


if __name__ == "__main__":
    main(sys.argv[1])
