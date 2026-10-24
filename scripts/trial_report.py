"""Cheque-trial report: how often the machine was right, and how often it was
wrong WITHOUT SAYING SO (docs/CHEQUE-TRIAL.md, section 5).

    python scripts/trial_report.py --truth outcomes.csv [--results results.json]
                                   [--out trial-report]

--truth    the accountant's outcomes CSV (docs/cheque-trial-outcomes-template.csv):
           file, page, field, machine value, level, reasons, true value,
           correct yes/no, and optionally `cheque` (the k of a record named
           "file [k of N]"; 1 when absent).
--results  optional: the job's results as returned by
           GET /api/jobs/{id}/results (a JSON list). When given, the machine
           value, level and reasons come from it (the CSV's copies are
           ignored), and cheques found are counted from its records. Without
           it, the CSV's own machine columns are used. The exported workbook
           is not parsed: its values and review status are the same data, and
           the JSON is the unambiguous copy.
--out      output path stem: writes <stem>.md and <stem>.csv (default
           trial-report). Nothing is sent anywhere.

Real trial files stay on the firm's side; this repository holds synthetic
fixtures only (tests/fixtures/trial/).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Report order. "verified" is the `high` confidence level.
LEVELS = ["verified", "grounded", "unverified", "low", "edited",
          "empty_flagged", "empty", "failed", "unknown"]
LEVEL_NAMES = {"verified": "high (verified)", "empty_flagged": "empty-flagged"}
#: Levels that claim the value is right. A wrong one is a SILENT wrong value.
CONFIDENT = {"verified", "grounded"}
#: Levels that ask a person to look, whatever the reasons say.
NEEDS_PERSON = {"unverified", "low", "empty_flagged", "unknown", "failed"}
_ALIASES = {"high": "verified", "empty-flagged": "empty_flagged",
            "empty flagged": "empty_flagged", "medium": "unverified"}

EXPLAIN = """\
## What the numbers mean

- **Count / correct / wrong / accuracy** — for each field and each level, how
  many values the accountant checked, how many matched the cheque, how many did
  not, and correct ÷ count. Notation differences ($1,250.00 vs 1250.00) count
  as correct.
- **Silent-wrong rate** — of the values the system labelled *high (verified)*
  or *grounded* (it claims they are right, and nothing tells the reader to
  look), the share that were wrong. **This must be zero**: it is the one error
  a user who never reviews would receive as fact.
- **Wrong with no flag** — wrong values that carried no warning at all: a
  confident level and no reason code. Includes a field left empty without a
  flag where the cheque had a value.
- **False alarms** — correct values that were flagged (a review level or a
  reason code). Not dangerous, but each one costs the accountant a look.
- **Cheques found vs truth** — per file, how many cheque records the system
  produced against how many cheques the accountant counted. Fewer means a
  cheque was dropped or two were merged; more means one was split or
  duplicated.
- **Reason precision** — for each reason code, how often the value it fired on
  really was wrong. A code that fires on correct values is noise; one that
  fires only on wrong values is earning its place.
"""


# ── reading ──────────────────────────────────────────────────────────────────

def norm_level(level) -> str:
    s = str(level or "").strip().lower()
    s = _ALIASES.get(s, s)
    return s if s in LEVELS else ("empty" if s == "" else "unknown")


def norm_value(v) -> str:
    """Notation-blind form: case, whitespace, currency, separators."""
    s = re.sub(r"\s+", "", str(v if v is not None else "")).casefold()
    num = re.sub(r"[$€£,]", "", s)
    if re.fullmatch(r"\(?-?\d+(\.\d+)?\)?", num or "x"):
        neg = num.startswith("(") or num.startswith("-")
        val = float(num.strip("()").lstrip("-"))
        return repr(-val if neg else val)
    return s


def same_value(a, b) -> bool:
    return norm_value(a) == norm_value(b)


def _yes(v):
    s = str(v or "").strip().lower()
    return True if s in ("yes", "y", "true", "1") else False if s in (
        "no", "n", "false", "0") else None


_RECORD = re.compile(r"^(?P<file>.*?)(?: \[(?P<k>\d+) of (?P<n>\d+)\])?$")


def read_truth(text: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {str(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        rows.append({
            "file": r.get("file", ""), "page": r.get("page", ""),
            "cheque": int(r.get("cheque") or 1), "field": r.get("field", ""),
            "machine": r.get("machine value", ""), "level": norm_level(r.get("level")),
            "reasons": [x.strip() for x in (r.get("reasons") or "").split(";") if x.strip()],
            "true": r.get("true value", ""), "judged": _yes(r.get("correct yes/no"))})
    return rows


def read_results(data) -> tuple[dict, Counter]:
    """{(file, cheque, field): machine value dict}, and cheque records per file."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.review import document_values
    values, found = {}, Counter()
    for rec in data or []:
        name = rec.get("filename") or ""
        m = _RECORD.match(name)
        file = rec.get("original_filename") or m.group("file")
        ed = rec.get("extracted_data") or {}
        if not isinstance(ed, dict) or rec.get("document_type") == "cancelled":
            continue
        k = int(ed.get("document_index") or m.group("k") or 1)
        found[file] += 1
        for v in document_values(ed):
            if v.get("kind") != "field":
                continue
            values[(file, k, v["label"])] = {
                "machine": v.get("value") or "", "level": norm_level(v.get("status")),
                "reasons": list(v.get("reasons") or []),
                "review_required": bool(v.get("review_required"))}
    return values, found


# ── judging ──────────────────────────────────────────────────────────────────

def judge(truth: list[dict], machine: dict | None) -> list[dict]:
    out = []
    for t in truth:
        row = dict(t)
        m = (machine or {}).get((t["file"], t["cheque"], t["field"])) if machine is not None else None
        if machine is not None:
            row["machine"] = m["machine"] if m else ""
            row["level"] = m["level"] if m else "empty"
            row["reasons"] = m["reasons"] if m else []
            row["review_required"] = bool(m and m["review_required"])
            # the accountant judged the value HE saw; trust it only for that value
            use_judged = t["judged"] is not None and same_value(t["machine"], row["machine"])
        else:
            row["review_required"] = False
            use_judged = t["judged"] is not None
        if use_judged:
            row["correct"] = t["judged"]
        elif str(row["machine"]).strip() == "":
            row["correct"] = str(t["true"]).strip() == ""
        else:
            row["correct"] = same_value(row["machine"], t["true"])
        row["flagged"] = (row["level"] in NEEDS_PERSON or bool(row["reasons"])
                          or row["review_required"])
        out.append(row)
    return out


def _acc(c, n):
    return f"{100.0 * c / n:.1f}%" if n else "—"


def report(judged: list[dict], found: Counter | None) -> tuple[str, list[list]]:
    by_level = defaultdict(lambda: [0, 0])
    by_field = defaultdict(lambda: [0, 0])
    by_fl = defaultdict(lambda: [0, 0])
    reason = defaultdict(lambda: [0, 0])          # fired, value wrong
    confident = confident_wrong = unflagged_wrong = false_alarm = wrong = 0
    for r in judged:
        ok = bool(r["correct"])
        for d, k in ((by_level, r["level"]), (by_field, r["field"]),
                     (by_fl, (r["field"], r["level"]))):
            d[k][0] += 1
            d[k][1] += ok
        wrong += not ok
        if r["level"] in CONFIDENT:
            confident += 1
            confident_wrong += not ok
        if not ok and not r["flagged"]:
            unflagged_wrong += 1
        if ok and r["flagged"]:
            false_alarm += 1
        for code in r["reasons"]:
            reason[code][0] += 1
            reason[code][1] += not ok

    truth_cheques = Counter()
    for f, k in {(r["file"], r["cheque"]) for r in judged}:
        truth_cheques[f] += 1
    if found is None:                 # no results JSON: a cheque is found if any value was
        found = Counter()
        for f, k in {(r["file"], r["cheque"]) for r in judged
                     if str(r["machine"]).strip()}:
            found[f] += 1
    files = sorted(set(truth_cheques) | set(found))
    missing = sum(max(0, truth_cheques[f] - found[f]) for f in files)
    extra = sum(max(0, found[f] - truth_cheques[f]) for f in files)

    rows = [["section", "field", "level", "count", "correct", "wrong", "accuracy"]]
    md = ["# Cheque trial report", "", EXPLAIN, "## Safety", "",
          "| metric | value |", "|---|---|",
          f"| values checked | {len(judged)} |",
          f"| wrong values | {wrong} |",
          f"| **silent-wrong rate** (wrong ÷ labelled high or grounded) | "
          f"**{confident_wrong} of {confident}** ({_acc(confident_wrong, confident)}) |",
          f"| wrong with no flag | {unflagged_wrong} |",
          f"| false alarms (correct but flagged) | {false_alarm} |",
          f"| cheques found / truth | {sum(found[f] for f in files)} / "
          f"{sum(truth_cheques.values())} (missing {missing}, extra {extra}) |", ""]
    rows += [["safety", "", "", len(judged), len(judged) - wrong, wrong, _acc(len(judged) - wrong, len(judged))],
             ["silent_wrong", "", "high+grounded", confident, confident - confident_wrong,
              confident_wrong, _acc(confident - confident_wrong, confident)],
             ["wrong_no_flag", "", "", unflagged_wrong, "", unflagged_wrong, ""],
             ["false_alarm", "", "", false_alarm, false_alarm, "", ""]]

    md += ["## By level", "", "| level | count | correct | wrong | accuracy |",
           "|---|---|---|---|---|"]
    for lv in LEVELS:
        if lv in by_level:
            n, c = by_level[lv]
            md.append(f"| {LEVEL_NAMES.get(lv, lv)} | {n} | {c} | {n - c} | {_acc(c, n)} |")
            rows.append(["level", "", lv, n, c, n - c, _acc(c, n)])
    md += ["", "## By field", "", "| field | level | count | correct | wrong | accuracy |",
           "|---|---|---|---|---|---|"]
    for f in sorted(by_field):
        n, c = by_field[f]
        md.append(f"| **{f}** | all | {n} | {c} | {n - c} | {_acc(c, n)} |")
        rows.append(["field", f, "all", n, c, n - c, _acc(c, n)])
        for lv in LEVELS:
            if (f, lv) in by_fl:
                n2, c2 = by_fl[(f, lv)]
                md.append(f"| {f} | {LEVEL_NAMES.get(lv, lv)} | {n2} | {c2} | {n2 - c2} | {_acc(c2, n2)} |")
                rows.append(["field_level", f, lv, n2, c2, n2 - c2, _acc(c2, n2)])
    md += ["", "## Cheques found vs truth", "", "| file | found | truth | note |",
           "|---|---|---|---|"]
    for f in files:
        note = ("dropped or merged" if found[f] < truth_cheques[f]
                else "split or duplicated" if found[f] > truth_cheques[f] else "")
        md.append(f"| {f} | {found[f]} | {truth_cheques[f]} | {note} |")
        rows.append(["cheques", f, "", truth_cheques[f], found[f], "", note])
    md += ["", "## Reason precision", "",
           "| reason | fired | value was wrong | precision |", "|---|---|---|---|"]
    for code in sorted(reason):
        n, w = reason[code]
        md.append(f"| `{code}` | {n} | {w} | {_acc(w, n)} |")
        rows.append(["reason", code, "", n, "", w, _acc(w, n)])
    if not reason:
        md.append("| (no reason codes fired) | | | |")
    return "\n".join(md) + "\n", rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--truth", required=True)
    ap.add_argument("--results")
    ap.add_argument("--out", default="trial-report")
    a = ap.parse_args(argv)
    truth = read_truth(Path(a.truth).read_text(encoding="utf-8-sig"))
    machine = found = None
    if a.results:
        machine, found = read_results(json.loads(Path(a.results).read_text(encoding="utf-8")))
    md, rows = report(judge(truth, machine), found)
    Path(a.out + ".md").write_text(md, encoding="utf-8")
    with open(a.out + ".csv", "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    print(f"wrote {a.out}.md and {a.out}.csv ({len(truth)} values)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
