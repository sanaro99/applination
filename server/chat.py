"""Coach conversational assistant.

A send-and-wait chat grounded in the candidate's real profile. Sessions and
messages are persisted; a session can optionally be grounded to an Application
(so the candidate can prep for one specific job). Good replies can be saved to
a reusable answer bank and attached to an Application's answers.md.

No streaming: every provider exposes only text_call/json_call, so the POST
simply returns the full assistant reply.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import select

from .auth import require_owner, require_user
from .db import (
    Application,
    ChatMessage,
    ChatSession,
    SavedAnswer,
    User,
    session,
)
from .deps import load_config
from .limits import LLM_LIMIT, limiter
from .scoping import find_owned, get_owned, owned

router = APIRouter(prefix="/api/chat", tags=["chat"])
log = logging.getLogger("server.chat")


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class SessionCreate(BaseModel):
    title: str | None = None
    application_id: int | None = None
    mode: str = "chat"  # "chat" | "interview"


class SessionUpdate(BaseModel):
    # Both optional; `application_id` may be explicitly set to null to clear
    # grounding. We use model_fields_set to tell "omitted" from "set to null".
    title: str | None = None
    application_id: int | None = None


class SessionOut(BaseModel):
    id: int
    title: str
    mode: str = "chat"
    application_id: int | None = None
    application_label: str | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class SessionDetailOut(BaseModel):
    session: SessionOut
    messages: list[MessageOut]


class PostMessageBody(BaseModel):
    content: str


class PostMessageOut(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut


class SaveAnswerBody(BaseModel):
    content: str
    title: str | None = None
    prompt: str | None = None
    tags: list[str] = []
    source_message_id: int | None = None
    application_id: int | None = None


class SavedAnswerOut(BaseModel):
    id: int
    title: str
    prompt: str
    content: str
    tags: list[str]
    application_id: int | None = None
    created_at: datetime


class AttachAnswerBody(BaseModel):
    application_id: int


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _app_label(app: Application | None) -> str | None:
    if app is None:
        return None
    return f"{app.company} — {app.title}".strip(" —")


def _session_out(s, sess: ChatSession, user: User | int) -> SessionOut:
    count = len(
        s.exec(
            owned(
                select(ChatMessage.id).where(
                    ChatMessage.session_id == sess.id
                ),
                ChatMessage,
                user,
            )
        ).all()
    )
    # find_owned, not s.get: a session grounded to another user's application
    # would otherwise leak that application's company and title through the
    # label. It renders as ungrounded instead.
    app = (
        find_owned(s, Application, sess.application_id, user)
        if sess.application_id
        else None
    )
    return SessionOut(
        id=sess.id,
        title=sess.title,
        mode=sess.mode,
        application_id=sess.application_id,
        application_label=_app_label(app),
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        message_count=count,
    )


def _saved_out(ans: SavedAnswer) -> SavedAnswerOut:
    tags = [t.strip() for t in (ans.tags or "").split(",") if t.strip()]
    return SavedAnswerOut(
        id=ans.id,
        title=ans.title,
        prompt=ans.prompt,
        content=ans.content,
        tags=tags,
        application_id=ans.application_id,
        created_at=ans.created_at,
    )


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
@router.post("/sessions", response_model=SessionOut)
def create_session(
    body: SessionCreate, user: User = Depends(require_user)
) -> SessionOut:
    with session() as s:
        if body.application_id is not None:
            # Re-verify the parent: without this a session could be created
            # under the caller's own user_id while pointing at someone else's
            # application, which reads as consistent and still leaks.
            get_owned(
                s, Application, body.application_id, user,
                detail="application not found",
            )
        mode = body.mode if body.mode in ("chat", "interview") else "chat"
        default_title = _DEFAULT_TITLES[mode]
        sess = ChatSession(
            user_id=user.id,
            title=(body.title or default_title).strip() or default_title,
            application_id=body.application_id,
            mode=mode,
        )
        s.add(sess)
        s.commit()
        s.refresh(sess)
        return _session_out(s, sess, user)


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    mode: str | None = None, user: User = Depends(require_user)
) -> list[SessionOut]:
    with session() as s:
        stmt = owned(select(ChatSession), ChatSession, user).order_by(
            ChatSession.updated_at.desc()
        )
        if mode is not None:
            stmt = stmt.where(ChatSession.mode == mode)
        return [_session_out(s, sess, user) for sess in s.exec(stmt).all()]


@router.get("/sessions/{sid}", response_model=SessionDetailOut)
def get_session(
    sid: int, user: User = Depends(require_user)
) -> SessionDetailOut:
    with session() as s:
        sess = get_owned(s, ChatSession, sid, user, detail="session not found")
        msgs = s.exec(
            owned(
                select(ChatMessage).where(ChatMessage.session_id == sid),
                ChatMessage,
                user,
            ).order_by(ChatMessage.created_at)
        ).all()
        return SessionDetailOut(
            session=_session_out(s, sess, user),
            messages=[
                MessageOut(id=m.id, role=m.role, content=m.content,
                           created_at=m.created_at)
                for m in msgs
            ],
        )


@router.patch("/sessions/{sid}", response_model=SessionOut)
def update_session(
    sid: int, body: SessionUpdate, user: User = Depends(require_user)
) -> SessionOut:
    fields = body.model_fields_set
    if not fields:
        raise HTTPException(400, "nothing to update")
    with session() as s:
        sess = get_owned(s, ChatSession, sid, user, detail="session not found")
        if "title" in fields:
            title = (body.title or "").strip()
            if not title:
                raise HTTPException(400, "title cannot be empty")
            sess.title = title[:120]
        if "application_id" in fields:
            # Explicit null clears grounding; a value re-grounds the chat.
            if body.application_id is not None:
                get_owned(
                    s, Application, body.application_id, user,
                    detail="application not found",
                )
            sess.application_id = body.application_id
        sess.updated_at = datetime.utcnow()
        s.add(sess)
        s.commit()
        s.refresh(sess)
        return _session_out(s, sess, user)


@router.delete("/sessions/{sid}")
def delete_session(sid: int, user: User = Depends(require_user)) -> dict:
    with session() as s:
        sess = get_owned(s, ChatSession, sid, user, detail="session not found")
        msgs = s.exec(
            owned(
                select(ChatMessage).where(ChatMessage.session_id == sid),
                ChatMessage,
                user,
            )
        ).all()
        for m in msgs:
            s.delete(m)
        s.delete(sess)
        s.commit()
    return {"ok": True}


_DEFAULT_TITLES = {"chat": "New chat", "interview": "New interview"}


def _run_chain(sys_prompt: str, user_prompt: str, *, task: str) -> str:
    """Call the per-task provider chain and return a non-empty reply.

    Shared by the chat, interview-kickoff, and essay flows. ``task`` selects
    the configured chain (llm.tasks.<task>); falls back to the global chain if
    the task is unconfigured. Raises HTTPException(502) on failure.
    """
    from src.providers import get_provider_chain, get_task_chains, try_chain

    cfg = load_config()
    try:
        chain = get_task_chains(cfg["llm"]).get(task)
    except Exception:  # noqa: BLE001 — bad task config shouldn't 500 the chat
        chain = None
    if not chain:
        chain = get_provider_chain(cfg["llm"])
    if not chain:
        raise HTTPException(502, "no LLM provider is configured")
    try:
        reply = try_chain(
            chain,
            lambda p: p.text_call(sys_prompt, user_prompt, max_tokens=1200),
            any_error=True,
            task_name=task,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("%s reply failed: %s", task, e)
        raise HTTPException(502, f"assistant unavailable: {e}") from e
    reply = (reply or "").strip()
    if not reply:
        raise HTTPException(502, "assistant returned an empty reply")
    return reply


# --------------------------------------------------------------------------- #
# Core: post a message, get an assistant reply
# --------------------------------------------------------------------------- #
@router.post("/sessions/{sid}/messages", response_model=PostMessageOut)
@limiter.limit(LLM_LIMIT)
def post_message(
    request: Request,
    sid: int,
    body: PostMessageBody,
    # Owner-only until PR 3: the reply is grounded in the one global
    # master_data/ profile and paid for with the global provider keys.
    user: User = Depends(require_owner),
) -> PostMessageOut:
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "message is required")

    # 1. Load context + persist the user message (short DB session).
    with session() as s:
        sess = get_owned(s, ChatSession, sid, user, detail="session not found")
        app = (
            find_owned(s, Application, sess.application_id, user)
            if sess.application_id else None
        )
        history = s.exec(
            owned(
                select(ChatMessage).where(ChatMessage.session_id == sid),
                ChatMessage,
                user,
            ).order_by(ChatMessage.created_at)
        ).all()
        # Detach the data we need before the session closes.
        app_data = (
            _AppView(app.company, app.title, app.location, app.description)
            if app else None
        )
        history_view = [_MsgView(m.role, m.content) for m in history]
        mode = sess.mode
        is_first = sess.title in _DEFAULT_TITLES.values() and not history

        user_msg = ChatMessage(
            session_id=sid, user_id=user.id, role="user", content=content
        )
        s.add(user_msg)
        s.commit()
        s.refresh(user_msg)
        user_msg_out = MessageOut(
            id=user_msg.id, role=user_msg.role, content=user_msg.content,
            created_at=user_msg.created_at,
        )

    # 2. Assemble context + call the provider chain (no DB session held).
    from .coach_context import (
        build_coach_prompt,
        load_profile_bundle,
        pick_stories,
    )

    cfg = load_config()
    bundle = load_profile_bundle()
    stories = pick_stories(bundle, question=content, app=app_data)
    sys_prompt, user_prompt = build_coach_prompt(
        bundle,
        question=content,
        history=history_view,
        app=app_data,
        stories=stories,
        user=cfg.get("user"),
        mode=mode,
    )
    reply = _run_chain(sys_prompt, user_prompt, task=mode if mode == "interview" else "coach")

    story_titles = [s.get("title", "") for s in stories]
    meta = json.dumps({"stories": story_titles})

    # 3. Persist the assistant message + bump session (short DB session).
    with session() as s:
        asst_msg = ChatMessage(
            session_id=sid, user_id=user.id, role="assistant",
            content=reply, meta=meta,
        )
        s.add(asst_msg)
        sess = find_owned(s, ChatSession, sid, user)
        if sess is not None:
            sess.updated_at = datetime.utcnow()
            # Auto-title chats from the first question; interview titles stay
            # the default until renamed (the first user turn is an answer).
            if is_first and mode == "chat":
                sess.title = content[:60]
            s.add(sess)
        s.commit()
        s.refresh(asst_msg)
        asst_msg_out = MessageOut(
            id=asst_msg.id, role=asst_msg.role, content=asst_msg.content,
            created_at=asst_msg.created_at,
        )

    return PostMessageOut(
        user_message=user_msg_out, assistant_message=asst_msg_out
    )


# Lightweight detached views so coach_context never touches a live DB session.
class _AppView:
    def __init__(self, company: str, title: str, location: str, description: str):
        self.company = company
        self.title = title
        self.location = location
        self.description = description


class _MsgView:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


# --------------------------------------------------------------------------- #
# Mock interview kickoff (first question, no preceding answer)
# --------------------------------------------------------------------------- #
@router.post("/sessions/{sid}/kickoff", response_model=MessageOut)
@limiter.limit(LLM_LIMIT)
def kickoff(
    request: Request,
    sid: int,
    user: User = Depends(require_owner),  # owner-only: see post_message
) -> MessageOut:
    """Generate the opening interviewer question for an interview session that
    has no messages yet. Idempotent: 400 if the session already has messages."""
    with session() as s:
        sess = get_owned(s, ChatSession, sid, user, detail="session not found")
        if sess.mode != "interview":
            raise HTTPException(400, "kickoff is only for interview sessions")
        existing = s.exec(
            owned(
                select(ChatMessage.id).where(ChatMessage.session_id == sid),
                ChatMessage,
                user,
            )
        ).first()
        if existing is not None:
            raise HTTPException(400, "interview already started")
        app = (
            find_owned(s, Application, sess.application_id, user)
            if sess.application_id else None
        )
        app_data = (
            _AppView(app.company, app.title, app.location, app.description)
            if app else None
        )

    from .coach_context import (
        build_interview_kickoff_prompt,
        load_profile_bundle,
        pick_stories,
    )

    cfg = load_config()
    bundle = load_profile_bundle()
    stories = pick_stories(
        bundle, question=(app_data.title if app_data else "interview"),
        app=app_data,
    )
    sys_prompt, user_prompt = build_interview_kickoff_prompt(
        bundle, app=app_data, stories=stories, user=cfg.get("user"),
    )
    reply = _run_chain(sys_prompt, user_prompt, task="interview")

    with session() as s:
        msg = ChatMessage(
            session_id=sid, user_id=user.id, role="assistant", content=reply
        )
        s.add(msg)
        sess = find_owned(s, ChatSession, sid, user)
        if sess is not None:
            sess.updated_at = datetime.utcnow()
            s.add(sess)
        s.commit()
        s.refresh(msg)
        return MessageOut(
            id=msg.id, role=msg.role, content=msg.content,
            created_at=msg.created_at,
        )


# --------------------------------------------------------------------------- #
# Essay / short-answer drafter (one-shot, not persisted as a session)
# --------------------------------------------------------------------------- #
class EssayBody(BaseModel):
    prompt: str
    word_limit: int | None = None
    application_id: int | None = None
    instructions: str = ""


@router.post("/essay")
@limiter.limit(LLM_LIMIT)
def draft_essay(
    request: Request,
    body: EssayBody,
    user: User = Depends(require_owner),  # owner-only: see post_message
) -> dict:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")

    app_data = None
    if body.application_id is not None:
        with session() as s:
            app = get_owned(
                s, Application, body.application_id, user,
                detail="application not found",
            )
            app_data = _AppView(
                app.company, app.title, app.location, app.description
            )

    from .coach_context import (
        build_essay_prompt,
        load_profile_bundle,
        pick_stories,
    )

    cfg = load_config()
    bundle = load_profile_bundle()
    stories = pick_stories(bundle, question=prompt, app=app_data)
    sys_prompt, user_prompt = build_essay_prompt(
        bundle,
        prompt=prompt,
        word_limit=body.word_limit,
        instructions=body.instructions.strip(),
        app=app_data,
        stories=stories,
        user=cfg.get("user"),
    )
    content = _run_chain(sys_prompt, user_prompt, task="essay")
    return {"content": content}


# --------------------------------------------------------------------------- #
# Answer bank
# --------------------------------------------------------------------------- #
@router.post("/answers", response_model=SavedAnswerOut)
def save_answer(
    body: SaveAnswerBody, user: User = Depends(require_user)
) -> SavedAnswerOut:
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "content is required")
    with session() as s:
        if body.application_id is not None:
            get_owned(
                s, Application, body.application_id, user,
                detail="application not found",
            )
        if body.source_message_id is not None:
            # The bank stores the message it came from; without this check a
            # saved answer could cite another user's chat message by id.
            get_owned(
                s, ChatMessage, body.source_message_id, user,
                detail="message not found",
            )
        ans = SavedAnswer(
            user_id=user.id,
            title=(body.title or "").strip()[:120],
            prompt=(body.prompt or "").strip(),
            content=content,
            tags=",".join(t.strip() for t in body.tags if t.strip()),
            source_message_id=body.source_message_id,
            application_id=body.application_id,
        )
        s.add(ans)
        s.commit()
        s.refresh(ans)
        return _saved_out(ans)


@router.get("/answers", response_model=list[SavedAnswerOut])
def list_answers(
    application_id: int | None = None, user: User = Depends(require_user)
) -> list[SavedAnswerOut]:
    with session() as s:
        stmt = owned(select(SavedAnswer), SavedAnswer, user).order_by(
            SavedAnswer.created_at.desc()
        )
        if application_id is not None:
            stmt = stmt.where(SavedAnswer.application_id == application_id)
        return [_saved_out(a) for a in s.exec(stmt).all()]


@router.delete("/answers/{aid}")
def delete_answer(aid: int, user: User = Depends(require_user)) -> dict:
    with session() as s:
        ans = get_owned(
            s, SavedAnswer, aid, user, detail="saved answer not found"
        )
        s.delete(ans)
        s.commit()
    return {"ok": True}


@router.post("/answers/{aid}/attach")
def attach_answer(
    aid: int, body: AttachAnswerBody, user: User = Depends(require_user)
) -> dict:
    """Append a saved answer to an Application's answers.md (reuses the
    pipeline's answers convention) and link it to that application."""
    with session() as s:
        ans = get_owned(
            s, SavedAnswer, aid, user, detail="saved answer not found"
        )
        # This writes to the application's folder on disk, so an unscoped
        # lookup here would let one user append text into another's answers.md.
        app = get_owned(
            s, Application, body.application_id, user,
            detail="application not found",
        )
        folder = Path(app.folder_path)
        if not folder.exists():
            raise HTTPException(404, f"application folder missing: {folder}")

        path = folder / "answers.md"
        heading = ans.prompt or ans.title or "Saved answer"
        block = f"## {heading}\n\n{ans.content}\n"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(
            (existing.rstrip() + "\n\n" + block) if existing.strip() else block,
            encoding="utf-8",
        )

        ans.application_id = app.id
        if not app.answers_file:
            # Match the output-root-relative style used by the pipeline.
            try:
                app.answers_file = str(path.relative_to(folder.parent.parent))
            except ValueError:
                app.answers_file = str(path)
        s.add(ans)
        s.add(app)
        s.commit()
        answers_file = app.answers_file
    return {"ok": True, "answers_file": answers_file}
