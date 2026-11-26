"""Per-field accuracy of the OCR word-box reading on the synthetic checks
(Run S, Stage 4).

    backend\\.venv\\Scripts\\python.exe tools\\eval_synthetic_checks.py --tag before --variants none
    backend\\.venv\\Scripts\\python.exe tools\\eval_synthetic_checks.py --tag sweep --variants none ink otsu median ink_x15 multipass

For every check in local_docs/synthetic_checks/ground_truth.json the image is
cleaned (engine/image_cleanup.py), read by the engine's own OCR reader
(ocr_source.OcrPageSource, the seam every scanned page goes through), and each
field is scored:

  text fields (payee, amount in words, memo, payer, bank, date, number, amount)
      READ when the ground truth's words appear, in order and contiguous, on
      one OCR line (casefolded; punctuation other than digits' own ignored).
      This is the precondition for any grounded value: a field the reading
      does not carry cannot be verified, whatever the model answers.
  micr_routing / micr_account / micr_serial
      READ when the engine's MICR parser (micr.parse_micr) returns the ground
      truth from the OCR reading's MICR line - the MICR check of Stage 4c.
  amounts_agree
      the engine's amount reconciliation (cheque_amounts.compare_amounts) of
      the READ figures and READ words finds them equal.

No model is called. Results: local_docs/synthetic_checks/eval_<tag>.json/.md,
split by watermark strength and by capture.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "local_docs" / "synthetic_checks"
TEXT_FIELDS = ["payer_name", "bank_name", "check_number", "date", "payee",
               "amount_numeric", "amount_words", "memo"]
MICR_FIELDS = ["micr_routing", "micr_account", "micr_serial"]
ALL = TEXT_FIELDS + MICR_FIELDS + ["amounts_agree"]


def _setup():
    sys.path.insert(0, str(ROOT))
    from tests.harness import bootstrap as bs
    bs.bootstrap()


def _norm_tokens(text):
    return [t for t in re.split(r"\s+", re.sub(r"[^\w./,-]", " ", str(text).casefold())) if t]


def _flat(tok):
    return re.sub(r"[^\w]", "", tok)


def lines_of(words):
    by = {}
    for w in words:
        by.setdefault(w.get("line_id", round(w["top"] / 12)), []).append(w)
    return [sorted(ws, key=lambda w: w["x0"]) for _k, ws in
            sorted(by.items(), key=lambda kv: min(w["top"] for w in kv[1]))]


def field_read(truth, lines) -> bool:
    want = [_flat(t) for t in _norm_tokens(truth)]
    want = [t for t in want if t]
    if not want:
        return False
    for ln in lines:
        got = [_flat(t) for w in ln for t in _norm_tokens(w["text"])]
        got = [t for t in got if t]
        for i in range(len(got) - len(want) + 1):
            if got[i:i + len(want)] == want:
                return True
    return False


def read(image, variant):
    """[word] in the ORIGINAL image's pixel space."""
    import image_cleanup as IC
    from ocr_source import OcrPageSource
    if variant == "multipass":
        readings = [read(image, v) for v in IC.MULTIPASS]
        return IC.merge_readings(readings)
    if variant == "engine":
        # the reader exactly as the pipeline configures it: its default
        # cleanup (image_cleanup.DEFAULT) and its own MICR band repair
        src = OcrPageSource(image, dpi=200, straighten_page=True)
        return [dict(w) for w in src.words()]
    img, f = IC.apply(image, variant)
    src = OcrPageSource(img, dpi=200 * f, straighten_page=True, cleanup="none")
    out = []
    for w in src.words():
        w = dict(w)
        for k in ("x0", "x1", "top", "bottom"):
            w[k] = w[k] / f
        out.append(w)
    return out


def score(check, words, image=None, band_reader=False):
    import micr
    import cheque_amounts as CA
    f = check["fields"]
    lines = lines_of(words)
    res = {k: field_read(f[k], lines) for k in TEXT_FIELDS}
    text = "\n".join(" ".join(w["text"] for w in ln) for ln in lines)
    if band_reader and image is not None:
        import micr_reader as MR             # Stage 4c: the band read on its own
        band = MR.read_band(image, words)
    else:
        band = micr.find_micr_line(text)
    parsed = micr.parse_micr(band) if band else {}
    res["micr_routing"] = parsed.get("routing_number") == f["routing"]
    res["micr_account"] = parsed.get("account_number") == f["account"]
    res["micr_serial"] = parsed.get("serial_number") == f["check_number"]
    try:
        chk = CA.compare_amounts(f["amount_numeric"] if res["amount_numeric"] else None,
                                 f["amount_words"] if res["amount_words"] else None)
        res["amounts_agree"] = bool(getattr(chk, "agree", False)
                                    or getattr(chk, "status", "") in ("match", "agree"))
    except Exception:
        res["amounts_agree"] = False
    res["_micr_line"] = band
    return res


def run(tag, variants, limit=None, band_reader=False):
    _setup()
    from PIL import Image
    gt = json.loads((DATA / "ground_truth.json").read_text(encoding="utf-8"))["checks"]
    if limit:
        gt = gt[:limit]
    out = {"tag": tag, "micr_band_reader": band_reader, "variants": {}}
    for v in variants:
        t0 = time.time()
        per = []
        for c in gt:
            img = Image.open(DATA / c["files"]["image"]).convert("RGB")
            words = read(img, v)
            per.append({"id": c["id"], "kind": c["kind"], "watermark": c["watermark"],
                        "capture": c["capture"],
                        "result": score(c, words, img, band_reader)})
        out["variants"][v] = {"seconds": round(time.time() - t0), "checks": per,
                              "summary": summarise(per)}
        print(f"{v}: {out['variants'][v]['summary']['all']['overall']}% "
              f"({out['variants'][v]['seconds']} s)", flush=True)
    (DATA / f"eval_{tag}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (DATA / f"eval_{tag}.md").write_text(markdown(out), encoding="utf-8")
    return out


def summarise(per):
    groups = {"all": per}
    for key in ("watermark", "capture", "kind"):
        for p in per:
            groups.setdefault(f"{key}={p[key]}", []).append(p)
    out = {}
    for g, ps in groups.items():
        row = {f: round(100 * sum(p["result"][f] for p in ps) / len(ps)) for f in ALL}
        row["overall"] = round(100 * sum(p["result"][f] for p in ps for f in ALL)
                               / (len(ps) * len(ALL)), 1)
        row["n"] = len(ps)
        out[g] = row
    return out


def markdown(out):
    lines = [f"# Synthetic checks: per-field read accuracy ({out['tag']})", ""]
    for v, d in out["variants"].items():
        lines += [f"## variant `{v}` ({d['seconds']} s)", "",
                  "| slice | n | overall | " + " | ".join(ALL) + " |",
                  "|---|---:|---:|" + "---:|" * len(ALL)]
        order = ["all"] + [f"watermark={s}" for s in ("none", "light", "medium", "heavy")] \
            + sorted(k for k in d["summary"] if k.startswith(("capture=", "kind=")))
        for g in order:
            r = d["summary"].get(g)
            if r:
                lines.append(f"| {g} | {r['n']} | {r['overall']} | "
                             + " | ".join(str(r[f]) for f in ALL) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--variants", nargs="+", default=["none"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--micr-band", action="store_true",
                    help="read the MICR band on its own (Stage 4c)")
    a = ap.parse_args(argv)
    if not (DATA / "ground_truth.json").exists():
        print("no local_docs/synthetic_checks: run tools/make_synthetic_checks.py first")
        return 1
    run(a.tag, a.variants, a.limit, a.micr_band)
    return 0


if __name__ == "__main__":
    sys.exit(main())
