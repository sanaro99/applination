"""Structured-output contracts for evidence-led resume tailoring.

The writer still returns the public ``RESUME_SCHEMA`` consumed by the
renderer.  These schemas describe the internal planning and grounding stages;
they deliberately contain stable evidence identifiers rather than copying
source text between stages.
"""
from __future__ import annotations


_REQUIREMENT = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "text": {"type": "string"},
        "priority": {"type": "integer", "minimum": 1, "maximum": 5},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["id", "text", "priority", "evidence_ids"],
    "additionalProperties": False,
}

_SECTION_SELECTION = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "evidence_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "target_bullets": {"type": "integer", "minimum": 1, "maximum": 5},
        "highlight": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["source_id", "evidence_ids", "target_bullets", "highlight", "reason"],
    "additionalProperties": False,
}

_SKILL_SELECTION = {
    "type": "object",
    "properties": {
        "skill": {"type": "string"},
        "evidence_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "support": {
            "type": "string",
            "enum": ["direct", "entailed", "adjacent"],
        },
    },
    "required": ["skill", "evidence_ids", "support"],
    "additionalProperties": False,
}

CONTENT_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "role_strategy": {"type": "string"},
        "requirements": {"type": "array", "items": _REQUIREMENT},
        "selected_experience": {"type": "array", "items": _SECTION_SELECTION},
        "selected_projects": {"type": "array", "items": _SECTION_SELECTION},
        "selected_skills": {"type": "array", "items": _SKILL_SELECTION},
        "summary_evidence_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "ats_keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "role_strategy",
        "requirements",
        "selected_experience",
        "selected_projects",
        "selected_skills",
        "summary_evidence_ids",
        "ats_keywords",
    ],
    "additionalProperties": False,
}


_VERDICT = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "claim": {"type": "string"},
        "support": {
            "type": "string",
            "enum": ["direct", "entailed", "adjacent", "unsupported", "contradictory"],
        },
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "action": {
            "type": "string",
            "enum": ["accept", "qualify", "rewrite", "remove"],
        },
        "reason": {"type": "string"},
    },
    "required": ["path", "claim", "support", "evidence_ids", "action", "reason"],
    "additionalProperties": False,
}

GROUNDING_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {"type": "array", "items": _VERDICT},
        "passed": {"type": "boolean"},
    },
    "required": ["verdicts", "passed"],
    "additionalProperties": False,
}
