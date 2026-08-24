"""Deterministic, LLM-free extraction of conversation chips.

Precision over recall throughout: four good chips beat eight with two absurd
ones, because the user sees these as "things you mentioned" and a wrong one
reads as the product not having listened.
"""
from __future__ import annotations

from src.intake_extract import load_vocabulary

SAMPLE_INDEX = """# Stories Index

Prose that must not become vocabulary.

## Tag taxonomy (expand as needed)

**Technical areas:** ai, llm, rag, backend, platform,
devtools, security

**Specific tech:** python, typescript, fastapi

**Role types (role_fit):** swe, ml-engineer, sre
"""


def test_reads_comma_lists_including_continuation_lines():
    vocab = load_vocabulary(SAMPLE_INDEX)
    assert {"ai", "llm", "rag", "backend", "platform", "devtools", "security"} <= vocab
    assert {"python", "typescript", "fastapi"} <= vocab
    assert {"swe", "ml-engineer", "sre"} <= vocab


def test_ignores_prose_outside_the_taxonomy_section():
    vocab = load_vocabulary(SAMPLE_INDEX)
    assert "prose" not in vocab
    assert "vocabulary" not in vocab


def test_ignores_the_headings_own_parenthetical():
    vocab = load_vocabulary(SAMPLE_INDEX)
    assert "expand" not in vocab
    assert "needed" not in vocab


def test_ignores_the_bold_label_text_itself():
    vocab = load_vocabulary(SAMPLE_INDEX)
    assert "technical" not in vocab
    assert "areas" not in vocab
    assert "role_fit" not in vocab


def test_missing_taxonomy_section_yields_empty_set():
    assert load_vocabulary("# Stories Index\n\nNo taxonomy here.\n") == set()
