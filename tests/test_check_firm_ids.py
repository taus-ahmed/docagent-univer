"""scripts/check_firm_ids.py — read-only report of firm ids this release would
refuse (Run 15, item 13). Its two rules are copies; these tests hold them to
the app's own functions on a corpus of awkward ids."""
from __future__ import annotations

import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_firm_ids as C  # noqa: E402

CORPUS = ["demo_001", "pearx_demo", "acme_001", "Smith.CPA-2", "a", "A1",
          "a b", "a_b", "../acme", "acme", "Smith & Co", "smith_co", "x/y",
          "-lead", "trail-", ".dot", "ü-firm", "a" * 100, "a" * 101,
          "tab\tid", "UPPER", "with:colon"]


@pytest.mark.parametrize("fid", CORPUS)
def test_the_copies_agree_with_the_app(fid):
    from app.core import storage
    from app.schemas.schemas import CLIENT_ID_PATTERN
    try:
        storage._tenant_segment(fid, "x")
        storage_ok = True
    except storage.StorageError:
        storage_ok = False
    if "\\" not in fid:            # Path() differs by OS only for a backslash
        assert (C.old_prefix(fid) == fid) == storage_ok, fid
        assert C.old_prefix(fid) == storage._safe_segment(fid, "unknown")
    assert bool(C.CLIENT_ID_PATTERN.match(fid)) == bool(re.match(CLIENT_ID_PATTERN, fid))


def test_the_demo_ids_pass():
    lines, ok = C.check(["demo_001", "pearx_demo"])
    assert ok, lines


def test_refusals_and_collisions_are_reported():
    lines, ok = C.check(["a b", "a_b", "acme_001"])
    assert not ok
    text = "\n".join(lines)
    assert "REFUSED  'a b'" in text and "stored it under 'a_b'" in text
    assert "COLLIDE  ['a b', 'a_b']" in text
    assert "ok       'acme_001'" in text
    assert lines[-1] == "3 id(s) checked, 2 problem(s)"


def test_stdin_and_file_and_exit_codes(tmp_path):
    script = str(REPO / "scripts" / "check_firm_ids.py")
    good = subprocess.run([sys.executable, script], input=b"# firms\ndemo_001\n\nacme_001\n",
                          capture_output=True)
    assert good.returncode == 0, good.stdout
    f = tmp_path / "ids.txt"
    f.write_text("acme_001\n../acme\n", encoding="utf-8")
    bad = subprocess.run([sys.executable, script, str(f)], capture_output=True)
    assert bad.returncode == 1
    assert b"REFUSED  '../acme'" in bad.stdout


def test_it_imports_nothing_from_the_app():
    src = (REPO / "scripts" / "check_firm_ids.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+(app|sqlalchemy|psycopg2)\b", src, re.M)
