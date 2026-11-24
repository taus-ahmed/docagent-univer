# UI backlog (Run Q) — noticed, deliberately not done

Run Q did UI1–UI3 only: small, safe changes. Everything below was noticed
along the way and left alone on purpose.

## Results page (`app/extract/page.tsx`)

- Done in Run Q Phase 3 (UI3): the template picker is replaced by "Template
  used" while a job is open; Download ZIP follows the job's own document
  count (a job reopened from History offers it); the empty state previews the
  job's template; the status line uses `plainStatus`.
- The ZIP export has no audit variant. UI3 made it always clean.

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
