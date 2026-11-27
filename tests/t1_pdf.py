"""Tiny synthetic PDFs for Run T1: text at any angle, size and grey level,
plus horizontal rules, through the project's own generator
(tests/fixtures/make_scan_variants.py). No dates, no IDs: same input, same
bytes."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _gen():
    spec = importlib.util.spec_from_file_location(
        "make_scan_variants", ROOT / "tests" / "fixtures" / "make_scan_variants.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen


def ops(items, rules=()):
    """items: (x, y, text) or dicts {x, y, text, size=10, angle=0, gray=0,
    font="F1"}; y is PDF points from the BOTTOM. rules: (x0, x1, y, width)."""
    gen = _gen()
    out = [b"BT"]
    for it in items:
        if not isinstance(it, dict):
            x, y, t = it
            it = {"x": x, "y": y, "text": t}
        a = math.radians(float(it.get("angle", 0)))
        c, s = math.cos(a), math.sin(a)
        size = float(it.get("size", 10))
        fill = (f"{it['rgb'][0]:.3f} {it['rgb'][1]:.3f} {it['rgb'][2]:.3f} rg"
                if it.get("rgb") else f"{float(it.get('gray', 0)):.3f} g")
        out.append(f"{fill} /F1 {size} Tf "
                   f"{c:.4f} {s:.4f} {-s:.4f} {c:.4f} {it['x']:.2f} {it['y']:.2f} Tm (".encode()
                   + gen._esc(it["text"]) + b") Tj")
    out.append(b"ET")
    for x0, x1, y, w in rules:
        out.append(f"0 g {w:.2f} w {x0:.2f} {y:.2f} m {x1:.2f} {y:.2f} l S".encode())
    return b"\n".join(out)


def make(path, pages, w=612.0, h=792.0):
    """pages: [items] or [(items, rules)]."""
    gen = _gen()
    built = []
    for p in pages:
        items, rules = (p if isinstance(p, tuple) else (p, ()))
        built.append({"w_pt": w, "h_pt": h, "ops": ops(items, rules)})
    Path(path).write_bytes(gen.build_pdf(built))
    return Path(path)
