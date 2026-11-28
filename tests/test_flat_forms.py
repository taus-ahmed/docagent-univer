"""Run T3, Stage 7: flat (non-fillable) form reading via drawn boxes.

A flattened PDF has drawn edges (boxes) but no AcroForm widget values.
``form_boxes.has_flat_form_boxes`` must detect it, and ``form_regions``
(with flat_form=True) must split label from value within each box."""
import sys, os
import pytest


@pytest.fixture(autouse=True)
def _engine_path():
    backend = os.path.join(os.path.dirname(__file__), "..", "backend")
    engine  = os.path.join(backend, "engine")
    for p in (backend, engine):
        if p not in sys.path:
            sys.path.insert(0, p)


# ── helpers ──────────────────────────────────────────────────────────────────

def _word(wid, text, x0, x1, top, bottom, baseline=None, size=10.0, origin=None):
    w = {"id": wid, "text": text, "x0": float(x0), "x1": float(x1),
         "top": float(top), "bottom": float(bottom),
         "baseline": float(baseline if baseline is not None else bottom - 2),
         "size": float(size)}
    if origin:
        w["origin"] = origin
    return w


def _line(lid, word_ids, x0, x1, top, bottom):
    return {"id": lid, "word_ids": list(word_ids),
            "x0": float(x0), "x1": float(x1),
            "top": float(top), "bottom": float(bottom),
            "baseline": float(bottom - 2)}


def _make_flat_page(boxes_with_words):
    """Build a minimal page with drawn edges from box geometries and their words.
    ``boxes_with_words`` is a list of ((x0,y0,x1,y1), [word_dicts])."""
    words = []
    # Build edges: for each box emit 4 edges (top, bottom, left, right)
    h_edges = []   # (x0, x1, y)
    v_edges = []   # (y0, y1, x)
    lines = []
    lid = 0
    for (bx0, by0, bx1, by1), ws in boxes_with_words:
        h_edges.append((bx0, bx1, by0))
        h_edges.append((bx0, bx1, by1))
        v_edges.append((by0, by1, bx0))
        v_edges.append((by0, by1, bx1))
        words.extend(ws)
        lid += 1
        lines.append(_line(f"L{lid}", [w["id"] for w in ws],
                           min(w["x0"] for w in ws), max(w["x1"] for w in ws),
                           min(w["top"] for w in ws), max(w["bottom"] for w in ws)))
    page = {
        "page": 1, "width": 612.0, "height": 792.0,
        "words": words,
        "lines": lines,
        "edges": {"h": h_edges, "v": v_edges},
    }
    return page


# ── detection ────────────────────────────────────────────────────────────────

class TestHasFlatFormBoxes:

    def _make_simple_flat_page(self):
        """6 boxes, each with label text at top and value text at bottom;
        no widget-origin words."""
        boxes = []
        for i in range(6):
            x0, y0 = (i % 3) * 200, (i // 3) * 150 + 20
            x1, y1 = x0 + 180, y0 + 120
            lab = _word(f"lab{i}", f"Label {i}",  x0+2, x0+90, y0+2,  y0+14, size=8.0)
            val = _word(f"val{i}", f"Value {i}",  x0+2, x0+140, y0+40, y0+60, size=14.0)
            boxes.append(((x0, y0, x1, y1), [lab, val]))
        return _make_flat_page(boxes)

    def test_flat_form_detected(self):
        import form_boxes as FB
        page = self._make_simple_flat_page()
        assert FB.has_flat_form_boxes(page), (
            "a page with drawn boxes and text words but no widgets must be "
            "detected as a flat form")

    def test_no_flat_form_when_widgets_present(self):
        """A page with widget-origin words is NOT a flat form."""
        import form_boxes as FB
        page = self._make_simple_flat_page()
        # mark one word as a widget
        page["words"][0]["origin"] = "widget"
        assert not FB.has_flat_form_boxes(page), (
            "a page with widget values must not be detected as a flat form")

    def test_no_flat_form_when_no_edges(self):
        import form_boxes as FB
        page = self._make_simple_flat_page()
        page["edges"] = {"h": [], "v": []}
        assert not FB.has_flat_form_boxes(page), (
            "a page with no drawn edges is not a flat form")

    def test_no_flat_form_when_too_few_boxes(self):
        """Fewer than 4 word-in-box matches → not a flat form."""
        import form_boxes as FB
        # only 2 boxes, each with 1 word
        boxes = [
            ((0, 0, 100, 50), [_word("w1", "A", 5, 50, 5, 20)]),
            ((110, 0, 210, 50), [_word("w2", "B", 115, 180, 5, 20)]),
        ]
        page = _make_flat_page(boxes)
        assert not FB.has_flat_form_boxes(page), (
            "fewer than 4 enclosed words should not be detected as a flat form")


# ── label/value inference ─────────────────────────────────────────────────────

class TestInferFlatOrigins:

    def test_smaller_top_cluster_becomes_label(self):
        """Small font at box top → label; larger font below → value."""
        import form_boxes as FB
        box = (10.0, 10.0, 200.0, 80.0)
        ws = [
            _word("lw1", "1 Wages, tips", 12, 150, top=12, bottom=22, size=8.0),
            _word("vw1", "$28,000",        12, 90,  top=45, bottom=65, size=14.0),
        ]
        # assign origins
        import copy
        ws_copy = [copy.copy(w) for w in ws]
        FB._infer_flat_origins(ws_copy, box)
        origins = {w["id"]: w.get("origin") for w in ws_copy}
        assert origins.get("lw1") == "label",  f"small-font top word must be label, got {origins}"
        assert origins.get("vw1") == "value",  f"large-font bottom word must be value, got {origins}"

    def test_same_size_top_bottom_fallback(self):
        """Same font size but two baselines; top baseline → label."""
        import form_boxes as FB
        box = (10.0, 10.0, 200.0, 80.0)
        ws = [
            _word("lw1", "Box label", 12, 100, top=12, bottom=22, size=10.0),
            _word("vw1", "Box value", 12, 100, top=45, bottom=55, size=10.0),
        ]
        import copy
        ws_copy = [copy.copy(w) for w in ws]
        FB._infer_flat_origins(ws_copy, box)
        origins = {w["id"]: w.get("origin") for w in ws_copy}
        assert origins.get("lw1") == "label", f"top baseline must become label, got {origins}"
        assert origins.get("vw1") == "value", f"bottom baseline must become value, got {origins}"

    def test_single_word_box_no_split(self):
        """A box with one word gets no synthetic origin (whole box is label)."""
        import form_boxes as FB
        box = (10.0, 10.0, 200.0, 50.0)
        ws = [_word("w1", "SSN", 12, 60, top=15, bottom=25, size=10.0)]
        import copy
        ws_copy = [copy.copy(w) for w in ws]
        FB._infer_flat_origins(ws_copy, box)
        # No "value" origin should be assigned for a single-word box
        assert ws_copy[0].get("origin") != "value", (
            "a single-word box must not get a 'value' origin")


# ── form_regions flat path ────────────────────────────────────────────────────

class TestFlatFormRegions:

    def _make_w2_like_page(self):
        """3 boxes simulating a W-2: each has a small label (font 8) and a
        typed value (font 12) in different y positions."""
        boxes = []
        layout = [
            # (box_rect, label_text, value_text)
            ((10, 10, 200, 60), "1 Wages, tips, other compensation", "$28,000"),
            ((210, 10, 400, 60), "2 Federal income tax withheld",    "$2,800"),
            ((10, 70, 200, 120), "b EIN",                            "25-7XXXXXX"),
            ((210, 70, 400, 120), "a Employee SSN",                  "128-00-XXXX"),
        ]
        wid = 0
        for (bx0, by0, bx1, by1), lab_text, val_text in layout:
            lab_w = _word(f"l{wid}", lab_text, bx0+2, bx1-5, by0+2, by0+14, size=8.0)
            val_w = _word(f"v{wid}", val_text, bx0+2, bx1-5, by0+30, by0+48, size=12.0)
            wid += 1
            boxes.append(((bx0, by0, bx1, by1), [lab_w, val_w]))
        return _make_flat_page(boxes)

    def test_flat_form_regions_found(self):
        """form_regions(flat_form=True) must return at least one region."""
        import form_boxes as FB
        page = self._make_w2_like_page()
        regions = FB.form_regions(page, flat_form=True)
        assert regions, (
            "form_regions(flat_form=True) must return at least one region for "
            "a page with label/value boxes")

    def test_regions_have_value_fields(self):
        """Every returned region must have at least one field with a value."""
        import form_boxes as FB
        page = self._make_w2_like_page()
        regions = FB.form_regions(page, flat_form=True)
        for r in regions:
            has_val = any(f["value_ids"] for f in r.get("fields", []))
            assert has_val, f"region must have at least one value field: {r}"

    def test_fillable_form_unaffected(self):
        """form_regions(flat_form=False) must not change for a page without
        boxes (the normal code path is unchanged)."""
        import form_boxes as FB
        # a page with no edges → both paths return []
        page = {"page": 1, "width": 612.0, "height": 792.0, "words": [],
                "lines": [], "edges": {"h": [], "v": []}}
        assert FB.form_regions(page, flat_form=False) == []
        assert FB.form_regions(page, flat_form=True)  == []
