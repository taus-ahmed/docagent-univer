"""Moved to `app/services/prompt_registry.py` (round 13), next to the loader
that finds it by its own directory (`template_parsing._load_registry`).

This name stays importable: it IS that module (one module object, so
`PROMPT_REGISTRY` and every helper, private ones included, are the same).
"""
import sys

from app.services import prompt_registry as _moved

sys.modules[__name__] = _moved
