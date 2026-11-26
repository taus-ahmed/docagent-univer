"use client";

// Run Q Phase 3, UI1: "New extraction" is ONE action wherever it appears —
// a fresh extract page: no files, no result, the template picker reset.
// It never re-runs or alters the job on screen; that job stays in History
// and stays downloadable.

import Link from "next/link";

interface Props {
  /** clears the extract page's own state when already on it */
  onNew?: () => void;
}

export default function NewExtractionButton({ onNew }: Props) {
  return (
    <Link className="btn btn-secondary btn-full" href="/extract" onClick={onNew}
          title="Start a new extraction; this job stays in History as it is">
      New extraction
    </Link>
  );
}
