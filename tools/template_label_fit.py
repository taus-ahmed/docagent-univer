"""How many of a template's own labels does the document print? (Run S, 3b)

    backend\\.venv\\Scripts\\python.exe tools\\template_label_fit.py [results_dir]

Reads cached replay results (tools/corpus_metrics.py, default the `s1`
cache) and, for every TEMPLATED document, counts the template's field labels
and column headings whose words the PDF's text prints (`template_fit.
label_fraction`). A rule that warns "wrong template" must fire on the
mismatches (a pay stub under a purchase-order template) and on no right
template: this prints the distribution so the threshold is chosen on it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    d = Path(argv[0]) if argv else ROOT / "local_docs" / "corpus_metrics" / "s1_results"
    sys.path.insert(0, str(ROOT / "tools"))
    import replay_raw
    replay_raw._setup()
    import template_fit as TF
    import pdfplumber
    rows = []
    for f in sorted(d.glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        meta, ed = rec["meta"], rec["ed"]
        if not meta.get("templated"):
            continue
        src = replay_raw.find_source(meta["file"])
        if not src or src.suffix.lower() != ".pdf":
            continue
        with pdfplumber.open(str(src)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        labels = TF.slot_labels(ed.get("slot_map") or {})
        frac, n, hit = TF.label_fraction(text, labels)
        tpl = json.loads((replay_raw.RAW / str(meta["job"]) / "template.json")
                         .read_text(encoding="utf-8"))
        rows.append((frac, hit, n, meta["job"], meta["file"], (tpl or {}).get("name")))
    for r in sorted(rows):
        print(f"{r[0]:.2f} {r[1]:>3}/{r[2]:<3} job {r[3]:<4} {r[4][:38]:<38} {r[5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
