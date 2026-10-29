"""User-written regular expressions, run so they cannot hang the process
(Review-3 F4; Recheck R1).

A template's `regex` rule and a category rule's `regex` are written by a
user and run against text an uploaded document supplies. Python's `re` is a
backtracking engine: `(a+)+$` over thirty `a`s and a `b` takes longer than
the age of the universe, and it holds the GIL while it does — a thread
timeout cannot stop it, and the whole worker stops with it.

Recheck R1: a subset check alone was not enough. Codex found two patterns it
admitted that still ran for tens of seconds on ONE value —
`a{0,100}a{0,100}a{0,100}a{0,100}a{0,100}b` (fullmatch, ~30 s: bounded
quantifiers were not counted) and `\d*\d*\d*x` (search, ~18 s) — and a
budget checked between calls cannot stop a match already running.

So every match now runs on RE2 (google-re2), which never backtracks: its time
is linear in the text for ANY pattern, so the limit holds during a match by
construction, not by an interrupt. The subset check is kept as defence in
depth, decided once from the parse tree before a pattern is admitted:

  * no repetition of something that itself varies in length — `(a+)+`,
    `(a*)*`, `(\w+\s?)+`, `(?:a?b)*` (a fixed count inside is fine:
    `(?:\d{3})+`);
  * no alternation inside a repeated group — `(a|aa)+`, `(a|a)*` (write a
    character class: `[-\s]+`);
  * no backreferences and no lookaround, which RE2 does not have;
  * at most MAX_VARIABLE variable-length quantifiers in all — EVERY one whose
    minimum and maximum differ counts, bounded or not (`?`, `{0,100}`, `*`) —
    and MAX_PATTERN characters;
  * and the pattern is TEST-MATCHED against adversarial strings
    (`_probe_strings`): one that takes more than PROBE_SEC on them is refused.

WHAT IS GUARANTEED (Recheck 2 S3), and what is not:

  * a match is linear in the text (RE2), and the text is at most MAX_INPUT
    (512) characters — `SafePattern` refuses a longer one itself, so the
    bound does not depend on every caller remembering `too_long`;
  * a pattern is at most MAX_PATTERN characters AND compiles to at most
    MAX_PROGRAM RE2 instructions (forward and reverse), and RE2 runs in at
    most MAX_MEM bytes per compiled pattern. Together these bound ONE value's
    worst case: measured at about PER_VALUE_MS ms (4.0 ms on the dev machine,
    `[a ]{0,120}[ab]{0,120}[ a]{0,120}$` ignoring case, size 964). Without the
    program cap `\w{0,1000}\W{0,1000}\w{0,1000}$` (size 20,004) took 19 ms
    and the worst found 83 ms;
  * `Budget` is a SOFT limit over all of one rule's values: it is checked
    before each call and charged after it, so it stops the rule at the first
    value after BUDGET_SEC is spent and says so. It overruns by at most one
    value's cost.
  * NOT guaranteed: a hard wall-clock limit. Nothing interrupts a match once
    it has started; the bound above is what makes that acceptable. ⚠ RE2's `\d`, `\w` and `\b` are ASCII, where Python's are
Unicode: `\d+` does not match Arabic-Indic digits. Write the characters
out (`[0-9٠-٩]`) when a rule needs them.

Everything refused is refused OUT LOUD — `pattern_problem` returns the reason
the editor shows at save time, and a rule that still meets one at run time is
UNREADABLE with that reason — never skipped quietly and never guessed. Without
the RE2 engine installed every pattern is refused: nothing falls back to `re`.
"""
from __future__ import annotations

import re
import time
from typing import Optional

try:                                   # Python 3.11+
    import re._constants as _c
    import re._parser as _p
except ImportError:                    # pragma: no cover - older Pythons
    import sre_constants as _c         # type: ignore
    import sre_parse as _p             # type: ignore

MAX_PATTERN = 300
MAX_INPUT = 512
MAX_VARIABLE = 3
#: RE2 instructions a compiled pattern may have (forward and reverse); with
#: MAX_INPUT this is what bounds one value's cost (module docstring)
MAX_PROGRAM = 1000
#: RE2's memory budget per compiled pattern (its own default, stated here)
MAX_MEM = 8 << 20
#: the measured worst case of one match under the limits above, milliseconds
#: (tests/test_regex_linear.py asserts a ceiling well above it)
PER_VALUE_MS = 4.0
BUDGET_SEC = 2.0
#: seconds a pattern may take over all of the save-time probe strings
PROBE_SEC = 0.25

_REPEATS = {_c.MAX_REPEAT, _c.MIN_REPEAT}
if hasattr(_c, "POSSESSIVE_REPEAT"):
    _REPEATS.add(_c.POSSESSIVE_REPEAT)
_BACKREFS = {_c.GROUPREF, _c.GROUPREF_EXISTS}
if hasattr(_c, "GROUPREF_IGNORE"):
    _BACKREFS.add(_c.GROUPREF_IGNORE)


class UnsafePattern(ValueError):
    """A pattern outside the safe subset (or not a pattern at all)."""


class _Walk:
    def __init__(self):
        self.variable = 0
        self.literals: set = set()

    def items(self, seq, repeated: bool):
        for op, av in seq:
            if op in _REPEATS:
                lo, hi, sub = av
                varies = lo != hi
                if repeated and varies:
                    raise UnsafePattern(
                        "a repeated group contains another quantifier that can "
                        "match a varying length (like (a+)+); this can take "
                        "forever on some text")
                if varies:
                    self.variable += 1
                self.items(sub, repeated or hi > 1)
            elif op == _c.BRANCH:
                if repeated:
                    raise UnsafePattern(
                        "a repeated group contains alternatives (like (a|ab)+); "
                        "use a character class such as [-\\s]+ instead")
                for alt in av[1]:
                    self.items(alt, repeated)
            elif op == _c.SUBPATTERN:
                self.items(av[-1], repeated)
            elif op == getattr(_c, "ATOMIC_GROUP", None):
                self.items(av, repeated)
            elif op in (_c.ASSERT, _c.ASSERT_NOT):
                raise UnsafePattern("lookahead and lookbehind ((?=…), (?!…), "
                                    "(?<=…), (?<!…)) are not supported")
            elif op in _BACKREFS:
                raise UnsafePattern("backreferences (\\1) are not supported")
            elif op == _c.LITERAL:
                self.literals.add(chr(av))


def pattern_problem(pattern) -> Optional[str]:
    """Why `pattern` is refused, in words for the editor, or None if safe."""
    if not isinstance(pattern, str):
        return "a pattern must be text"
    if len(pattern) > MAX_PATTERN:
        return f"the pattern is longer than {MAX_PATTERN} characters"
    try:
        tree = _p.parse(pattern)
    except re.error as e:
        return f"the pattern does not compile ({e})"
    w = _Walk()
    try:
        w.items(tree, False)
    except UnsafePattern as e:
        return str(e)
    if w.variable > MAX_VARIABLE:
        return (f"the pattern has {w.variable} variable-length quantifiers (?, *, +, "
                f"{{m,n}}); at most {MAX_VARIABLE} are allowed")
    try:
        compiled = _compile_re2(pattern, 0)
        _compile_re2(pattern, re.IGNORECASE)          # case folding grows it
    except UnsafePattern as e:
        return str(e)
    t = time.perf_counter()
    for s in _probe_strings(w.literals):
        compiled.search(s)
        compiled.fullmatch(s)
    if time.perf_counter() - t > PROBE_SEC:
        return (f"the pattern took more than {PROBE_SEC:g} s on the test strings "
                f"it is checked against; simplify it")
    return None


def _probe_strings(literals) -> list:
    """Adversarial texts of MAX_INPUT characters: a run of each character the
    pattern names (and a few generic ones), alone and with a different last
    character — the shape that makes a backtracking matcher retry."""
    chars = sorted(set(literals) | set("a1 -.")) [:24]
    out = []
    for ch in chars:
        out.append(ch * MAX_INPUT)
        out.append(ch * (MAX_INPUT - 1) + ("!" if ch != "!" else "?"))
    return out


class TextTooLong(ValueError):
    """A value over MAX_INPUT characters: never matched (the per-value bound
    assumes the cap)."""


class SafePattern:
    """A compiled pattern with the two calls the rules use, both on RE2, on
    at most MAX_INPUT characters."""

    engine = "re2"

    def __init__(self, compiled):
        self._p = compiled

    def _checked(self, text):
        if too_long(text):
            raise TextTooLong(f"the value is longer than {MAX_INPUT} characters")
        return text

    def search(self, text):
        return self._p.search(self._checked(text))

    def fullmatch(self, text):
        return self._p.fullmatch(self._checked(text))


def _compile_re2(pattern, flags):
    try:
        import re2
    except ImportError:                    # fail CLOSED, never fall back to `re`
        raise UnsafePattern("the regular-expression engine (google-re2) is not "
                            "installed, so no pattern can be checked")
    opts = re2.Options()
    opts.log_errors = False                # its log line would quote the pattern
    opts.max_mem = MAX_MEM
    if flags & re.IGNORECASE:
        opts.case_sensitive = False
    try:
        compiled = re2.compile(pattern, opts)
    except re2.error as e:
        raise UnsafePattern(f"the pattern is not supported ({type(e).__name__})")
    size = max(compiled.programsize, compiled.reverseprogramsize)
    if size > MAX_PROGRAM:
        raise UnsafePattern(f"the pattern is too large to check quickly ({size} steps; at "
                            f"most {MAX_PROGRAM}): use smaller counts such as {{0,50}}")
    return compiled


def compile_safe(pattern, flags=0) -> SafePattern:
    """A pattern in the safe subset (UnsafePattern otherwise), matched by RE2.
    Only re.IGNORECASE is honoured among `flags`."""
    why = pattern_problem(pattern)
    if why:
        raise UnsafePattern(why)
    return SafePattern(_compile_re2(pattern, flags))


class BudgetExceeded(RuntimeError):
    """A rule spent its whole time budget; the rest was not checked."""


class Budget:
    """Wall time one rule may spend matching, over all of its values — a SOFT
    limit: checked before each call, charged after it, never interrupting a
    match, so it overruns by at most one value's cost (PER_VALUE_MS)."""

    def __init__(self, seconds: Optional[float] = None):
        self.left = BUDGET_SEC if seconds is None else seconds

    def run(self, fn, *a):
        if self.left <= 0:
            raise BudgetExceeded(
                f"the pattern took more than {BUDGET_SEC:g} s in all; the rest was not checked")
        t = time.perf_counter()
        try:
            return fn(*a)
        finally:
            self.left -= time.perf_counter() - t


def too_long(text: str) -> bool:
    return len(text) > MAX_INPUT
