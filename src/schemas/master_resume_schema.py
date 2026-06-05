"""Strict JSON schema for importing a raw resume into the MASTER resume format.

This is the shape of ``master_data/resume.yaml`` (the source-of-truth library),
which differs from the tailored-output ``RESUME_SCHEMA``: it keeps
``summary_options`` (plural), ``core_skills``/``ats_adjacent_skills``,
``start_date``/``end_date`` (not a combined ``dates`` string), and
``bullets_all`` (the full pool the tailor selects from). Used by
``content_studio.import_resume()`` during onboarding.
"""
from __future__ import annotations

_SKILL_GROUP = {
    "type": "object",
    "properties": {
        "group": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    },
    "required": ["group", "items"],
    "additionalProperties": False,
}

_EXPERIENCE = {
    "type": "object",
    "properties": {
        "company": {"type": "string"},
        "role": {"type": "string"},
        "location": {"type": "string"},
        "start_date": {"type": "string"},
        "end_date": {"type": "string"},
        "bullets_all": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["company", "role", "bullets_all"],
    "additionalProperties": False,
}

_PROJECT = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "tech": {"type": "string"},
        "link": {"type": "string"},
        "bullets_all": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "bullets_all"],
    "additionalProperties": False,
}

_EDUCATION = {
    "type": "object",
    "properties": {
        "school": {"type": "string"},
        "degree": {"type": "string"},
        "location": {"type": "string"},
        "start_date": {"type": "string"},
        "end_date": {"type": "string"},
        "gpa": {"type": "string"},
        "coursework": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["school", "degree"],
    "additionalProperties": True,
}

_PROFILE = {
    "type": "object",
    "properties": {
        "identity_titles": {"type": "array", "items": {"type": "string"}},
        "seniority": {"type": "string", "enum": ["student", "new-grad", "professional"]},
    },
    "required": ["identity_titles", "seniority"],
    "additionalProperties": False,
}

MASTER_RESUME_SCHEMA = {
    "type": "object",
    "properties": {
        "profile": _PROFILE,
        "summary_options": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "core_skills": {"type": "array", "items": {"type": "string"}},
        "ats_adjacent_skills": {"type": "array", "items": {"type": "string"}},
        "skills": {"type": "array", "items": _SKILL_GROUP, "minItems": 1},
        "experience": {"type": "array", "items": _EXPERIENCE, "minItems": 1},
        "projects": {"type": "array", "items": _PROJECT},
        "education": {"type": "array", "items": _EDUCATION, "minItems": 1},
    },
    "required": ["summary_options", "core_skills", "skills", "experience", "education"],
    "additionalProperties": False,
}
