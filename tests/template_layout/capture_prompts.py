"""Refresh the deterministic prompt-slot capture (no model invocation)."""

from __future__ import annotations

import json

from tests.template_layout.helpers import (
    FIXTURES,
    load_truth,
    prompt_capture,
    scenario_ids,
)


def main():
    capture = {}
    for scenario in scenario_ids():
        capture[scenario] = {
            "slot_descriptions": prompt_capture(scenario),
            "ambiguities": load_truth(scenario).get("prompt_ambiguities", []),
        }
    (FIXTURES / "prompt_capture.json").write_text(
        json.dumps(capture, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"captured prompts for {len(capture)} scenarios")


if __name__ == "__main__":
    main()
