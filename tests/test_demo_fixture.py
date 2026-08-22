"""The committed demo fixture has to be loadable by the real loaders, and it
has to stay fictional -- this repository is public."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo_data"
MASTER = DEMO / "master_data"


def _config() -> dict:
    return yaml.safe_load((DEMO / "config.yaml").read_text(encoding="utf-8"))


def _resume() -> dict:
    return yaml.safe_load((MASTER / "resume.yaml").read_text(encoding="utf-8"))


def test_fixture_exists():
    assert (DEMO / "config.yaml").is_file()
    assert (MASTER / "resume.yaml").is_file()
    assert (MASTER / "bio.md").is_file()


def test_config_routes_to_the_demo_provider():
    llm = _config()["llm"]
    assert llm["primary"] == "demo"
    # A fallback would be a real provider, and reaching it would mean spending
    # somebody's money on a shared public account.
    assert not llm.get("fallbacks")


def test_config_carries_no_api_keys():
    """A committed api_key in a public repo is the failure this guards."""
    for name, block in _config()["llm"].items():
        if isinstance(block, dict):
            assert not block.get("api_key"), f"llm.{name}.api_key must be empty"


def test_profile_derives_a_new_grad():
    from src.profile import derive_profile

    profile = derive_profile(_resume())
    assert profile["identity_titles"]
    assert profile["seniority"] == "new-grad"
    assert profile["education_close"]


def test_stories_have_the_frontmatter_the_matcher_needs():
    from src.reference_loader import load_stories

    stories = load_stories(MASTER / "stories")
    assert len(stories) >= 5
    for story in stories:
        assert story["tags"], story["title"]
        assert story["role_fit"], story["title"]
        assert story["company_fit"], story["title"]
        assert story["one_liner"], story["title"]
        assert len(story["body"].split()) > 80, story["title"]


def test_stories_match_a_relevant_job():
    """A story bank the matcher never selects from is decoration."""
    from src.reference_loader import load_stories, match_stories

    stories = load_stories(MASTER / "stories")
    matched = match_stories(
        "Backend engineer working on data pipelines, reliability and "
        "observability in Python on Kubernetes.",
        "Datadog",
        "Data Platform Engineer",
        stories,
    )
    assert matched


def test_example_letters_load():
    from src.reference_loader import load_example_letters

    letters = load_example_letters(MASTER / "cover_letters" / "examples")
    assert len(letters) >= 2
    for letter in letters:
        assert letter["company"]
        assert letter["role"]
        assert len(letter["body"].split()) > 80


@pytest.mark.parametrize("field", ["email", "phone"])
def test_contact_details_are_reserved_examples(field):
    value = str(_config()["user"][field])
    assert "555-0100" in value or value.endswith("@applination.app")


def test_persona_employers_are_invented():
    """Real companies appear in this fixture only as public job postings. A
    real company must never appear to have employed a person who does not
    exist."""
    invented = {"Northwind Analytics", "Trellis Labs", "Cascadia State University"}
    for entry in _resume()["experience"]:
        assert entry["company"] in invented, entry["company"]
    for entry in _resume()["education"]:
        assert entry["school"] in invented, entry["school"]


def test_no_em_dashes_in_rendered_content():
    """src/tailor.py strips em dashes for ATS safety; the master data should
    already agree with what the pipeline produces."""
    for path in [MASTER / "resume.yaml", MASTER / "bio.md"]:
        assert "—" not in path.read_text(encoding="utf-8"), path.name
    for path in (MASTER / "stories").glob("*.md"):
        assert "—" not in path.read_text(encoding="utf-8"), path.name
