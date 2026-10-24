# Replay portability: running the recorded-answer tests on another machine

**Status:** proposal. What is implemented is the safe half: CI skips
replay-dependent tests by name instead of failing or passing silently
(`tests/conftest.py`, `DOCAGENT_REPLAY_ENV=skip`, marker `replay`;
`.github/workflows/ci.yml`). Nothing here makes a live call.

## Why the cache does not travel

`tests/llm_cache/` holds 439 recorded model answers (1.29 M tokens in all,
recorded with `gemini-2.5-flash` and `gemini-2.5-flash-lite`). Each is stored
under `request_key` (`tests/harness/llm_cache.py`): a SHA-256 of the method,
text, prompt, system instruction, model **and a hash of every page image's
base64 bytes**. Page images are made by pdf2image → `pdftoppm` (Poppler) →
Pillow's JPEG encoder; another Poppler version rasterises a glyph a pixel
differently and another Pillow encodes the same pixels to different bytes, so
every key changes and every lookup misses. The cache was recorded with
**pdftoppm 23.13.0 and Pillow 10.4.0** (`_render_fingerprint.json`); Ubuntu's
packaged Poppler, and the production image's Debian Poppler, are other
versions.

It is worse than images for scanned pages: their TEXT comes from OCR of the
rendered image, so a different render can change the text too, and the text is
also in the key.

The preflight (`check_replay_environment`) already turns this into one clear
error instead of hundreds of misleading misses — the harness used to report
0.0% accuracy on such a machine.

## Options

| | Re-record in the pinned production image | Image-independent alias key |
|---|---|---|
| What | Build `Dockerfile.backend`, run the suite and both harness modes once inside it in record mode with a real `GEMINI_API_KEY` and a spend cap; commit the new entries and fingerprint; run CI in that image | Store a second key per entry that leaves out the image bytes (keeping their count and dimensions, the text, prompt, system instruction and model); in replay, look it up only after the exact key misses, and count those as `alias_hits` |
| Live calls | up to ~440 (every distinct request the suite and harness make) | none |
| Cost | ~1.3 M tokens; at Flash / Flash-Lite list prices a few dollars at most — **cap the key at $10**; a re-run of the stability check (`--repeat 3`) triples it | none |
| Answers change? | **Yes.** Gemini is not reproducible even at temperature 0 (CLAUDE.md, "Inference is not fully reproducible"); every recorded answer is replaced, so the harness baselines (97.2% / 96.7%), the round-2 evidence and several pinned counts must be re-measured and re-justified | No: the same recorded answers are replayed |
| Covers scanned pages? | Yes, by construction | **No.** OCR text depends on the render, so those keys still miss; those tests stay skipped by name |
| Risk | Losing comparability with every figure recorded so far | An alias hit replays an answer recorded for a different image of the same page; acceptable for regression tests, but it must never be used in record mode or for accuracy claims about images |
| Who | needs Tauseef: a real key, a budget, and a decision to re-baseline | can be done offline |

A third option — pinning Poppler 23.13.0 and Pillow 10.4.0 in CI — fails on
Linux: 23.13.0 here is the MiKTeX Windows build, and the same version number
from another build is not guaranteed to rasterise identically. The fingerprint
check would tell, cheaply, if someone wants to try.

## Recommendation

1. **Now (done):** CI runs everything that does not need replay and skips the
   rest by name (`replay` marker, end-of-run count, job summary), so CI is green
   or red for code reasons only.
2. **Next, offline:** add the alias key for requests whose text came from a
   native text layer (the large majority of the corpus — gold, round 2,
   scenarios). Re-key the 439 entries locally on this machine, where the exact
   keys still match, so each entry gains its alias without any call. Report
   `alias_hits` in the harness's `cache` line so a run says how much of it was
   replayed by alias.
3. **When the OCR tests must run in CI:** re-record only the OCR-derived
   entries inside the production Docker image, with a capped key, and keep a
   separate fingerprint for them. That is a minority of the cache (count them while re-keying), and it leaves the
   gold-corpus answers — and so the headline numbers — untouched.

Re-recording everything (option 1 in full) is the only way to make every test
run in CI, but it re-bases every accuracy figure in the project; it should be
a deliberate decision with before/after numbers, not a CI convenience.
