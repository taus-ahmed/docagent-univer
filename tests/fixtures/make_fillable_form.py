"""
Builds `tests/fixtures/FORM-CT3-FILLABLE.pdf` — a real fillable form.

Zero of the 60 corpus PDFs carry AcroForm fields, so the commonest construction
for a real tax form has never been testable here: a checkbox that is a WIDGET
ANNOTATION rather than a printed character. Such a widget carries no text at
all, so the text layer shows every option and no marker, and the selection
state — which is the whole content of the field — is invisible to anything
reading text.

Committed as a script as well as a PDF so the fixture can be read, argued with
and regenerated, rather than being an opaque binary someone has to trust.

    python tests/fixtures/make_fillable_form.py
"""
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject, BooleanObject, DictionaryObject, FloatObject, NameObject,
    NumberObject, TextStringObject,
)

OUT = Path(__file__).resolve().parent / "FORM-CT3-FILLABLE.pdf"

PAGE_W, PAGE_H = 612, 792
FONT = "/F1"

#: (label, [(option, selected)]) — the fields whose whole meaning is which
#: box is ticked.
CHOICES = [
    ("Entity type", [("Sole proprietor", False),
                     ("Limited liability company", True),
                     ("C corporation", False),
                     ("S corporation", False)]),
    ("Accounting method", [("Accrual", True), ("Cash", False)]),
    ("Is this a final return?", [("Yes", False), ("No", True)]),
    ("Principal business activity", [("Manufacturing", False),
                                     ("Wholesale trade", True),
                                     ("Retail trade", False),
                                     ("Services", False)]),
]

HEADER = [
    "NEW YORK STATE DEPARTMENT OF TAXATION AND FINANCE",
    "FORM CT-3 - GENERAL BUSINESS CORPORATION FRANCHISE TAX RETURN",
    "Tax Year 2023",
    "",
    "Legal name: Nexus Global Trading LLC",
    "EIN: 47-3821654",
    "",
]
FOOTER = [
    "",
    "Total receipts: $8,412,500.00",
    "Tax due: $412,180.00",
]


def _esc(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build():
    ops, widgets = [], []
    y = PAGE_H - 60

    def text(s, x, yy, size=10):
        ops.append(f"BT {FONT} {size} Tf {x} {yy} Td ({_esc(s)}) Tj ET")

    for line in HEADER:
        if line:
            text(line, 50, y, 11 if line.startswith("FORM") else 10)
        y -= 16

    for i, (label, options) in enumerate(CHOICES):
        text(label + ":", 50, y)
        y -= 16
        x = 66
        for j, (option, selected) in enumerate(options):
            # The BOX is drawn; the TICK is not — the tick lives only in the
            # widget's appearance state, which is exactly the point.
            ops.append(f"{x} {y - 2} 9 9 re S")
            text(option, x + 14, y, 9)
            widgets.append({
                "name": f"choice_{i}_{j}",
                "rect": (x, y - 2, x + 9, y + 7),
                "on": selected,
                "export": option,
            })
            x += 14 + int(5.1 * len(option)) + 16
        y -= 22

    for line in FOOTER:
        if line:
            text(line, 50, y)
        y -= 16

    writer = PdfWriter()
    page = writer.add_blank_page(PAGE_W, PAGE_H)

    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject(FONT):
                                               writer._add_object(font)}),
    })
    page[NameObject("/Contents")] = writer._add_object(
        _stream("\n".join(ops)))

    annots, fields = ArrayObject(), ArrayObject()
    for w in widgets:
        state = NameObject("/Yes") if w["on"] else NameObject("/Off")
        annot = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Btn"),
            NameObject("/T"): TextStringObject(w["name"]),
            NameObject("/TU"): TextStringObject(w["export"]),
            NameObject("/V"): state,
            NameObject("/AS"): state,
            NameObject("/F"): NumberObject(4),
            NameObject("/Rect"): ArrayObject(
                [FloatObject(v) for v in w["rect"]]),
            NameObject("/P"): page.indirect_reference,
        })
        ref = writer._add_object(annot)
        annots.append(ref)
        fields.append(ref)
    page[NameObject("/Annots")] = annots
    writer._root_object[NameObject("/AcroForm")] = writer._add_object(
        DictionaryObject({
            NameObject("/Fields"): fields,
            NameObject("/NeedAppearances"): BooleanObject(True),
        }))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "wb") as fh:
        writer.write(fh)
    return OUT


def _stream(data):
    from pypdf.generic import DecodedStreamObject
    s = DecodedStreamObject()
    s.set_data(data.encode("latin-1"))
    return s


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}")
    from pypdf import PdfReader
    r = PdfReader(str(path))
    flds = r.get_fields() or {}
    print(f"AcroForm fields: {len(flds)}")
    for k, v in flds.items():
        print(f"   {k:14} value={v.get('/V')!r:8} tooltip={v.get('/TU')!r}")
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        print("\ntext layer:")
        print(pdf.pages[0].extract_text())
