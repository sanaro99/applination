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


from src.intake_extract import SearchTerms, extract_search_terms


def test_picks_up_a_role_title_from_the_text():
    terms = extract_search_terms("I'm a backend engineer these days")
    assert "backend engineer" in terms.keywords
    assert terms.guessed is False


def test_picks_up_role_titles_from_the_resume():
    terms = extract_search_terms("", resume_text="Senior Data Scientist, Acme")
    assert any("data scientist" in k for k in terms.keywords)


def test_includes_vocabulary_terms():
    terms = extract_search_terms(
        "backend engineer working in python", vocabulary={"python"}
    )
    assert "python" in terms.keywords


def test_falls_back_to_defaults_and_says_so():
    terms = extract_search_terms("")
    assert terms.guessed is True
    assert terms.keywords


def test_keywords_are_capped_and_unique():
    terms = extract_search_terms(
        "python python typescript rust go java scala kotlin",
        vocabulary={"python", "typescript", "rust", "go", "java", "scala", "kotlin"},
        limit=4,
    )
    assert len(terms.keywords) == 4
    assert len(set(terms.keywords)) == 4


def test_is_hashable_so_it_can_be_cached():
    assert isinstance(extract_search_terms("backend engineer"), SearchTerms)
    hash(extract_search_terms("backend engineer"))


# --------------------------------------------------------------------------- #
# Grouped taxonomy
#
# The tag picker offers the taxonomy back to the user, and a flat set of 60
# tags is not something anyone browses. The groups the file already writes are
# the only grouping that exists, so they are what gets parsed.
# --------------------------------------------------------------------------- #
from src.intake_extract import load_vocabulary_groups  # noqa: E402


def test_groups_keep_the_files_own_order_and_labels():
    groups = load_vocabulary_groups(SAMPLE_INDEX)
    assert [g.label for g in groups] == ["Technical areas", "Specific tech", "Role types"]


def test_a_groups_tags_keep_the_files_own_order():
    groups = load_vocabulary_groups(SAMPLE_INDEX)
    assert groups[0].tags == [
        "ai", "llm", "rag", "backend", "platform", "devtools", "security",
    ]


def test_the_parenthetical_says_which_frontmatter_field_a_group_belongs_to():
    groups = load_vocabulary_groups(SAMPLE_INDEX)
    assert [g.field for g in groups] == ["tags", "tags", "role_fit"]


def test_company_types_bind_to_company_fit():
    groups = load_vocabulary_groups(
        SAMPLE_INDEX + "\n**Company types (company_fit):** finance, startup\n"
    )
    assert groups[-1].field == "company_fit"
    assert groups[-1].tags == ["finance", "startup"]


def test_the_flat_vocabulary_is_the_union_of_the_groups():
    groups = load_vocabulary_groups(SAMPLE_INDEX)
    assert load_vocabulary(SAMPLE_INDEX) == {t for g in groups for t in g.tags}


def test_missing_taxonomy_section_yields_no_groups():
    assert load_vocabulary_groups("# Stories Index\n\nNo taxonomy here.\n") == []
