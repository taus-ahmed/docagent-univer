"""Synthetic US checks with known ground truth (Run S, Stage 4).

    backend\\.venv\\Scripts\\python.exe tools\\make_synthetic_checks.py [--out DIR] [--n 48]

The owner has no sample checks, so they are generated: personal, business
and payroll checks with MADE-UP data only (invented names, a fictional bank,
routing numbers built to pass the ABA checksum but drawn from no real bank's
range list), each written as a PNG/JPEG image AND as a PDF holding that
image (a scan, no text layer), plus `ground_truth.json`.

Degradations, chosen per check from its index so every strength is covered
for every kind:

  watermark strength   none / light / medium / heavy
    light   a pale tiled background word ("ORIGINAL DOCUMENT")
    medium  + a diagonal security text and a guilloche background pattern
    heavy   + a VOID / SAMPLE overprint across the face, darker pattern
  capture   flat scan / scan with noise and blur / phone photo (slight
            rotation, perspective, a shadow gradient) / low-quality JPEG

Pure PIL (no numpy, no OpenCV); deterministic for a given index. Nothing
here is a real document and no real person, business or bank is named.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "local_docs" / "synthetic_checks"
W, H = 1500, 660            # 7.5 x 3.3 in at 200 dpi
STRENGTHS = ["none", "light", "medium", "heavy"]
CAPTURES = ["scan", "noisy_scan", "phone", "jpeg"]
KINDS = ["personal", "business", "payroll"]

_FONTS = {
    "sans": ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "bold": ["arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "serif": ["times.ttf", "DejaVuSerif.ttf", "LiberationSerif-Regular.ttf"],
    "script": ["segoesc.ttf", "segoepr.ttf", "times.ttf", "DejaVuSerif.ttf"],
    "mono": ["consola.ttf", "cour.ttf", "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf"],
}


def font(kind, size):
    for name in _FONTS[kind]:
        for base in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"),
                     Path("/usr/share/fonts/truetype/liberation")):
            p = base / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


# ── made-up data ─────────────────────────────────────────────────────────────

_SYL = ["mar", "lo", "ven", "tar", "qui", "sel", "dor", "ra", "bel", "nox", "fen", "zu",
        "kal", "ri", "mon", "the", "pa", "vor", "lin", "es", "cad", "wy", "jor", "ul"]
_STREETS = ["Lantern", "Quill", "Harbor", "Juniper", "Copperleaf", "Meadowrun", "Saltmarsh",
            "Brindle", "Foxglove", "Ironwood"]
_TYPES = ["St", "Ave", "Rd", "Ln", "Way", "Ct"]
_CITIES = ["Brookhaven", "Millbridge", "Stonecrest", "Fairhollow", "Westmere", "Ashvale"]
_STATES = ["OR", "KS", "OH", "NM", "VT", "GA", "MN", "TX"]
_BIZ = ["Holdings", "Supply Co", "Services LLC", "Works Inc", "Partners", "Logistics"]
_MEMO = ["Invoice 4471", "Rent March", "Consulting", "Deposit refund", "Payroll period 14",
         "Supplies", "Reimbursement", "Lawn care", "Tuition", "Repairs"]


def _word(rng, n=2):
    return "".join(rng.choice(_SYL) for _ in range(n)).capitalize()


def _person(rng):
    return f"{_word(rng)} {_word(rng, rng.choice((2, 3)))}"


def _business(rng):
    return f"{_word(rng, 3)} {rng.choice(_BIZ)}"


def _address(rng):
    return (f"{rng.randint(10, 9899)} {rng.choice(_STREETS)} {rng.choice(_TYPES)}",
            f"{rng.choice(_CITIES)}, {rng.choice(_STATES)} {rng.randint(10000, 99899):05d}")


def aba_routing(rng):
    """Nine digits passing the ABA checksum 3-7-1 (made up, not a real bank)."""
    while True:
        d = [rng.randint(0, 1)] + [rng.randint(0, 9) for _ in range(7)]
        s = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5])
        check = (10 - s % 10) % 10
        r = "".join(map(str, d + [check]))
        if r[:2] in ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"):
            return r


_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _words_under_1000(n):
    out = []
    if n >= 100:
        out.append(_ONES[n // 100] + " hundred")
        n %= 100
    if n >= 20:
        out.append(_TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else ""))
    elif n:
        out.append(_ONES[n])
    return " ".join(out)


def amount_in_words(cents):
    dollars, c = divmod(int(cents), 100)
    parts = []
    for unit, name in ((1_000_000, "million"), (1000, "thousand"), (1, "")):
        q, dollars = divmod(dollars, unit)
        if q:
            parts.append((_words_under_1000(q) + (" " + name if name else "")).strip())
    text = " ".join(parts) or "zero"
    return f"{text[0].upper()}{text[1:]} and {c:02d}/100"


def make_truth(i, rng):
    kind = KINDS[i % 3]
    strength = STRENGTHS[(i // 3) % 4]
    capture = CAPTURES[(i // 12) % 4]
    payer = _business(rng) if kind != "personal" else _person(rng)
    payee = _person(rng) if kind == "payroll" else rng.choice([_person(rng), _business(rng)])
    cents = rng.choice([rng.randint(1000, 99999), rng.randint(100000, 999999),
                        rng.randint(1000000, 4999999)])
    if kind == "payroll":
        cents = rng.randint(60000, 480000)
    month, day, year = rng.randint(1, 12), rng.randint(1, 28), rng.choice([2024, 2025, 2026])
    return {
        "id": f"chk_{i:03d}", "kind": kind, "watermark": strength, "capture": capture,
        "fields": {
            "payer_name": payer, "payer_address": list(_address(rng)),
            "bank_name": f"{_word(rng, 2)} Fictional Bank",
            "check_number": str(rng.randint(1001, 9899) if kind == "personal"
                                else rng.randint(10001, 98999)),
            "date": f"{month:02d}/{day:02d}/{year}",
            "payee": payee,
            "amount_numeric": f"{cents // 100:,}.{cents % 100:02d}",
            "amount_words": amount_in_words(cents),
            "memo": rng.choice(_MEMO),
            "routing": aba_routing(rng),
            "account": "".join(str(rng.randint(0, 9)) for _ in range(rng.choice((9, 10, 12)))),
        },
    }


# ── drawing ──────────────────────────────────────────────────────────────────

def _guilloche(img, rng, strength):
    d = ImageDraw.Draw(img)
    tone = {"medium": (205, 222, 235), "heavy": (170, 195, 215)}[strength]
    for k in range(18 if strength == "medium" else 30):
        ph = rng.random() * math.tau
        amp = rng.randint(12, 40)
        per = rng.randint(90, 220)
        y0 = rng.randint(0, H)
        pts = [(x, y0 + amp * math.sin(ph + x * math.tau / per)) for x in range(0, W, 6)]
        d.line(pts, fill=tone, width=1)


def _tiled(img, text, alpha, size, angle, colour=(150, 150, 150)):
    layer = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font("bold", size)
    step_x, step_y = int(size * len(text) * 0.75), int(size * 2.2)
    for y in range(0, H * 2, step_y):
        for x in range(-step_x, W * 2, step_x):
            d.text((x + (y // step_y % 2) * step_x // 2, y), text, font=f,
                   fill=colour + (alpha,))
    layer = layer.rotate(angle, resample=Image.BICUBIC)
    layer = layer.crop((W // 2, H // 2, W // 2 + W, H // 2 + H))
    img.alpha_composite(layer)


def _overprint(img, text, alpha):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font("bold", 230)
    d.text((W // 2, H // 2), text, font=f, fill=(200, 40, 40, alpha), anchor="mm")
    layer = layer.rotate(14, resample=Image.BICUBIC)
    img.alpha_composite(layer)


def draw_check(t, rng):
    f = t["fields"]
    img = Image.new("RGBA", (W, H), (250, 248, 240, 255))
    s = t["watermark"]
    if s in ("medium", "heavy"):
        _guilloche(img, rng, s)
    if s != "none":
        _tiled(img, "ORIGINAL DOCUMENT", {"light": 45, "medium": 70, "heavy": 95}[s], 26, 0)
    if s in ("medium", "heavy"):
        _tiled(img, "SECURITY", 70 if s == "medium" else 110, 40, 32, (120, 140, 170))
    d = ImageDraw.Draw(img)
    ink = (20, 20, 30, 255)
    d.rectangle((6, 6, W - 7, H - 7), outline=(90, 90, 110, 255), width=3)
    # payer block
    d.text((40, 30), f["payer_name"], font=font("bold", 30), fill=ink)
    d.text((40, 68), f["payer_address"][0], font=font("sans", 22), fill=ink)
    d.text((40, 96), f["payer_address"][1], font=font("sans", 22), fill=ink)
    if t["kind"] == "payroll":
        d.text((40, 124), "PAYROLL ACCOUNT", font=font("bold", 18), fill=ink)
    # bank, number, date
    d.text((640, 34), f["bank_name"], font=font("serif", 24), fill=ink)
    d.text((W - 200, 30), f["check_number"], font=font("bold", 30), fill=ink)
    d.text((W - 470, 120), "DATE", font=font("sans", 20), fill=ink)
    d.text((W - 390, 108), f["date"], font=font("sans", 30), fill=ink)
    d.line((W - 400, 145, W - 60, 145), fill=ink, width=2)
    # payee and amount
    d.text((40, 215), "PAY TO THE", font=font("sans", 18), fill=ink)
    d.text((40, 238), "ORDER OF", font=font("sans", 18), fill=ink)
    d.text((170, 218), f["payee"], font=font("sans", 34), fill=ink)
    d.line((165, 262, W - 330, 262), fill=ink, width=2)
    d.rectangle((W - 300, 205, W - 60, 265), outline=ink, width=2)
    d.text((W - 290, 218), "$", font=font("bold", 32), fill=ink)
    d.text((W - 255, 218), f["amount_numeric"], font=font("bold", 32), fill=ink)
    d.text((40, 300), f["amount_words"], font=font("sans", 28), fill=ink)
    d.line((35, 340, W - 230, 340), fill=ink, width=2)
    d.text((W - 220, 310), "DOLLARS", font=font("sans", 22), fill=ink)
    # memo and signature
    d.text((40, 440), "MEMO", font=font("sans", 20), fill=ink)
    d.text((120, 430), f["memo"], font=font("sans", 28), fill=ink)
    d.line((115, 465, 640, 465), fill=ink, width=2)
    d.text((W - 560, 420), _word(rng, 2) + " " + _word(rng, 2), font=font("script", 42),
           fill=(30, 40, 110, 255))
    d.line((W - 600, 470, W - 60, 470), fill=ink, width=2)
    # MICR band: transit, on-us (account), serial - ASCII stand-ins (A, C)
    micr = f"A{f['routing']}A {f['account']}C {f['check_number']}"
    d.text((140, H - 110), micr, font=font("mono", 44), fill=(10, 10, 10, 255))
    if s == "heavy":
        _overprint(img, "VOID" if t["kind"] != "payroll" else "SAMPLE", 120)
    t["micr_line"] = micr
    return img.convert("RGB")


# ── capture ─────────────────────────────────────────────────────────────────

def _solve(a, b):
    """Solve a dense 8x8 linear system (Gauss-Jordan); pure Python."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                k = m[r][c] / m[c][c]
                m[r] = [x - k * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def _perspective(img, rng):
    w, h = img.size
    j = lambda: rng.randint(0, 40)  # noqa: E731
    dst = [(j(), j()), (w - j(), j()), (w - j(), h - j()), (j(), h - j())]
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    coeffs = _solve(a, b)
    return img.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BICUBIC,
                         fillcolor=(90, 85, 80))


def _shadow(img, rng):
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    start = rng.randint(w // 3, 2 * w // 3)
    for x in range(start, w):
        d.line((x, 0, x, h), fill=int(110 * (x - start) / max(1, w - start)))
    dark = Image.new("RGB", (w, h), (30, 30, 30))
    return Image.composite(dark, img, mask)


def _noise(img, rng, amount):
    px = img.load()
    w, h = img.size
    for _ in range(int(w * h * amount)):
        x, y = rng.randrange(w), rng.randrange(h)
        v = rng.choice((0, 255))
        px[x, y] = (v, v, v)
    return img


def capture(img, t, rng):
    c = t["capture"]
    if c == "noisy_scan":
        img = _noise(img, rng, 0.01).filter(ImageFilter.GaussianBlur(1.1))
    elif c == "phone":
        canvas = Image.new("RGB", (W + 120, H + 120), (95, 90, 84))
        canvas.paste(img, (60, 60))
        img = canvas.rotate(rng.uniform(-3, 3), resample=Image.BICUBIC,
                            fillcolor=(95, 90, 84))
        img = _perspective(img, rng)
        img = _shadow(img, rng).filter(ImageFilter.GaussianBlur(0.8))
    elif c == "jpeg":
        img = img.filter(ImageFilter.GaussianBlur(0.6))
    return img


def build(out: Path, n: int, seed: int = 20261125):
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "pdfs").mkdir(parents=True, exist_ok=True)
    truth = []
    for i in range(n):
        rng = random.Random(seed * 1000 + i)
        t = make_truth(i, rng)
        img = capture(draw_check(t, rng), t, rng)
        q = 35 if t["capture"] == "jpeg" else 85
        ip = out / "images" / f"{t['id']}.jpg"
        img.save(ip, "JPEG", quality=q)
        pp = out / "pdfs" / f"{t['id']}.pdf"
        Image.open(ip).convert("RGB").save(pp, "PDF", resolution=200.0)
        t["files"] = {"image": f"images/{ip.name}", "pdf": f"pdfs/{pp.name}"}
        truth.append(t)
    (out / "ground_truth.json").write_text(json.dumps(
        {"generator": "tools/make_synthetic_checks.py", "seed": seed, "checks": truth},
        indent=1), encoding="utf-8")
    return truth


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--n", type=int, default=48)
    a = ap.parse_args(argv)
    if a.n < 40:
        raise SystemExit("at least 40 checks")
    t = build(Path(a.out), a.n)
    by = {}
    for x in t:
        by.setdefault((x["kind"], x["watermark"]), 0)
        by[(x["kind"], x["watermark"])] += 1
    print(f"{len(t)} checks -> {a.out}")
    for k, v in sorted(by.items()):
        print(f"  {k[0]:<9} {k[1]:<7} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
