"""User-written regular expressions, run so they cannot hang the process
(Review-3 F4).

A template's `regex` rule and a category rule's `regex` are written by a
user and run against text an uploaded document supplies. Python's `re` is a
backtracking engine: `(a+)+$` over thirty `a`s and a `b` takes longer than
the age of the universe, and it holds the GIL while it does — a thread
timeout cannot stop it, and the whole worker stops with it.

So a pattern is admitted only from a SAFE SUBSET, decided once from its parse
tree, before it ever runs:

  * no repetition of something that itself varies in length — `(a+)+`,
    `(a*)*`, `(\\w+\\s?)+`, `(?:a?b)*` — which is where exponential
    backtracking comes from (a fixed count inside is fine: `(?:\\d{3})+`);
  * no alternation inside a repeated group — `(a|aa)+` — the same blow-up by
    another route (write a character class: `[-\\s]+`);
  * no backreferences, which no linear-time bound covers;
  * at most MAX_UNBOUNDED open-ended quantifiers in all, and MAX_PATTERN
    characters — adjacent quantifiers over the same characters are polynomial
    (`\\d*\\d*\\d*x`), and the exponent is the number of them.

and the text it runs against is capped at MAX_INPUT characters, so the
polynomial case has a measured ceiling (three quantifiers over 512 characters:
~0.15 s). A caller also gets a `Budget`: once a rule has spent BUDGET_SEC over
all of its matches it stops and says so, rather than grinding through a
thousand-row table.

Everything refused is refused OUT LOUD — `pattern_problem` returns the reason
the editor shows at save time, and a rule that still meets one at run time is
UNREADABLE with that reason — never skipped quietly and never guessed.
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
MAX_UNBOUNDED = 3
BUDGET_SEC = 2.0

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
        self.unbounded = 0

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
                if hi == _c.MAXREPEAT:
                    self.unbounded += 1
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
                self.items(av[1], repeated)
            elif op in _BACKREFS:
                raise UnsafePattern("backreferences (\\1) are not supported")


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
    if w.unbounded > MAX_UNBOUNDED:
        return (f"the pattern has {w.unbounded} open-ended quantifiers (*, +, "
                f"{{n,}}); at most {MAX_UNBOUNDED} are allowed")
    return None


def compile_safe(pattern, flags=0) -> "re.Pattern":
    """`re.compile`, for a pattern in the safe subset only (UnsafePattern)."""
    why = pattern_problem(pattern)
    if why:
        raise UnsafePattern(why)
    return re.compile(pattern, flags)


class BudgetExceeded(RuntimeError):
    """A rule spent its whole time budget; the rest was not checked."""


class Budget:
    """Wall time one rule may spend matching, over all of its values."""

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
