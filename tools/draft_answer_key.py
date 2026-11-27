"""Draft an answer key from a PDF's printed text layer (Run T2, Stage 1).

    backend\.venv\Scripts\python.exe tools\draft_answer_key.py <pdf> [--pages 1,2]

Reads pdfplumber's words directly - NOT the perception layer or either
layout engine - groups them into printed lines by their top edge and cuts
each line at gaps wider than one text height. Every line is printed as
`? seg | seg | ...` for a person to turn into key lines (see
tools/position_check.py for the key format). A draft is never a key: it
is edited by hand against the page.
"""
from __future__ import annotations

import argparse
import io
import sys


def draft(pdf_path, pages=None) -> str:
    import pdfplumber
    out = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        nums = pages or list(range(1, len(pdf.pages) + 1))
        for n in nums:
            pg = pdf.pages[n - 1]
            ws = pg.extract_words(keep_blank_chars=False, use_text_flow=False,
                                  extra_attrs=["size"])
            ws.sort(key=lambda w: (round(w["top"]), w["x0"]))
            lines = []
            for w in ws:
                if lines and abs(w["top"] - lines[-1][0]["top"]) <= 2.0:
                    lines[-1].append(w)
                else:
                    lines.append([w])
            out.append(f"## page {n}")
            for ln in lines:
                ln.sort(key=lambda w: w["x0"])
                segs, cur = [], [ln[0]]
                for a, b in zip(ln, ln[1:]):
                    if b["x0"] - a["x1"] > max(4.0, 0.9 * float(a.get("size") or 8)):
                        segs.append(cur)
                        cur = []
                    cur.append(b)
                segs.append(cur)
                out.append("? " + " | ".join(" ".join(w["text"] for w in s) for s in segs))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", default="")
    a = ap.parse_args()
    pages = [int(x) for x in a.pages.split(",") if x.strip()] or None
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stdout.write(draft(a.pdf, pages))


if __name__ == "__main__":
    main()
