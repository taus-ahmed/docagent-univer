"""Capped live canary for the frozen 14-document owner corpus.

This module is never imported by normal pytest or CI. It reads the API key
only from the process environment, performs at most ``HARD_MAX_CALLS`` HTTP
requests, never logs the key or response body, and writes a summary report.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

os.environ["DOCAGENT_TEST_NO_DOTENV"] = "1"

from tests.harness import bootstrap as _bootstrap
from tests.tools.score_runs import values_equal


_bootstrap.bootstrap()

from core.preprocessor import preprocess_file  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden"
SOURCES = ROOT / "tests" / "fixtures" / "acceptance" / "source_docs"
HARD_MAX_CALLS = 14
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

OWNER_RUNS = [
    "flowparse_bank_us", "mammoth_2pg", "flowparse_card_us",
    "flowparse_invoice_tax", "flowparse_po", "flowparse_cafe",
    "irs_w2_mod11", "irs_w2_2012", "irs6744_w2_mcguire",
    "pitt_sample_w2", "irs_1099nec_ellis", "irs_1099int_mod3",
    "irs6744_brokerage_1099DIV_MISC_INT_B", "irs_1098_joe_angela",
]


class CappedGemini:
    def __init__(self, key: str, max_calls: int):
        self._key = key
        self.max_calls = max_calls
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def generate(self, prompt: str, images: list[str]) -> dict:
        if self.calls >= self.max_calls:
            raise RuntimeError("live canary call cap reached")
        self.calls += 1
        parts = [{"text": prompt}]
        parts.extend({"inlineData": {"mimeType": "image/jpeg", "data": image}}
                     for image in images if image)
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        }
        url = f"{ENDPOINT}/{MODEL}:generateContent?key={self._key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            size = len(exc.read())
            raise RuntimeError(f"Gemini HTTP {exc.code}; {size}-byte body suppressed") from None
        usage = payload.get("usageMetadata") or {}
        self.input_tokens += int(usage.get("promptTokenCount") or 0)
        self.output_tokens += int(usage.get("candidatesTokenCount") or 0)
        candidates = payload.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")
        candidate = candidates[0]
        raw = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
        return {
            "parsed": json.loads(raw),
            "finish_reason": candidate.get("finishReason", ""),
        }

    @property
    def estimated_cost_usd(self) -> float:
        return self.input_tokens / 1_000_000 * 0.075 + self.output_tokens / 1_000_000 * 0.30


def _prompt(truth: dict, text: str) -> str:
    fields = list((truth.get("headers") or {}).keys()) + list((truth.get("totals") or {}).keys())
    tables = {
        table["name"]: sorted({key for row in table.get("key_rows") or [] for key in row})
        for table in truth.get("tables") or []
    }
    return (
        "Extract only facts printed in this document. Return JSON exactly as "
        '{"fields": {label: value}, "tables": {name: [rows]}}. '
        "Use an empty string only when the field is truly absent; do not invent or zero-fill.\n"
        f"Field labels: {json.dumps(fields)}\n"
        f"Tables and columns: {json.dumps(tables)}\n"
        f"Native text (may omit form widgets):\n{text[:30000]}"
    )


def _score_fields(truth: dict, parsed: dict) -> dict:
    actual = parsed.get("fields") if isinstance(parsed, dict) else {}
    actual = actual if isinstance(actual, dict) else {}
    expected = {**(truth.get("headers") or {}), **(truth.get("totals") or {})}
    correct = wrong = missing = 0
    for label, item in expected.items():
        value = actual.get(label)
        if value is None or str(value).strip() == "":
            missing += 1
        elif values_equal(item["value"], value, item.get("type", "text")):
            correct += 1
        else:
            wrong += 1
    return {"expected": len(expected), "correct": correct, "wrong": wrong, "missing": missing}


def run(max_calls: int) -> dict:
    if not 1 <= max_calls <= HARD_MAX_CALLS:
        raise ValueError(f"max calls must be between 1 and {HARD_MAX_CALLS}")
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    client = CappedGemini(key, max_calls)
    runs = []
    for run_id in OWNER_RUNS:
        if client.calls >= max_calls:
            break
        truth = json.loads((GOLDEN / f"{run_id}.json").read_text(encoding="utf-8"))
        document = preprocess_file(SOURCES / truth["file"])
        try:
            response = client.generate(
                _prompt(truth, document.extracted_text),
                document.page_images_b64,
            )
            runs.append({
                "run_id": run_id,
                "success": True,
                "finish_reason": response["finish_reason"],
                **_score_fields(truth, response["parsed"]),
            })
        except Exception as exc:
            runs.append({
                "run_id": run_id,
                "success": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:160],
            })
    return {
        "schema_version": 1,
        "model": MODEL,
        "hard_call_cap": HARD_MAX_CALLS,
        "requested_call_cap": max_calls,
        "calls_made": client.calls,
        "input_tokens": client.input_tokens,
        "output_tokens": client.output_tokens,
        "estimated_cost_usd": round(client.estimated_cost_usd, 6),
        "runs": runs,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-calls", type=int, default=HARD_MAX_CALLS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.max_calls)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Live canary: {report['calls_made']}/{report['requested_call_cap']} calls; "
        f"estimated cost ${report['estimated_cost_usd']:.6f}."
    )
    return 0 if report["runs"] and all(run["success"] for run in report["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
