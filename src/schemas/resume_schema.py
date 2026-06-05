"""Strict JSON schemas for LLM-produced resume / critique / relinefit outputs.

These are intentionally minimal — provider strict-mode JSON-schema support
varies, and complex constructs like `anyOf` with length ranges fail silently
on some backends. Instead we enforce:
  - structural correctness (required fields, types, no extra properties)
  - generous length bands (50-300 chars per bullet)

The deterministic line_fitter in src/line_fitter.py handles the finer-grained
"90-105 single OR 170-220 double" rule AFTER the LLM returns its draft.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Resume tailoring — used by _run_tailor, _run_keyword_fix, _run_revise
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
                # Wide range — line_fitter handles the band fitting post-LLM.
                # We just reject malformed outputs (empty / pathologically long).
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
# Resume critique — used by _run_critique
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
# Relinefit rescue — used by _run_relinefit_rescue
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
