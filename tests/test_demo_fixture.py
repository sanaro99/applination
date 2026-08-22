"""The committed demo fixture has to be loadable by the real loaders, and it
has to stay fictional -- this repository is public."""
from __future__ import annotations

import re
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


def _document_text(path: Path) -> str:
    """Everything inside a committed document, including the parts nobody
    looks at: docx is a zip, and a PDF carries its hyperlink targets as
    annotations rather than as visible text."""
    import zipfile

    if path.suffix == ".docx":
        try:
            with zipfile.ZipFile(path) as z:
                return "\n".join(
                    z.read(n).decode("utf-8", "ignore") for n in z.namelist()
                )
        except zipfile.BadZipFile:
            return ""
    return path.read_bytes().decode("utf-8", "ignore")


@pytest.mark.parametrize(
    "path",
    sorted(p for p in (DEMO / "output").rglob("*") if p.suffix in {".docx", ".pdf"}),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_committed_documents_carry_only_the_demo_persona(path):
    """Every contact detail in a committed document must be the demo's.

    This exists because a real leak got this far: `python -m src.tweak` without
    `--user` defaults to the *owner*, so a regenerated resume embedded the
    repository owner's real email, LinkedIn and GitHub as PDF hyperlink
    annotations. The visible text still said John Doe, so reading the document
    did not reveal it, and this repository is public.
    """
    text = _document_text(path)

    # Hyperlink targets specifically, because that is where the leak was and
    # because they survive in the clear: a PDF keeps them as `/URI(...)`
    # annotations even when the visible text is a compressed stream, and .docx
    # keeps them as relationship `Target="..."` entries. A looser scan over the
    # whole byte stream matches compressed binary that happens to contain an
    # "@" and reports it as an email address.
    found = re.findall(r"/URI\s*\(([^)]*)\)", text)
    found += re.findall(r'Target="([^"]*)"', text)
    # Plus any strict, dotted email address in readable text.
    found += re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    found = [
        f for f in found
        if "@" in f or "linkedin.com" in f or "github.com" in f
    ]
    allowed = {"demo@applination.app", "john-doe-demo"}
    for item in found:
        assert any(a in item for a in allowed), (
            f"{path.name} carries a contact detail that is not the demo "
            f"persona's: {item}"
        )

    # A resume with no contact details at all would pass the loop above
    # vacuously, so require the demo's own on the documents that expose text.
    if path.suffix == ".docx" and path.name.startswith("resume"):
        assert "demo@applination.app" in text, f"{path.name} has no demo contact"


def test_no_em_dashes_in_rendered_content():
    """src/tailor.py strips em dashes for ATS safety; the master data should
    already agree with what the pipeline produces."""
    for path in [MASTER / "resume.yaml", MASTER / "bio.md"]:
        assert "—" not in path.read_text(encoding="utf-8"), path.name
    for path in (MASTER / "stories").glob("*.md"):
        assert "—" not in path.read_text(encoding="utf-8"), path.name
