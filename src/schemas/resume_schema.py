"""Strict JSON schemas for renderer-facing resume output and legacy tools.

These are intentionally minimal — provider strict-mode JSON-schema support
varies, and complex constructs like `anyOf` with length ranges fail silently
on some backends. Instead we enforce:
  - structural correctness (required fields, types, no extra properties)
  - generous limits that permit concise, 1.5-line, and two-line bullets

Fine-grained character bands are intentionally not part of the v2 pipeline.
Page layout is enforced after editorial generation in ``resume_builder``.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Renderer-facing resume draft — used by editorial write and factual repair
# ---------------------------------------------------------------------------

# A skills group entry. Skills are arrays of {group, items} not free-form dicts
# because the renderer's _normalize_skills() prefers this canonical shape.
_SKILLS_GROUP_SCHEMA = {
    "type": "object",
    "properties": {
        "group": {"type": "string"},
        "items": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
    },
    "required": ["group", "items"],
    "additionalProperties": False,
}

_EXPERIENCE_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "company":  {"type": "string"},
        "role":     {"type": "string"},
        "location": {"type": "string"},
        "dates":    {"type": "string"},
        "bullets": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "string",
                # Reject only empty/pathologically long values; layout is a
                # downstream page-level concern.
                "minLength": 30,
                "maxLength": 320,
            },
        },
    },
    "required": ["company", "role", "bullets"],
    "additionalProperties": False,
}

_PROJECT_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "name":    {"type": "string"},
        "tech":    {"type": "string"},
        "link":    {"type": "string"},
        "bullets": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 30, "maxLength": 320},
        },
    },
    "required": ["name", "bullets"],
    "additionalProperties": False,
}

_EDUCATION_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "school":     {"type": "string"},
        "degree":     {"type": "string"},
        "location":   {"type": "string"},
        "dates":      {"type": "string"},
        "gpa":        {"type": "string"},
        "coursework": {"type": "string"},
    },
    "required": ["school", "degree"],
    "additionalProperties": True,   # honors/specializations/minor live here
}

RESUME_SCHEMA = {
    "type": "object",
    "properties": {
        "summary":      {"type": "string", "minLength": 80, "maxLength": 500},
        "skills":       {"type": "array", "items": _SKILLS_GROUP_SCHEMA, "minItems": 3},
        "experience":   {"type": "array", "items": _EXPERIENCE_ENTRY_SCHEMA, "minItems": 1},
        "projects":     {"type": "array", "items": _PROJECT_ENTRY_SCHEMA},
        "education":    {"type": "array", "items": _EDUCATION_ENTRY_SCHEMA, "minItems": 1},
        "ats_keywords": {"type": "array", "items": {"type": "string"}, "minItems": 6},
    },
    "required": ["summary", "skills", "experience", "education", "ats_keywords"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Legacy compatibility schemas (not used by the v2 production pipeline)
# ---------------------------------------------------------------------------

CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {"type": "array", "items": {"type": "string"}},
        "severity": {
            "type": "string",
            "enum": ["none", "minor", "medium", "major"],
        },
        "passed": {"type": "boolean"},
    },
    "required": ["issues", "severity", "passed"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Relinefit rescue
# ---------------------------------------------------------------------------

RELINEFIT_SCHEMA = {
    "type": "object",
    "properties": {
        "rewrites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idx":  {"type": "integer", "minimum": 0},
                    "text": {"type": "string", "minLength": 50, "maxLength": 230},
                },
                "required": ["idx", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["rewrites"],
    "additionalProperties": False,
}
