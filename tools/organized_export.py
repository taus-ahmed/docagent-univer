"""Organized layout (Run R, Part 2): write the page-shaped sheet for PDFs.

    backend\\.venv\\Scripts\\python.exe tools\\organized_export.py utah_paystub_2 saltlake_paycheck

Each name is looked up under local_docs/DocAgent_testdocs; the workbook goes
to local_docs/organized_out/<name>_organized.xlsx. No model, no key, no .env.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "local_docs" / "DocAgent_testdocs"
OUT = ROOT / "local_docs" / "organized_out"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="+")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from tests.harness.bootstrap import bootstrap
    bootstrap()
    from app.services.excel_organized import organized_workbook
    OUT.mkdir(parents=True, exist_ok=True)
    for name in a.names:
        stem = name[:-4] if name.lower().endswith(".pdf") else name
        hits = [p for p in SOURCES.rglob(f"{stem}.pdf")]
        if not hits:
            print(f"{stem}: not in {SOURCES}")
            continue
        wb = organized_workbook([(hits[0].name, hits[0])])
        p = OUT / f"{stem}_organized.xlsx"
        wb.save(p)
        print(f"{stem}: {', '.join(wb.sheetnames)} -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
