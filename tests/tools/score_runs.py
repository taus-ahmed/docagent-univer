"""Score recorded DocAgent results against tests/golden truth files.

Standard-library only. The default command reports the supplied baseline and
returns zero; ``--gate`` returns non-zero when a silent defect exists or a
record with missing data is reported READY.
"""
from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN = ROOT / "tests" / "golden"
DEFAULT_RECORDS = ROOT / "tests" / "fixtures" / "acceptance" / "job_records"
DEFAULT_JSON = ROOT / "tests" / "reports" / "acceptance" / "scoreboard.json"
DEFAULT_MD = ROOT / "tests" / "reports" / "acceptance" / "scoreboard.md"

JOB_TRUTH = {
    15: "flowparse_bank_us.json",
    19: "flowparse_po.json",
    21: "irs_w2_mod11.json",
    25: "irs_1099nec_ellis.json",
}


def _empty(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or _empty(value):
        return None
    text = str(value).strip().replace("−", "-")
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^0-9.,+\-]", "", text)
    if not text:
        return None
    if text.count(",") and text.count("."):
        text = text.replace(",", "")
    elif text.count(",") == 1 and len(text.rsplit(",", 1)[1]) in (1, 2):
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        out = Decimal(text)
    except InvalidOperation:
        return None
    return -out if negative else out


def _normal_text(value: Any) -> str:
    return " ".join(str(value or "").replace("−", "-").split()).casefold()


def values_equal(expected: Any, actual: Any, value_type: str) -> bool:
    if _empty(actual):
        return False
    if value_type in {"money", "number", "percent"}:
        left, right = _number(expected), _number(actual)
        return left is not None and right is not None and abs(left - right) <= Decimal("0.005")
    if value_type in {"identifier", "date", "datetime", "date_range"}:
        compact = lambda v: re.sub(r"\s+", "", str(v or "")).casefold()
        return compact(expected) == compact(actual)
    return _normal_text(expected) == _normal_text(actual)


def _expected_items(truth: dict) -> list[dict]:
    items = []
    for section in ("headers", "totals"):
        for label, entry in (truth.get(section) or {}).items():
            items.append({
                "key": label,
                "label": label,
                "value": entry["value"],
                "type": entry.get("type", "text"),
                "kind": section,
            })
    for table in truth.get("tables") or []:
        items.append({
            "key": f"{table['name']} row count",
            "label": table["name"],
            "value": table["row_count"],
            "type": "number",
            "kind": "row_count",
        })
        for index, row in enumerate(table.get("key_rows") or []):
            identity = next((str(v) for k, v in row.items()
                             if isinstance(v, str) and k.casefold() not in {"date", "pages"}), str(index + 1))
            for column, value in row.items():
                value_type = "money" if isinstance(value, (int, float)) and column.casefold() not in {
                    "line", "quantity", "row", "page"
                } else ("number" if isinstance(value, (int, float)) else "text")
                items.append({
                    "key": f"{table['name']}::{identity}::{column}",
                    "label": column,
                    "identity": identity,
                    "value": value,
                    "type": value_type,
                    "kind": "table_cell",
                })
    return items


def _actual_fields(record: dict) -> dict[str, Any]:
    projected = (record.get("extracted_data") or {}).get("extracted_data") or {}
    return {
        label: (entry.get("value") if isinstance(entry, dict) else entry)
        for label, entry in projected.items()
    }


def _table_rows(record: dict) -> list[dict]:
    data = record.get("extracted_data") or {}
    rows = data.get("table_rows") or []
    if rows:
        return [row for row in rows if isinstance(row, dict)]
    out = []
    for key, value in data.items():
        if key.endswith("_rows") and isinstance(value, list):
            out.extend(row for row in value if isinstance(row, dict))
    return out


def _actual_for(item: dict, record: dict) -> Any:
    if item["kind"] in {"headers", "totals"}:
        return _actual_fields(record).get(item["label"])
    rows = _table_rows(record)
    if item["kind"] == "row_count":
        return len(rows)
    identity = _normal_text(item.get("identity"))
    column = item["label"]
    candidates = [row for row in rows if identity and identity in _normal_text(" ".join(
        str(v) for key, v in row.items() if not str(key).startswith("_")
    ))]
    return candidates[0].get(column) if candidates else None


def _flags(record: dict) -> list[dict]:
    validation = (record.get("extracted_data") or {}).get("validation") or {}
    return [flag for flag in validation.get("flagged_fields") or [] if isinstance(flag, dict)]


def _flag_matches(item: dict, flag: dict, record: dict) -> bool:
    haystack = _normal_text(" ".join(str(flag.get(k, "")) for k in ("ref", "value", "reason")))
    if _normal_text(item["label"]) in haystack:
        return True
    refs = {
        str(entry.get("ref")): label
        for label, entry in ((record.get("extracted_data") or {}).get("extracted_data") or {}).items()
        if isinstance(entry, dict) and entry.get("ref")
    }
    return refs.get(str(flag.get("ref"))) == item["label"]


def _state(record: dict) -> str:
    data = record.get("extracted_data") or {}
    explicit = record.get("document_state") or data.get("document_state")
    if explicit:
        return str(explicit)
    return "NEEDS_REVIEW" if record.get("needs_review") else "READY"


def score_record(truth: dict, record: dict, *, job: int | None = None) -> dict:
    expected_items = _expected_items(truth)
    flags = _flags(record)
    used_flags: set[int] = set()
    correct = wrong = missing = silent = 0
    details = []
    for item in expected_items:
        actual = _actual_for(item, record)
        if _empty(actual):
            outcome = "missing"
            missing += 1
        elif values_equal(item["value"], actual, item["type"]):
            outcome = "correct"
            correct += 1
        else:
            outcome = "wrong"
            wrong += 1
        matching = [i for i, flag in enumerate(flags) if _flag_matches(item, flag, record)]
        flagged = bool(matching)
        if outcome in {"wrong", "missing"}:
            used_flags.update(matching)
        if outcome in {"wrong", "missing"} and not flagged:
            silent += 1
        if outcome != "correct":
            details.append({
                "key": item["key"], "outcome": outcome,
                "expected": item["value"], "actual": actual, "flagged": flagged,
            })

    false_flags = len(flags) - len(used_flags)

    state = _state(record)
    expected = len(expected_items)
    return {
        "job": job,
        "run_id": truth["run_id"],
        "file": truth["file"],
        "state": state,
        "expected": expected,
        "correct": correct,
        "wrong": wrong,
        "missing": missing,
        "silent_defects": silent,
        "false_flags": false_flags,
        "approve_only": wrong == 0 and missing == 0 and not flags,
        "details": details,
    }


def build_scoreboard(golden_dir: Path = DEFAULT_GOLDEN,
                     records_dir: Path = DEFAULT_RECORDS) -> dict:
    runs = []
    for job, truth_name in JOB_TRUTH.items():
        truth = json.loads((golden_dir / truth_name).read_text(encoding="utf-8"))
        records = json.loads((records_dir / f"job{job}.json").read_text(encoding="utf-8"))
        assert len(records) == 1, f"job{job}: expected one recorded document"
        runs.append(score_record(truth, records[0], job=job))
    total_keys = ("expected", "correct", "wrong", "missing", "silent_defects", "false_flags")
    totals = {key: sum(run[key] for run in runs) for key in total_keys}
    totals["approve_only"] = sum(bool(run["approve_only"]) for run in runs)
    return {"schema_version": 1, "runs": runs, "totals": totals}


def gate_failures(scoreboard: dict) -> list[str]:
    failures = []
    for run in scoreboard["runs"]:
        if run["silent_defects"]:
            failures.append(f"{run['run_id']}: {run['silent_defects']} silent defect(s)")
        if run["missing"] and run["state"] == "READY":
            failures.append(f"{run['run_id']}: READY with {run['missing']} missing value(s)")
    return failures


def markdown(scoreboard: dict) -> str:
    lines = [
        "# Acceptance scoreboard",
        "",
        "| Run | State | Expected | Correct | Wrong | Missing | Silent | False flags | Approve-only |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for run in scoreboard["runs"]:
        lines.append(
            f"| {run['run_id']} | {run['state']} | {run['expected']} | {run['correct']} | "
            f"{run['wrong']} | {run['missing']} | {run['silent_defects']} | "
            f"{run['false_flags']} | {'yes' if run['approve_only'] else 'no'} |"
        )
    totals = scoreboard["totals"]
    lines.append(
        f"| **Total** |  | **{totals['expected']}** | **{totals['correct']}** | "
        f"**{totals['wrong']}** | **{totals['missing']}** | **{totals['silent_defects']}** | "
        f"**{totals['false_flags']}** | **{totals['approve_only']} run(s)** |"
    )
    failures = gate_failures(scoreboard)
    lines += ["", "Gate: " + ("PASS" if not failures else "FAIL"), ""]
    lines += [f"- {failure}" for failure in failures]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    parser.add_argument("--gate", action="store_true")
    args = parser.parse_args(argv)
    board = build_scoreboard(args.golden, args.records)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(board), encoding="utf-8")
    print(markdown(board), end="")
    return 1 if args.gate and gate_failures(board) else 0


if __name__ == "__main__":
    raise SystemExit(main())
