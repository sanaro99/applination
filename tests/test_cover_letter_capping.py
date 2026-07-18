"""Cover-letter prompt no longer ships every story body in full.

Guards the Part A change in write_cover_letter: the letter anchors in ONE story,
so only the top candidate gets its full body — the rest are capped to
STORY_CANDIDATE_CAP, and the bio is capped to COVER_LETTER_BIO_CAP. This keeps
the prompt (and every retry-ladder re-send) small.
"""
from src.reference_loader import COVER_LETTER_BIO_CAP, STORY_CANDIDATE_CAP
from src.tailor import Tailor


class _CapturingProvider:
    """Records the user prompt it is handed, then fails so the ladder exhausts.

    We only care about the assembled prompt, not a valid letter, so raising
    keeps the test independent of cover-letter validation rules.
    """

    name = "capture"

    def __init__(self):
        self.prompts: list[str] = []

    def text_call(self, system: str, user: str, max_tokens: int = 1000) -> str:
        self.prompts.append(user)
        raise RuntimeError("stub — capture only")

    def json_call(self, system: str, user: str, max_tokens: int = 2000, *, schema=None) -> dict:
        return {}


def _make_story(i: int) -> dict:
    # Body long enough that STORY_CANDIDATE_CAP truncation is observable.
    body = f"START{i} " + ("x" * (STORY_CANDIDATE_CAP + 1000)) + f" END{i}"
    return {"title": f"Story {i}", "one_liner": f"one-liner {i}", "body": body,
            "tags": [f"tag{i}"]}


def test_cover_letter_caps_nonanchor_bodies_and_bio():
    tailor = Tailor({"cover_letter": [_CapturingProvider()]}, critique_cover_letters=False)
    provider = tailor._chains["cover_letter"][0]

    bio = ("B" * (COVER_LETTER_BIO_CAP + 500)) + " BIOEND"
    stories = [_make_story(1), _make_story(2), _make_story(3)]

    tailor.write_cover_letter(
        source={},
        job={"company": "Acme", "title": "Backend Engineer",
             "location": "Remote", "description": "We build backend systems."},
        user={"full_name": "Test User"},
        bio=bio,
        stories=stories,
    )

    assert provider.prompts, "provider was never called"
    prompt = provider.prompts[0]

    # Story 1 (the anchor) is shipped in full — its end marker survives.
    assert "END1" in prompt

    # Stories 2 and 3 are summarised, not shipped whole — heads present,
    # tails truncated away by STORY_CANDIDATE_CAP.
    assert "START2" in prompt and "START3" in prompt
    assert "END2" not in prompt
    assert "END3" not in prompt

    # Bio is capped to COVER_LETTER_BIO_CAP — its tail marker is dropped.
    assert "BIOEND" not in prompt


def test_single_story_keeps_full_body():
    tailor = Tailor({"cover_letter": [_CapturingProvider()]}, critique_cover_letters=False)
    provider = tailor._chains["cover_letter"][0]

    tailor.write_cover_letter(
        source={},
        job={"company": "Acme", "title": "Backend Engineer",
             "location": "Remote", "description": "We build backend systems."},
        user={"full_name": "Test User"},
        bio="short bio",
        stories=[_make_story(1)],
    )

    assert provider.prompts
    # The lone story is the anchor — full body (end marker) must be present.
    assert "END1" in provider.prompts[0]
