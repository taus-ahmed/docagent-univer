"""
DocAgent — Prompt Builder
Dynamically assembles LLM prompts based on client schema and document context.
This is the key differentiator — prompts are never hardcoded.
"""

import yaml
from pathlib import Path
from typing import Optional

from schemas.base_prompts import (
    CLASSIFICATION_PROMPT,
    EXTRACTION_PROMPT,
    EXTRACTION_PROMPT_VISION,
    AUTO_SCHEMA_DETECTION_PROMPT,
)


class ClientSchema:
    """Represents a loaded client configuration."""

    def __init__(self, schema_path: str | Path):
        self.path = Path(schema_path)
        with open(self.path, encoding="utf-8") as f:
            self.raw = yaml.safe_load(f)

        self.client_name = self.raw.get("client_name", "Unknown")
        self.client_id = self.raw.get("client_id", "unknown")
        self.document_types = self.raw.get("document_types", {})

    @property
    def type_names(self) -> list[str]:
        return list(self.document_types.keys())

    def get_type_schema(self, doc_type: str) -> Optional[dict]:
        return self.document_types.get(doc_type)

    def schema_to_text(self, doc_type: str) -> str:
        """Convert a document type schema to a human-readable text block for prompt injection."""
        schema = self.get_type_schema(doc_type)
        if not schema:
            return "No specific schema defined. Extract all visible data fields."

        lines = [f"Document Type: {doc_type}"]
        if schema.get("description"):
            lines.append(f"Description: {schema['description']}")
        lines.append("")
        lines.append("FIELDS TO EXTRACT:")

        for field in schema.get("fields", []):
            req = "REQUIRED" if field.get("required") else "optional"
            lines.append(
                f"  - {field['name']} ({field['type']}, {req}): {field.get('description', '')}"
            )

        if schema.get("line_items"):
            lines.append("")
            lines.append("LINE ITEMS / TABLE ROWS (extract each row):")
            for field in schema["line_items"]:
                lines.append(
                    f"  - {field['name']} ({field['type']}): {field.get('description', '')}"
                )

        return "\n".join(lines)


class PromptBuilder:
    """Assembles prompts dynamically from components."""

    def __init__(self, client_schema: ClientSchema):
        self.schema = client_schema

    def build_classification_prompt(self) -> str:
        """Build the Pass 1 classification prompt."""
        type_list = []
        for type_name, type_config in self.schema.document_types.items():
            desc = type_config.get("description", "")
            type_list.append(f'  - "{type_name}": {desc}')
        types_text = "\n".join(type_list)
        return CLASSIFICATION_PROMPT.format(document_types=types_text)

    def build_extraction_prompt(self, document_type: str, use_vision: bool = False) -> str:
        """Build the Pass 2 extraction prompt with the correct schema injected."""
        schema_text = self.schema.schema_to_text(document_type)
        template = EXTRACTION_PROMPT_VISION if use_vision else EXTRACTION_PROMPT
        return template.format(
            document_type=document_type,
            schema=schema_text,
        )

    def build_auto_schema_prompt(self) -> str:
        """Build prompt for automatic schema detection from a sample document."""
        return AUTO_SCHEMA_DETECTION_PROMPT

    @staticmethod
    def build_custom_extraction_prompt(fields: list[dict], document_type: str = "document") -> str:
        """Build an extraction prompt from a list of field dicts (for ad-hoc extraction).
        Useful when client hasn't set up a YAML schema yet."""
        lines = [f"Document Type: {document_type}", "", "FIELDS TO EXTRACT:"]
        for f in fields:
            req = "REQUIRED" if f.get("required") else "optional"
            lines.append(f"  - {f['name']} ({f.get('type', 'string')}, {req}): {f.get('description', '')}")

        schema_text = "\n".join(lines)
        return EXTRACTION_PROMPT.format(document_type=document_type, schema=schema_text)


def load_client_schema(schema_path: str | Path) -> ClientSchema:
    """Load a client schema from YAML file."""
    return ClientSchema(schema_path)


def load_all_schemas(schemas_folder: str | Path) -> dict[str, ClientSchema]:
    """Load all client schemas from a folder."""
    folder = Path(schemas_folder)
    schemas = {}
    for f in folder.glob("*.yaml"):
        schema = ClientSchema(f)
        schemas[schema.client_id] = schema
    for f in folder.glob("*.yml"):
        schema = ClientSchema(f)
        schemas[schema.client_id] = schema
    return schemas