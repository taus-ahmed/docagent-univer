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

## Round 12: the alias key is implemented

`tests/harness/llm_cache.py` (`alias_key`, `build_alias_index`), index
`tests/llm_cache/_alias_index.json`, builder `python -m tests.harness.alias_index`.

* **Native-text requests carry page images too.** The engine is vision-first
  (`extractor._llm_json` sends every rendered page with the prompt), so "a
  request with no images" is nearly empty. "Native-text" is therefore a
  property of the DOCUMENT: no page was OCR'd, so text and prompt come from
  the PDF's own text layer. The alias is the request with each image's bytes
  replaced by its width and height (count kept).
* **The index is built, not guessed.** On this machine (preflight passes)
  the full suite and both harness modes ran with `DOCAGENT_CACHE_TRACE`; a
  request qualifies only if it was an EXACT HIT from a document with no OCR'd
  page. An alias shared by two exact keys would be left out (there were 0).
* **Lookup:** exact key, then alias. A request with no alias (OCR-derived,
  or never indexed) keeps the exact key and the render preflight: with an
  index present a render mismatch no longer fails at install, it raises the
  same named `ReplayEnvironmentError` at that request's lookup, so the
  `DOCAGENT_REPLAY_ENV=skip` policy still skips it by name.
* **Fail closed.** `CacheMiss` and `ReplayEnvironmentError` now derive from
  `BaseException`: the engine's `except Exception` around model calls used to
  turn a miss into a failed call scored as a wrong answer. The runner
  refuses to report a replay with any miss (`replay_misses_are_fatal`).
  This surfaced one test that had passed on a swallowed miss
  (`test_batch_isolation.py::test_no_cache_means_infer_every_time`, fixed to
  assert the request).

| Cache entries (439) | count |
|---|---|
| reachable by alias | **48** |
| exact key only | 391 |
| — of which exercised by suite + harness but OCR-derived | 1 |
| — of which exercised by nothing in the suite or harness (older recordings) | 390 |

Proof (`DOCAGENT_REPLAY_ALIAS_ONLY=1` serves every indexed request by its
alias even where the exact key would hit): full suite 1933 passed, the one
failure being the swallowed-miss test above (identical without the flag);
harness templated **97.2%** with `hits 0, alias_hits 10`, no-template
**96.7%** with `hits 0, alias_hits 20`, 0 misses — the same scores as the
exact path.

Not done: CI still runs the harness only when the preflight passes. Ubuntu's
Poppler may also change image DIMENSIONS (a different rasteriser rounding),
in which case no alias matches; whether it does is the first thing to look at
on the first CI run (the run's `cache` line says how many alias hits it got).

## Round 12: Pillow upgrade measured (scratch venv, never the project venv)

Pillow 10.4.0 → **13.0.0** (latest; `pillow-heif` 0.16.0 unchanged, `pip
check` clean), everything else at the pinned versions, pdftoppm 23.13.0.

| | result |
|---|---|
| control: scratch venv on 10.4.0 | fingerprint `51c162ac8cd244a9` = the recorded one |
| page images, 124 inputs (69 PDFs, images, fixtures), 169 pages | **169/169 byte-identical**; fingerprint unchanged |
| page texts incl. 55 OCR'd inputs | **identical** (0 of 124 inputs differ) |
| cache entries that would miss | **0** (keys hash the identical bytes) |
| full suite + both harness modes on 13.0.0 | **unchanged**: 1934 passed, 0 failed; 97.2% (10 exact hits) / 96.7% (20), 0 misses |
| new warnings | `Image.getdata` is deprecated (removed in Pillow 14, 2027-10-15): `engine/ocr_source.py:179`; ~3,700 warnings in a suite run, no failures |

The pin is therefore moved to 13.0.0 (`requirements.txt`, `constraints.txt`).
Nothing has to be re-recorded. Before Pillow 14, `ocr_source.py:179` must move
to `get_flattened_data` (13.x only), and the OCR identity harness must be
re-run.

Why nothing moved: the JPEG bytes come from the libjpeg-turbo bundled in
Pillow's wheel, and the page pixels from pdftoppm; neither changed between
these two wheels on Windows. The Linux wheel bundles its own build, so the
production image should run `render_fingerprint()` once after the upgrade.

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
