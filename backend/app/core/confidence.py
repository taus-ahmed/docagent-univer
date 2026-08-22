"""
The confidence vocabulary — one definition, used by the engine, the API, the
exporters and (mirrored) the UI.

Four different claims. They were three words ("high"/"medium"/"low") until
Phase 8, and two of those words carried a promise nothing backed:

    HIGH        Grounded in the document AND it answers a question the USER
                asked, because the user authored the slot's label. Only
                reachable with a user-authored template.

    GROUNDED    Grounded in the document. Full stop. The slot's label was
                written by the same model chain that produced the value, so
                nothing independent establishes that the value BELONGS there.
                Grounding proves the text came from the page, never that it
                belongs in that slot — asking the model whether its own answer
                fits its own label is circular. This is the most no-template
                extraction can honestly claim.

    UNVERIFIED  No text layer existed to check the span against at all: an
                image upload, or a scanned PDF with no extractable text. The
                value may well be perfect; we simply did not check. Reported
                as "medium" before Phase 8, which implied a measurement that
                never happened.

    LOW         Checked, and failed: the span could not be found, or the cell
                carries more than one piece of information.

    EDITED      A human typed this value in the results grid. It is an
                assertion by the user, not an extraction, and must never
                inherit a grounding claim the engine never made.

    MEDIUM      Document level only, and a genuine mixed state: most values
                grounded, one or two not. Never a per-cell level.

HIGH and GROUNDED are both "confident" for gating purposes. They are never
merged for display — telling them apart is the entire point.
"""

HIGH = "high"
GROUNDED = "grounded"
UNVERIFIED = "unverified"
MEDIUM = "medium"
LOW = "low"
EDITED = "edited"

#: Levels meaning "we can stand behind this cell". Test membership in this
#: rather than `== "high"`, which silently excluded every inferred cell.
CONFIDENT_LEVELS = (HIGH, GROUNDED)

#: What a human sees. The engine's level is an identifier; this is the claim
#: spelled out, and it is what goes in the spreadsheet and the UI.
DISPLAY = {
    HIGH:       "High",
    GROUNDED:   "Verbatim from the document",
    UNVERIFIED: "Unverified — no text layer",
    MEDIUM:     "Medium",
    LOW:        "Low",
    EDITED:     "Edited by hand",
}

#: Short form, for a narrow column.
DISPLAY_SHORT = {
    HIGH:       "High",
    GROUNDED:   "Verbatim",
    UNVERIFIED: "Unverified",
    MEDIUM:     "Medium",
    LOW:        "Low",
    EDITED:     "Edited",
}


def display(level, short=False):
    """Human-facing text for a confidence level. Unknown levels pass through
    unchanged rather than being swallowed — a level we do not recognise is
    worth seeing, not hiding."""
    if not level:
        return ""
    table = DISPLAY_SHORT if short else DISPLAY
    return table.get(str(level), str(level))
