"""DEV-ONLY fake model provider: `PRIMARY_LLM=stub` (Part A1).

Answers every call the app makes — slot extraction, template inference,
classification, categorization, summary, anomaly — deterministically FROM THE
DOCUMENT TEXT IN THE PROMPT, with no network and no key, so the whole app
(upload, template, extraction, review, export, options) can be exercised in a
browser or in Playwright without a live call.

It is a stand-in, not a reader: a field slot is answered with what follows its
label on a line ("Invoice No: INV-1" -> "INV-1"); a table row is a line after
the line that holds the table's headings, its trailing numbers right-aligned
into the trailing columns. Every answer quotes the line it came from, so the
real grounding, checks and review marks run on it unchanged.

Startup REFUSES it when ENVIRONMENT is staging or production
(app/config.py `_refuse_stub_outside_development`).
"""
from __future__ import annotations

import json
import re

from connectors.base import LLMResponse

NAME = "stub"


def _resp(obj) -> LLMResponse:
    return LLMResponse(raw_text=json.dumps(obj), parsed_json=obj, model_used="stub",
                       tokens_used=0, success=True)


def _pages(prompt: str, text: str = ""):
    """[(page number, [line, ...])] from the prompt's document block, else
    from `text`."""
    m = re.search(r"=== DOCUMENT TEXT ===\n(.*?)=== END DOCUMENT ===", prompt or "", re.S)
    body = m.group(1) if m else (text or prompt or "")
    parts = re.split(r"^--- page (\d+) ---\n", body, flags=re.M)
    if len(parts) == 1:
        return [(1, [ln for ln in body.splitlines() if ln.strip()])]
    out = []
    for i in range(1, len(parts) - 1, 2):
        out.append((int(parts[i]), [ln for ln in parts[i + 1].splitlines() if ln.strip()]))
    return out


_NUMERICISH = re.compile(r"^[\(\-+]?[$£€₹¥]?\s?[\d.,'/\-]+[\)\-%]?$|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")


def _value_after(label: str, pages):
    lab = label.strip().lower()
    if not lab:
        return None
    for n, lines in pages:
        for ln in lines:
            low = ln.lower()
            i = low.find(lab)
            if i < 0:
                continue
            rest = ln[i + len(lab):].lstrip(" :#-\t")
            if rest:
                return rest.strip(), ln, n
    return None


def _table_rows(cols, pages):
    want = [c.strip().lower() for c in cols]
    for n, lines in pages:
        for k, ln in enumerate(lines):
            low = ln.lower()
            pos = [low.find(c) for c in want]
            if any(p < 0 for p in pos) or pos != sorted(pos):
                continue
            rows = []
            for row in lines[k + 1:]:
                if re.match(r"\s*(sub)?total\b|closing|opening|balance\s+forward", row, re.I):
                    break
                toks = row.split()
                if len(toks) < 2:
                    break
                cells = {}
                rest = list(toks)
                for c in reversed(cols[1:]):
                    if rest and len(rest) > 1 and _NUMERICISH.match(rest[-1]):
                        cells[c] = rest.pop()
                    else:
                        cells[c] = ""
                cells[cols[0]] = " ".join(rest)
                rows.append({"cells": cells, "source": row, "page": n})
            return rows
    return []


class StubClient:
    """Implements connectors.base.LLMProvider."""

    def classify_document(self, text, prompt):
        return _resp({"document_type": "other"})

    def classify_document_vision(self, image_b64, prompt):
        return _resp({"document_type": "other"})

    def extract_data_vision(self, image_b64, prompt, system_instruction="",
                            model=None, temperature=0.1):
        return self.extract_data("", prompt, system_instruction, model, temperature)

    def extract_data(self, text, prompt, system_instruction="", model=None,
                     temperature=0.1):
        p = prompt or ""
        if "Assign a business category" in p:
            n = len(re.findall(r"^Row \d+:", p, re.M))
            return _resp({"categories": ["Other"] * n})
        if p.startswith("Summarise this") or "Return ONLY a JSON object: {\"summary\"" in p:
            return _resp({"summary": ""})
        if "for anomalies" in p:
            return _resp({"anomalies": []})
        pages = _pages(p, text)
        if '"row_count"' in p and '"totals"' in p:
            labels = []
            for _n, lines in pages:
                for ln in lines:
                    m = re.match(r"\s*([A-Za-z][A-Za-z .#/&'-]{1,40}?)\s*:\s*\S", ln)
                    if m and m.group(1).strip() not in labels:
                        labels.append(m.group(1).strip())
            return _resp({"document_type": "other", "title": "Document",
                          "fields": labels[:15] or ["Document"], "tables": [],
                          "totals": []})
        if "=== DOCUMENT TEXT ===" in p:
            fields = {}
            for m in re.finditer(r'^\s+(F\d+): .*?the value on the row labelled "(.*)"\s*$', p, re.M):
                got = _value_after(m.group(2), pages)
                fields[m.group(1)] = ({"value": got[0], "source": got[1], "page": got[2]}
                                      if got else {"value": "", "source": "", "page": 0})
            tables = {}
            for m in re.finditer(r'^TABLE "(.+?)".*?\n(?:  section: .*\n)?  columns \(use EXACTLY these keys\): (.+)$',
                                 p, re.M):
                tables[m.group(1)] = _table_rows([c.strip() for c in m.group(2).split(" | ")], pages)
            return _resp({"fields": fields, "tables": tables})
        return _resp({})


def factory():
    return StubClient()
