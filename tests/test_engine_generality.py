"""Run S generality rule: engine code holds no literal taken from the local
test documents — no document name, no vendor / bank / person name, no
street or city name, no identifier printed on a test document.

The list is tests/fixtures/forbidden_literals.json, generated from
local_docs by tools/make_forbidden_literals.py and committed, so this test
runs on CI too. It scans every module under backend/engine: its STRING
LITERALS, and (Run S review) its COMMENTS and DOCSTRINGS too - a comment
explaining a rule uses an invented example, never a test document's text.
A comment may still name the job number or the rule's history.

`ENGLISH` holds words the generator could not tell from a vendor's name
because they are printed in capitals (or on an address line) on at most two
test documents, but are ordinary English or the trade's vocabulary; each is
a word, never a name.
"""
from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "backend" / "engine"
LITERALS = json.loads((ROOT / "tests" / "fixtures" / "forbidden_literals.json")
                      .read_text(encoding="utf-8"))

ENGLISH = set("""
acquire attention blocks borrower building businesses campus characters collecting
community confirmations correction correctly dated delivered designation directory
disbursement disclaimer distributed districts download electronics ensure
entertainment filer fiscal foods forget garage grand grant grocery handling
individual instruction issuer lender mailed manual meals meter modified module
notices operators original overhead owned performed permit placing plate plates
prefix presented prime printable proforma properties publicly quote recreation
reflecting remittance remote rental repeated replaces representative requisition
requisitioner retail reuse revisions river salesperson seller shipped shipping
single software spaces specification spring starting stores streaming string
submission subscription suffix tangible tickets treatment typed validate verify
wholesale coffee copper harvest maple metro depot kettle bistro parks prime
airfare restaurant cafe cents february mastercard misc specialist echo release
""".split())


# a run of consecutive digits, or one digit repeated, is a placeholder (a
# format example: 123456, 000000000, 99999999), never a document's own number
def _sequential(d: str) -> bool:
    return all(int(b) - int(a) == 1 for a, b in zip(d, d[1:])) or len(set(d)) == 1


def _docstring_ids(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    getattr(body[0], "value", None), ast.Constant):
                out.add(id(body[0].value))
    return out


def _string_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings:
            yield node.lineno, node.value


def _documentation(path: Path):
    """(line, text) of every comment and docstring of the module."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    docstrings = _docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and id(node) in docstrings:
            yield node.lineno, str(node.value)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            yield tok.start[0], tok.string


def _engine_files():
    return [p for p in ENGINE.rglob("*.py")
            if "__pycache__" not in p.parts and "tests" not in p.parts]


def _scan(texts_of):
    words = (set(LITERALS["document_names"]) | set(LITERALS["proper_names"])
             | set(LITERALS.get("address_words") or [])) - ENGLISH
    word_re = re.compile(r"(?<![a-z])(" + "|".join(sorted(map(re.escape, words), key=len,
                                                           reverse=True)) + r")(?![a-z])")
    idents = set(LITERALS["identifiers"])
    out = []
    for p in _engine_files():
        for line, s in texts_of(p):
            # a regex escape (\b, \s) is not a letter of the word beside it
            low = re.sub(r"\\[A-Za-z]", " ", s).casefold()
            for m in word_re.finditer(low):
                out.append(f"{p.relative_to(ROOT)}:{line} word {m.group(1)!r}")
            for d in re.findall(r"(?<!\d)\d{6,}(?!\d)", s):
                if d in idents and not _sequential(d):
                    out.append(f"{p.relative_to(ROOT)}:{line} identifier {d!r}")
    return out


def _hits():
    return _scan(_string_literals)


def test_the_literal_list_is_not_empty():
    assert len(LITERALS["document_names"]) >= 20
    assert len(LITERALS["identifiers"]) >= 50
    assert len(LITERALS["address_words"]) >= 10


def test_engine_code_holds_no_literal_from_the_test_documents():
    hits = _hits()
    assert not hits, "engine string literals taken from test documents:\n" + "\n".join(hits)


def test_engine_comments_and_docstrings_hold_no_document_text():
    hits = _scan(_documentation)
    assert not hits, ("engine comments/docstrings quoting test documents (use an "
                      "invented example):\n" + "\n".join(hits))


def test_the_scan_finds_a_planted_literal(tmp_path, monkeypatch):
    """The scanner is not vacuous: a planted vendor name and account number
    in a string, and a street name in a comment, are all found."""
    fake = tmp_path / "engine"
    fake.mkdir()
    name = sorted(set(LITERALS["document_names"]) - ENGLISH)[0]
    ident = next(d for d in sorted(LITERALS["identifiers"]) if not _sequential(d))
    street = sorted(set(LITERALS["address_words"]) - ENGLISH)[0]
    (fake / "planted.py").write_text(
        f'RULE = r"\\b{name.upper()}\\b"\nACCT = "{ident}"\n'
        f'# e.g. "1 {street.title()} Lane"\nX = 1\n', encoding="utf-8")
    import sys
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "ENGINE", fake)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    hits = _hits()
    assert any("word" in h for h in hits) and any("identifier" in h for h in hits)
    assert any(street in h for h in _scan(_documentation))
