# UI backlog (Run Q) — noticed, deliberately not done

Run Q did UI1–UI3 only: small, safe changes. Everything below was noticed
along the way and left alone on purpose.

## Results page (`app/extract/page.tsx`)

- The template picker stays on the left panel after a result is shown. Since
  UI1 it no longer changes the shown results, but a reader may still think it
  does. Consider collapsing it into the "New extraction" flow once a job has
  finished.
- "Download ZIP" is offered only when `files.length > 1`. `files` is the
  pending upload list, which is emptied after upload, so a job reopened from
  History (`/extract?job=…`) never offers it. History does offer it.
- The ZIP export has no audit variant. UI3 made it always clean.
- A finished job opened from History shows the picker's template preview in
  the empty state, not the job's own template.
- Status words on this page ("completed", "partial") are still raw. History
  uses `plainStatus` since UI3; the extract page could do the same.

## History (`app/history/page.tsx`)

- A job card's failure line is cut at 140 characters; the full text is the
  tooltip. A "Show full reason" toggle would be friendlier on touch devices.
- "Blank form" needs `blank_forms` in the job list; it is counted per job
  from the stored results (see RUN_Q_REPORT, UI3). Jobs stored before Run Q
  have no `blank_form` mark and read "Done".
- The job list has no filter by plain status ("Needs review", "Failed").

## Review dialog (`components/extract/ReviewPanel.tsx`)

- The accept-all confirmation is a browser `confirm()`. A styled dialog
  listing the Low values by label would let the reviewer see what is being
  accepted.
- The inline "Reviewed" confirmation (UI2) shows after a value mark only via
  the badge; a per-value inline tick would make bulk review clearer.
- Keyboard help ("j/k next/previous · a accept …") is in the header line,
  where it wraps on narrow screens.

## Notifications

- All toasts are now bottom-right (UI2). The "Processing documents…" state
  still has no progress toast and relies on the panel.
