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


from src.intake_extract import Thread, extract_threads


def test_finds_a_known_company_by_name():
    threads = extract_threads("I was at Stripe for two years", companies=["stripe"])
    assert Thread(label="Stripe", kind="company") in threads


def test_finds_vocabulary_topics():
    threads = extract_threads(
        "mostly backend work, a lot of python",
        vocabulary={"backend", "python", "frontend"},
    )
    labels = [t.label for t in threads]
    assert "backend" in labels
    assert "python" in labels
    assert "frontend" not in labels


def test_finds_verb_anchored_phrases():
    threads = extract_threads("I built the payments migration last year")
    assert Thread(label="payments migration", kind="phrase") in threads


def test_phrases_stop_at_two_words_so_they_do_not_swallow_the_sentence():
    threads = extract_threads("I built the payments migration last year")
    assert all("last year" not in t.label for t in threads)


def test_corporate_noise_is_dropped():
    threads = extract_threads("I worked on Inc and shipped Ltd")
    assert [t for t in threads if t.label.lower() in {"inc", "ltd"}] == []


def test_duplicates_are_collapsed_case_insensitively():
    threads = extract_threads(
        "python, Python, PYTHON everywhere", vocabulary={"python"}
    )
    assert len([t for t in threads if t.label.lower() == "python"]) == 1


def test_result_is_capped():
    vocab = {f"tag{i}" for i in range(30)}
    text = " ".join(sorted(vocab))
    assert len(extract_threads(text, vocabulary=vocab, limit=8)) == 8


def test_reads_the_resume_as_well_as_the_typed_text():
    threads = extract_threads("", resume_text="Senior Engineer, Figma", companies=["figma"])
    assert Thread(label="Figma", kind="company") in threads


def test_empty_input_yields_no_chips():
    assert extract_threads("") == []
