# Run N adversarial review

Reviewed the `d95ce8c` tree, including N2 follow-up `4f67f46`. The executable
review is `tests/test_run_n_adversarial_review.py`: scripted model answers go
through `run_slot_extraction` with synthetic text geometry and form fields. No
provider, live model, network service, or remote file is used.

## Verdicts

| Fix | Verdict | Adversarial result and likely responsible location |
| --- | --- | --- |
| N2: quote-row grounding | **Broken** | The unwrapped wrong-row control is Low, a correct amount repeated on two rows remains High, and a complete multiline quote remains High. **Silent gap:** if the row label itself wraps, `quote_row_lines` finds no row because `slot_extractor.py:1298-1300` requires all non-value quote words on one physical line; unrestricted re-anchoring at `2265-2287` then accepts the same amount from another wrapped row. **False-flag gap:** `1323-1327` rejects a legitimate continuation line when it also carries companion-column text omitted from the field-level quote. |
| N3: numeric wrong-column detection | **Holds** | `Service 70.00` in Description plus a claimed Amount `70.00` is flagged, while a correctly placed Amount control is not. `text_layer.py:1942-1945` prevents any digit-bearing value from using the “inside another cell” exemption; `1895-1929` locates and judges the figure itself. |
| N4: checkbox tie | **Holds with gap** | A clear owner 0.501 pt from the next option is retained without ambiguity, and the existing midpoint case is ambiguous. **Gap:** an X whose centre is inside Alpha is still called tied when Beta starts exactly 0.5 pt away. `ownership.py:231-245` gives containment distance zero, then includes every option within `<= TIE_PT` without making containment decisive. |
| N5: fragment merge record identity | **Broken** | Distinct `Checking-A` / `Savings-B` quotes no longer merge, and the known one-record Pitt fragments remain covered by Run N. **Gap:** `ownership.py:603-615` treats the first row's key appearing anywhere in a later quote as same-record proof. Two records sharing `Household` or `PA` therefore merge when the model misses the second key cell. |
| N6: pages past recovery cap | **Broken** | Several wholly absent pages beyond the cap are each named. The cap is read at `slot_extractor.py:650` through `llm_contract.setting("PAGE_RECOVERY_MAX_CALLS", 4)`; it is not a declared `Settings` attribute, so the test patches that lookup directly. **Silent gap:** pages that contain one surviving row but are still under-half complete are recorded as capped, then `slot_extractor.py:3204-3208` suppresses each reason on the presence of *any* row. A dense first page keeps the aggregate shortfall below `source_inventory.py:671-673`, so nine missing rows can be silent. |
| N7a: unplaced filled widget | **Holds with gap** | An unmatched business widget is reported and an extra address line stays quiet once the party name is captured. **Noise gap:** every other unplaced widget is reported by `source_inventory.py:597-634`; there is no form-metadata distinction, so `PDF Revision = Rev C` makes an otherwise complete form NEEDS_ATTENTION. |
| N7b: word beside empty label | **Holds** | `Employee Name Alice Rivera` with an empty answer produces an empty-slot flag and attention reason through `source_inventory.py:436-479,737-745`. No adversarial defect was found in the requested boundary. |

## Severity 1: silent wrong or incomplete data

### 1. N2 accepts a duplicate amount from the wrong wrapped row

Failing input:

```text
Opening
Balance 100.00
Closing
Balance 170.00
```

The scripted answer says Opening Balance is `170.00` and gives source
`Opening Balance 170.00`. The correct result is Low and flagged. Because
`Opening Balance` occurs on no single line, `quote_row_lines` returns `None`;
the general value re-anchor selects the Closing line and can leave the wrong
Opening Balance High and unflagged. Strict test:
`test_n2_wrapped_label_does_not_let_a_wrong_duplicate_amount_reanchor`.

### 2. N6 suppresses capped-page reasons for partially recovered pages

Failing input: page 1 has 100 transactions; pages 2-5 have four each. The
scripted first answer returns all of page 1 and one row from each later page.
With `PAGE_RECOVERY_MAX_CALLS = 1`, page 2 recovers; pages 3-5 remain at one of
four rows each.

The recovery planner correctly classifies pages 3-5 as deficient and beyond
the cap. The final check treats the one surviving row as proof the page is
present and suppresses its reason. The document-wide count is 107 of 116, so
the 75% aggregate threshold does not report the nine missing rows either.
Strict test: `test_n6_names_partially_missing_pages_beyond_the_cap`.

## Severity 2: correct data wrongly rejected, flagged, or merged

### 1. N2 rejects a correct continuation-line value with companion text

Failing input:

```text
Purpose
Supplier site visit Pacific Steel    Code A-17
```

The answer correctly returns Purpose `Supplier site visit Pacific Steel` and
quotes only the Purpose field. Because `Code A-17` is not in that field-level
quote, the whole physical continuation line is excluded from the row and the
correct Purpose is demoted. Strict test:
`test_n2_correct_neighbouring_value_survives_unquoted_companion_text`.

### 2. N4 flags a geometrically owned X at the inclusive tolerance edge

Alpha spans x=10..40, Beta starts at x=40.5, and the X centre is x=40. The
centre is inside Alpha, but the inclusive 0.5-point rule marks both options
tied and makes the correct Alpha value Low/ambiguous. At 40.501 the passing
control assigns Alpha. Strict test:
`test_n4_an_x_inside_alpha_is_not_a_tie_at_the_exact_tolerance_edge`.

### 3. N5 merges real records that share a key value

Two cases reproduce the same defect through the full pipeline:

- account records `Household / Debit 100.00` and `Household / Credit 250.00`;
- state records `PA / ID-A / Wages 100.00` and `PA / ID-B / Tax 20.00`.

The second model row omits only its key cell but quotes its own printed line.
Because that line repeats the first row's key, `same_record` merges it into the
first row. The credit/tax survives under the wrong entity and the second record
disappears. Strict parameterized test:
`test_n5_repeated_key_text_does_not_merge_two_real_records`.

### 4. N7 turns benign form metadata into missing-business-data attention

An Employee Name slot is filled from its matched widget; a separate filled
`PDF Revision = Rev C` widget is form metadata and has no template slot. The
address-line suppression is correctly narrow enough for the address control,
but there is no comparable metadata classification, so the form is wrongly
put in NEEDS_ATTENTION. Strict test:
`test_n7_legitimately_unmapped_form_metadata_does_not_create_attention`.

No severity-3-only finding was added.

## Test result

The file contains 17 cases: ten passing controls and seven strict-xfail
instances (six defect tests, with N5 parameterized for both shared-account and
shared-state records). Every strict defect is registered in
`tests/KNOWN_FAILING.md`.

```text
pytest tests/test_run_n_adversarial_review.py -q -rxX
10 passed, 7 xfailed
```

Each strict instance was also run explicitly with `--runxfail`: all seven
failed at the assertion describing the defect, with no setup errors.

| Strict instance | Raw assertion outcome under `--runxfail` |
| --- | --- |
| N2 wrapped label | `assert 'high' == 'low'` |
| N2 continuation with companion text | `assert 'low' == 'high'` |
| N4 exact tolerance edge | `assert 'ambig' not in "box 13 alpha x ambiguous: ..."` |
| N5 shared account label | `assert 1 == 2` (one merged row was returned) |
| N5 shared state | `assert 1 == 2` (one merged row was returned) |
| N6 partially missing capped pages | `assert 'page 3' in ''` |
| N7 form metadata | `assert 'rev c' not in "the filled form field ... holds 'rev c' ..."` |
