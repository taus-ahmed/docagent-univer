# -*- coding: utf-8 -*-
"""I8 — the LABEL-WITNESS gate, measured over every recorded gold answer.

THE RULE THIS MEASURES, and rejects:

    a filled field slot is trustworthy only if the DOCUMENT prints the slot's
    own label near the value the model quoted.

It is the obvious detector for the class I8 named — a value that is real,
printed, grounded, correctly typed and correctly placed, and answers a
different question than the field asked. Every gate the pipeline has today is
a property of the PAGE (is the string there, is the number printed whole, are
the words adjacent, does the x-span fit the column). This one would have been
a property of the CLAIM.

It does not survive contact with the corpus. See DECISION-LOG §22: 33 of 115
filled field slots fail it and all 33 are correct, because the document's own
word for a field is routinely a synonym (`No:` for Cheque Number, `Terms:` for
Payment Terms), an abbreviation (`Total` for Total Earnings), a block heading
set above the value rather than beside it (`Bill To:`), or absent altogether —
a cheque prints neither `Drawer` nor `Payee`. That is not an accident of this
corpus; it is CLAUDE.md's naming rules 1-3 stated from the other side.

Run it directly to see the failing set:

    python -m tests.harness.witness
"""
from __future__ import annotations

import re

from tests.harness import bootstrap as bs

#: Words carrying no discriminating power in a slot label. `total`, `date`,
#: `amount` and `number` are in here because they are the generic half of a
#: compound label (`Total Earnings`, `Due Date`) and matching on them alone
#: would call almost any line a witness.
STOP = {"of", "the", "a", "an", "to", "for", "in", "on", "and", "or", "no",
        "number", "total", "amount", "date", "name", "id", "address", "this",
        "per"}


def _tokens(s):
    return [t for t in re.split(r"[^a-z0-9]+", str(s).lower()) if t]


def content_words(s):
    """The tokens of a label that could identify it on the page."""
    return [t for t in _tokens(s) if t not in STOP and len(t) > 2]


def witnessed(label, source, pages_text):
    """(verdict, where) — does the page print `label` near its value?

    `None` means undecidable: the label has no content word to look for, or
    the model returned no quote. Counted separately and never as a failure —
    a detector that scores its own blind spots as hits is not a measurement.
    """
    wanted = content_words(label)
    if not wanted:
        return None, "no-content-label"
    src = " ".join(str(source).split())
    if not src:
        return None, "no-source"

    lines = "\n".join(pages_text).split("\n")
    head = " ".join(str(source).split("\n")[0].split())[:40]
    idx = -1
    for i, ln in enumerate(lines):
        if head and head in " ".join(ln.split()):
            idx = i
            break
    if idx < 0:
        # The quote is not on any one line (it wrapped, or it was renotated).
        # Fall back to the quote's own text, which is the most generous
        # reading available — it cannot make the gate look worse than it is.
        hay = src.lower()
        return all(t in hay for t in wanted), "quote-only"

    # THE LINE AND THE LINE ABOVE. A key/value pair prints its label to the
    # left on the same line; a block prints it as a heading above. Widening
    # further would start witnessing the neighbouring field's label instead.
    near = " ".join(lines[max(0, idx - 1): idx + 2]).lower()
    return all(t in near for t in wanted), "line+above"


def measure(only=None):
    """[{doc, label, value, source, ref, confidence, witness, where, outcome}]

    One row per FILLED field slot across the gold corpus, replayed. `outcome`
    is the accuracy harness's own verdict for that field, so "the gate's
    failures are all correct values" is asserted against the scorer rather
    than against a list someone wrote down.
    """
    bs.bootstrap()
    bs.chdir_backend()

    from tests.harness import runner
    from tests.harness.adapter import adapt
    from tests.harness.llm_cache import LLMCache
    from tests.harness.scoring import score_document

    cache = LLMCache(mode="replay")
    cache.install()
    rows = []
    try:
        for label in runner.load_labels(only):
            doc_id = label["document_id"]
            cache.context = doc_id
            template_data, grid, _ = runner.build_template_data(label, "replay")
            results, _log = runner.run_pipeline(label, template_data)

            text = runner.pdf_text(bs.PDF_DIR / label["pdf"])
            pages_text = [text] if isinstance(text, str) else list(text)
            scored = score_document(label, adapt(results, label, grid),
                                    doc_text=text)
            by_label = scored.get("fields") or {}
            by_value = {str(v.get("actual", "")).strip(): v
                        for v in by_label.values()}

            for r in results:
                ed = getattr(r, "extracted_data", None) or {}
                prov = ed.get("field_provenance") or {}
                conf = (ed.get("validation") or {}).get("confidence_map") or {}
                for lab, rec in (ed.get("extracted_data") or {}).items():
                    if not isinstance(rec, dict):
                        continue
                    value = str(rec.get("value", ""))
                    if not value.strip():
                        continue
                    ref = rec.get("ref", "")
                    source = (prov.get(ref) or {}).get("source", "")
                    verdict, where = witnessed(lab, source, pages_text)
                    # The adapter may rename a label on its way to the scorer,
                    # so fall back to matching on the value it scored.
                    hit = by_label.get(lab) or by_value.get(value.strip()) or {}
                    rows.append({
                        "doc": doc_id, "label": lab, "value": value,
                        "source": str(source), "ref": ref,
                        "confidence": conf.get(ref, ""),
                        "witness": verdict, "where": where,
                        "outcome": hit.get("outcome", "not-in-gold"),
                    })
    finally:
        cache.uninstall()
    return rows


def summarise(rows):
    return {
        "slots": len(rows),
        "witnessed": sum(1 for r in rows if r["witness"] is True),
        "unwitnessed": sum(1 for r in rows if r["witness"] is False),
        "undecidable": sum(1 for r in rows if r["witness"] is None),
        "unwitnessed_correct": sum(1 for r in rows if r["witness"] is False
                                   and r["outcome"] == "correct"),
        "unwitnessed_near": sum(1 for r in rows if r["witness"] is False
                                and r["outcome"] == "near"),
        # `wrong`, `hallucinated` and `missed` — the outcomes the gate would
        # have to catch to be worth its false positives.
        "unwitnessed_defective": sum(1 for r in rows if r["witness"] is False
                                     and r["outcome"] in ("wrong", "missed",
                                                          "hallucinated")),
        "defective_total": sum(1 for r in rows if r["outcome"] in
                               ("wrong", "missed", "hallucinated")),
    }


def main():
    rows = measure()
    s = summarise(rows)
    print("filled field slots      : %d" % s["slots"])
    print("  label witnessed       : %d (%.1f%%)"
          % (s["witnessed"], 100.0 * s["witnessed"] / max(s["slots"], 1)))
    print("  NOT witnessed         : %d (%.1f%%)"
          % (s["unwitnessed"], 100.0 * s["unwitnessed"] / max(s["slots"], 1)))
    print("  undecidable           : %d" % s["undecidable"])
    print("    of those: correct=%d near=%d defective=%d"
          % (s["unwitnessed_correct"], s["unwitnessed_near"],
             s["unwitnessed_defective"]))
    print("  defective slots in the whole corpus : %d   <- nothing for the "
          "gate to catch" % s["defective_total"])
    print()
    for r in rows:
        if r["witness"] is False:
            print("  %-22s %-26s [%s] %r" % (r["doc"][:22], r["label"][:26],
                                             r["outcome"], r["value"][:40]))
            print("      quoted: %r" % r["source"][:88])


if __name__ == "__main__":
    main()
