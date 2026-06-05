"""JSON schema for an LLM-generated master-data story.

Matches the frontmatter + body shape that src/reference_loader.load_stories()
expects (title, tags, role_fit, company_fit, one_liner) plus a prose body.
"""
from __future__ import annotations

STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "minLength": 6, "maxLength": 120},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
        },
        "role_fit": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "company_fit": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "one_liner": {"type": "string", "minLength": 20, "maxLength": 220},
        "body": {"type": "string", "minLength": 400, "maxLength": 2400},
    },
    "required": [
        "title", "tags", "role_fit", "company_fit", "one_liner", "body",
    ],
    "additionalProperties": False,
}
