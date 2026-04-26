"""
DocAgent — Validator
Validates extracted data against the client schema.
Flags missing required fields, type mismatches, and low-confidence values.
"""

from typing import Optional
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    low_confidence_fields: list[str] = field(default_factory=list)
    completeness_score: float = 0.0  # 0-1, percentage of fields extracted

    @property
    def needs_review(self) -> bool:
        return not self.is_valid or len(self.low_confidence_fields) > 0 or len(self.warnings) > 0


def validate_extraction(extracted: dict, schema: dict) -> ValidationResult:
    """Validate extracted data against a document type schema."""
    result = ValidationResult()

    if not extracted:
        result.is_valid = False
        result.errors.append("Extraction returned empty result")
        return result

    extracted_data = extracted.get("extracted_data", {})
    schema_fields = schema.get("fields", [])

    total_fields = len(schema_fields)
    filled_fields = 0

    for field_def in schema_fields:
        fname = field_def["name"]
        required = field_def.get("required", False)

        field_data = extracted_data.get(fname)

        if field_data is None or (isinstance(field_data, dict) and field_data.get("value") is None):
            if required:
                result.errors.append(f"Required field '{fname}' is missing")
                result.is_valid = False
            else:
                result.warnings.append(f"Optional field '{fname}' not found")
            continue

        filled_fields += 1

        # Check confidence
        if isinstance(field_data, dict):
            confidence = field_data.get("confidence", "high")
            if confidence == "low":
                result.low_confidence_fields.append(fname)
                result.warnings.append(f"Field '{fname}' has low confidence — needs review")

            # Type validation
            value = field_data.get("value")
            expected_type = field_def.get("type", "string")
            _validate_type(fname, value, expected_type, result)

    result.completeness_score = filled_fields / total_fields if total_fields > 0 else 0

    # Validate line items if present in schema
    if schema.get("line_items") and extracted.get("line_items"):
        _validate_line_items(extracted["line_items"], schema["line_items"], result)

    return result


def _validate_type(fname: str, value, expected_type: str, result: ValidationResult):
    """Check if extracted value matches expected type."""
    if value is None:
        return

    if expected_type == "number":
        if not isinstance(value, (int, float)):
            try:
                float(str(value).replace(",", "").replace("$", "").replace("€", "").replace("£", ""))
            except (ValueError, TypeError):
                result.warnings.append(f"Field '{fname}' expected number, got: {type(value).__name__}")

    elif expected_type == "date":
        if isinstance(value, str):
            import re
            date_pattern = r'\d{4}-\d{2}-\d{2}'
            if not re.match(date_pattern, value):
                result.warnings.append(f"Field '{fname}' date not in YYYY-MM-DD format: {value}")


def _validate_line_items(items: list, schema_fields: list, result: ValidationResult):
    """Validate line items array."""
    if not isinstance(items, list):
        result.warnings.append("line_items should be an array")
        return

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            result.warnings.append(f"Line item {i} is not an object")
            continue

        for field_def in schema_fields:
            fname = field_def["name"]
            field_data = item.get(fname)
            if field_data and isinstance(field_data, dict):
                confidence = field_data.get("confidence", "high")
                if confidence == "low":
                    result.low_confidence_fields.append(f"line_items[{i}].{fname}")
