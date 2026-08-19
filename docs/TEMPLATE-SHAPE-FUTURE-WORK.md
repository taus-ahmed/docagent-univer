# Template shape — what is left

Written 2026-08-19, after the declaration work (commits `520f5bc`, `2b769e4`).

## Where things stand

A template's shape is derived two ways, and they now coexist deliberately:

- **Declaration** — `grid["regions"]` names a table: the region as the user
  selected it, heading line included, plus which way its records run.
  Read first, by `_declared_bands` in `backend/engine/template_shape.py`.
- **Detection** — the band detector infers tables from adjacent static cells
  with empty rows beneath. Runs on everything not declared.

Detection was kept rather than replaced for three reasons: every template in
production relies on it and none of them declare anything; it costs the user
nothing, so a template that happens to fit its rule just works; and removing it
would turn one silent wrong answer into a hard failure for anyone who had not
migrated yet.

## The migration that has not been done

Right now declaration is opt-in per template, which means the two mechanisms
disagree by default about anything detection gets wrong — BS Luq being the
worked example. The full migration is:

1. **Offer declarations for existing templates.** On open, run the detector,
   show its answer as proposed regions, and let the user accept, adjust, or
   reject them. Detection becomes a suggestion engine rather than a silent
   authority.
2. **Retire detection once every live template declares.** Then a template with
   no declarations is a template with no tables, and that can be said out loud
   in the editor instead of guessed at.
3. **Delete the compatibility branch** in `compute_shape` and the `orientation`
   defaulting, leaving one path.

Step 1 is the whole job; 2 and 3 are cleanup that cannot start until the fleet
has moved. It was not attempted here because it changes what every existing
template does, and that is a migration to run deliberately with the numbers in
front of you, not a side effect of adding a control.

## Coordinate staleness — before adding row/column insertion

A region is stored as absolute coordinates. The editor can only edit cells in
place today, so declarations cannot go stale. **Adding insert/delete row or
column ends that**, and a stale declaration is worse than none: it points
confidently at the wrong cells.

Whoever adds insertion must shift declarations in the same change:

```
insert row at R  ->  r1 += 1 if r1 >= R ;  r2 += 1 if r2 >= R
delete row at R  ->  r1 -= 1 if r1 >  R ;  r2 -= 1 if r2 >  R
                     then DROP the region if r2 <= r1
columns: the same against c1/c2
```

This is unlike `shape`, which is deliberately never stored precisely because it
can be recomputed from the grid. A declaration is user *intent*: it cannot be
recomputed, so it has to be maintained.

The same note sits next to the code in both places that own the coordinates —
`_declared_bands` in `backend/engine/template_shape.py` and the `TableRegion`
type in `frontend/components/templates/DocAgentSpreadsheet.tsx`.

## Smaller things left open

- **Transposed tables cannot be declared inside another table.** Nested regions
  are not supported and are not needed by anything seen so far.
- **A region's `name` is optional.** Unnamed row-oriented two-column tables take
  their heading as their name; anything else becomes "Table N". Naming matters
  because gold labels and the export both key tables by name.
- **The detector still merges side-by-side sections** that share a header row
  into one wide band (BS Luq's two asset sections). Declaring them separately
  fixes it; detection alone cannot tell that shape from a genuine 4-column
  table.
