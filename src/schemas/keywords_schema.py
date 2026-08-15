"""JSON schema for LLM-suggested job-search keywords/role phrases."""
from __future__ import annotations

KEYWORDS_SCHEMA = {
    "type": "object",
    "properties": {
        "keywords": {
            "type": "array",
            "items": {"type": "string", "minLength": 3, "maxLength": 60},
            "minItems": 2,
            "maxItems": 8,
        },
    },
    "required": ["keywords"],
    "additionalProperties": False,
}
