"""Profile-context assembler for the Coach conversational assistant.

Pure functions, no DB. Loads the candidate's master data the same way the
single-job worker does, picks the most relevant stories via the existing
``reference_loader.match_stories`` scorer, and builds the (system, user)
strings for an LLM ``text_call``.

The voice + anti-fabrication language is deliberately reused from
``src/tailor.py`` (``write_cover_letter`` and ``answer_questions``) so the
Coach stays grounded in the candidate's real experience and authentic voice.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.profile import profile_summary_block
from src.reference_loader import BIO_CAP, STORY_BODY_CAP, load_stories

if TYPE_CHECKING:  # avoid a hard import cycle / DB import at module load
    from .db import Application, ChatMessage

MASTER_PATH = Path(__file__).resolve().parent.parent / "master_data"

# Rough char budgets so the assembled prompt stays inside the providers'
# context windows (tailor.py works to a similar ~8K-token ceiling). The bio /
# story-body budgets are shared with tailor.py via reference_loader so every
# prompt assembler agrees; _JD_CAP / _HISTORY_CAP are coach-specific.
_BIO_CAP = BIO_CAP
_STORY_BODY_CAP = STORY_BODY_CAP
_JD_CAP = 1500
_HISTORY_CAP = 6000


def load_profile_bundle() -> dict:
    """Load {master, bio, stories} once per request.

    Mirrors server/single_job.py's master-data loading.
    """
    master_file = MASTER_PATH / "resume.yaml"
    master = yaml.safe_load(master_file.read_text(encoding="utf-8")) or {}
    bio_path = MASTER_PATH / "bio.md"
    bio = bio_path.read_text(encoding="utf-8") if bio_path.exists() else ""
    stories = load_stories(MASTER_PATH / "stories")
    return {"master": master, "bio": bio, "stories": stories}


def pick_stories(
    bundle: dict, *, question: str, app: "Application | None"
) -> list[dict]:
    """Pick the top-3 most relevant stories.

    Grounded session: match against the application's JD/company/title.
    Ungrounded: treat the user's question text as the "JD" so tag/keyword
    overlap still surfaces topical stories.
    """
    from src.reference_loader import match_stories

    stories = bundle.get("stories") or []
    if not stories:
        return []
    if app is not None:
        return match_stories(
            app.description or "", app.company or "", app.title or "",
            stories, top_k=3,
        )
    return match_stories(question or "", "", "", stories, top_k=3)


# The compact master-resume view now lives in src/profile.py so that
# tailor.answer_questions and the Coach ground on identical facts.
_profile_summary_block = profile_summary_block


def _story_block(stories: list[dict]) -> str:
    """Reuse the answer_questions story-block shape from tailor.py."""
    block = "\n\n".join(
        f"STORY: {s.get('title', '')}\n"
        f"One-liner: {s.get('one_liner', '')}\n"
        f"{s.get('body', '')[:_STORY_BODY_CAP]}"
        for s in stories[:3]
    )
    return block or "(no stories available)"


def _history_block(
    history: "list[ChatMessage]", budget_chars: int = _HISTORY_CAP
) -> str:
    """Render prior turns as a transcript, trimmed oldest-first to a budget.

    text_call only takes (system, user) — there is no multi-turn message
    array — so history is folded into the user prompt.
    """
    if not history:
        return "(this is the first message)"
    lines = [
        f"{'You' if m.role == 'user' else 'Coach'}: {m.content}"
        for m in history
    ]
    text = "\n\n".join(lines)
    if len(text) > budget_chars:
        text = text[-budget_chars:]
        # Drop a partial leading turn so we start on a clean boundary.
        nl = text.find("\n\n")
        if nl != -1:
            text = text[nl + 2:]
    return text


def _first_name(master: dict, user: dict | None) -> str:
    if user and user.get("full_name"):
        return str(user["full_name"]).split()[0]
    # Fall back to a sensible default; the bio/profile carry the real identity.
    return "the candidate"


# Shared rules reused across chat / interview / essay system prompts. The
# anti-fabrication clause mirrors the BINDING language in src/tailor.py.
def _grounding_rule() -> str:
    return (
        "GROUNDING (this overrides every other instruction): Only use the "
        "candidate's REAL experience supplied below — the profile summary, the "
        "story material, and the bio voice. Never invent projects, employers, "
        "technologies, metrics, or experiences not present in that material, "
        "and never name technologies not mentioned there. If something is not "
        "covered by the material, say so plainly rather than fabricating.\n\n"
    )


def _voice_rule(name: str) -> str:
    return (
        f"VOICE: Write in {name}'s first-person voice. Absorb the tone from the "
        "bio; do not quote or reproduce it. No em dashes (—), use commas or "
        "semicolons. No 'passionate', 'thrilled', or 'excited to apply'. Plain, "
        "specific prose over vague enthusiasm.\n\n"
    )


def _grounding_block(app: "Application | None", *, label: str = "PREPARING FOR THIS ROLE") -> str:
    if app is None:
        return ""
    return (
        f"{label}:\n"
        f"Company: {app.company or ''} | Title: {app.title or ''} | "
        f"Location: {app.location or ''}\n"
        f"JD excerpt:\n{(app.description or '')[:_JD_CAP]}\n\n"
    )


def _profile_context(bundle: dict, name: str, stories: list[dict]) -> str:
    """The CANDIDATE VOICE + PROFILE SUMMARY + STORY MATERIAL block shared by
    every Prepwork prompt."""
    bio = bundle.get("bio") or ""
    master = bundle.get("master") or {}
    return (
        f"CANDIDATE VOICE (how {name} writes — absorb the tone, do not "
        f"reproduce this section):\n{bio[:_BIO_CAP]}\n\n"
        f"PROFILE SUMMARY:\n{_profile_summary_block(master)}\n\n"
        f"STORY MATERIAL (the only experiences you may draw on):\n"
        f"{_story_block(stories)}\n\n"
    )


def build_coach_prompt(
    bundle: dict,
    *,
    question: str,
    history: "list[ChatMessage]",
    app: "Application | None",
    stories: list[dict],
    user: dict | None = None,
    mode: str = "chat",
) -> tuple[str, str]:
    """Return (system, user) strings for an LLM text_call.

    Reuses the voice + BINDING anti-fabrication language from src/tailor.py.
    ``mode`` is "chat" (free conversation) or "interview" (coached mock
    interview: feedback on the answer + a model answer + the next question).
    """
    master = bundle.get("master") or {}
    name = _first_name(master, user)

    if mode == "interview":
        role_line = (
            f" for the {app.title} role at {app.company}"
            if app is not None else ""
        )
        system = (
            f"You are Coach, running a mock interview{role_line} with {name}. "
            f"{name}'s latest message is their answer to the question you asked "
            f"in your previous turn.\n\n"
            + _grounding_rule()
            + _voice_rule(name)
            + "HOW TO RESPOND each turn, in this order:\n"
            "1. Feedback: 2-3 sentences of specific, honest critique of the "
            "answer — what landed, what to tighten, whether it used a concrete "
            "story and metric. Ground it in the candidate's real material.\n"
            "2. Model answer: a tightened version of how the candidate could "
            "answer, in their first-person voice, anchored in a real story. "
            "Never fabricate.\n"
            "3. Next question: ask exactly ONE new interview question and stop. "
            "Mix behavioral and technical questions; when a role/JD is given, "
            "tailor them to it.\n\n"
            "Use short bold labels (Feedback / Model answer / Next question). "
            "Keep it focused; do not dump multiple questions at once."
        )
    else:
        system = (
            f"You are Coach, a career assistant for {name}. You help {name} talk "
            f"about their real background, surface their strongest material, and "
            f"draft answers to application, scholarship, and behavioral/interview "
            f"questions.\n\n"
            + _grounding_rule()
            + _voice_rule(name)
            + "FORMAT: This is a chat, not an ATS document, so light Markdown "
            "(short lists, bold, headers) is fine when it makes the answer "
            "clearer. Be conversational and concrete. When drafting an answer "
            "the candidate will submit somewhere, make it easy to copy out."
        )

    closing = (
        "Respond with feedback, a model answer, then your next question."
        if mode == "interview"
        else "Respond directly. Stay grounded in the material above; never "
        "claim experience the candidate doesn't have. No em dashes."
    )
    user_prompt = (
        _profile_context(bundle, name, stories)
        + _grounding_block(app)
        + f"CONVERSATION SO FAR:\n{_history_block(history)}\n\n"
        + f"CURRENT MESSAGE FROM {name}:\n{question}\n\n"
        + closing
    )
    return system, user_prompt


def build_interview_kickoff_prompt(
    bundle: dict,
    *,
    app: "Application | None",
    stories: list[dict],
    user: dict | None = None,
) -> tuple[str, str]:
    """Opening turn of a mock interview: a short greeting + the FIRST question
    only (there is no answer to critique yet)."""
    master = bundle.get("master") or {}
    name = _first_name(master, user)
    role_line = (
        f" for the {app.title} role at {app.company}" if app is not None else ""
    )
    system = (
        f"You are Coach, an interviewer running a mock interview{role_line} with "
        f"{name}.\n\n"
        + _grounding_rule()
        + _voice_rule(name)
        + "Open with one short sentence framing the interview, then ask exactly "
        "ONE opening question and stop. Do not answer it yourself. When a role "
        "or JD is provided, tailor the question to it; otherwise ask a strong "
        "general behavioral opener."
    )
    user_prompt = (
        _profile_context(bundle, name, stories)
        + _grounding_block(app)
        + "Begin the interview now with a one-line intro and your first "
        "question."
    )
    return system, user_prompt


def build_essay_prompt(
    bundle: dict,
    *,
    prompt: str,
    word_limit: int | None = None,
    instructions: str = "",
    app: "Application | None",
    stories: list[dict],
    user: dict | None = None,
) -> tuple[str, str]:
    """Draft a grounded answer to an ad-hoc essay / short-answer prompt
    (scholarship, application question) in the candidate's voice."""
    master = bundle.get("master") or {}
    name = _first_name(master, user)
    length_rule = (
        f"Keep it within about {word_limit} words. "
        if word_limit and word_limit > 0 else ""
    )
    system = (
        f"You are Coach, drafting an application answer for {name} in their own "
        f"first-person voice.\n\n"
        + _grounding_rule()
        + _voice_rule(name)
        + "Answer the prompt directly and specifically, anchored in one real "
        "story where it helps. " + length_rule + "Plain prose, no bullet lists "
        "unless the prompt asks for them, no headers, no sign-off. Output ONLY "
        "the answer text."
    )
    user_prompt = (
        _profile_context(bundle, name, stories)
        + _grounding_block(app)
        + (f"EXTRA INSTRUCTIONS: {instructions}\n\n" if instructions else "")
        + f"PROMPT TO ANSWER:\n{prompt}\n\n"
        + (f"Target length: about {word_limit} words.\n" if word_limit and word_limit > 0 else "")
        + "Write the answer now. Stay grounded in the material above; never "
        "claim experience the candidate doesn't have. No em dashes."
    )
    return system, user_prompt
