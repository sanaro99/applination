"""Ops & insight endpoints: provider connectivity tests + run comparison."""
from __future__ import annotations
import logging
import re
import time

import requests

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from .auth import require_user
from .db import Application, Run, User, session
from .deps import load_config, update_llm_config
from .limits import LLM_LIMIT, limiter
from .scoping import get_owned, owned

router = APIRouter(prefix="/api", tags=["ops"])
log = logging.getLogger("server.ops")

# Provider names the factory knows how to build (mirrors src/tweak.py choices).
KNOWN_PROVIDERS = [
    "openrouter", "openai", "nim", "groq", "cloudflare", "gemini", "ollama", "claude", "deepseek", "mistral",
]
# Providers that don't need an api_key (local / self-hosted).
LOCAL_PROVIDERS = {"ollama"}


class ProviderInfo(BaseModel):
    name: str
    model: str
    configured: bool
    role: str  # "primary" | "fallback" | "available"
    account_id: str = ""


@router.get("/providers", response_model=list[ProviderInfo])
def list_providers(
    user: User = Depends(require_user),
) -> list[ProviderInfo]:
    # Reports which of *this* user's provider keys are set. load_config has
    # already merged their decrypted UserSecret rows in, so a key stored
    # encrypted reads as configured here without ever being returned.
    llm = load_config(user).get("llm", {}) or {}
    primary = llm.get("primary")
    fallbacks = llm.get("fallbacks", []) or []
    out: list[ProviderInfo] = []
    for name in KNOWN_PROVIDERS:
        block = llm.get(name)
        if not isinstance(block, dict):
            continue
        has_key = bool(block.get("api_token" if name == "cloudflare" else "api_key"))
        configured = has_key or name in LOCAL_PROVIDERS
        role = (
            "primary" if name == primary
            else "fallback" if name in fallbacks
            else "available"
        )
        out.append(ProviderInfo(
            name=name,
            model=str(block.get("model", "")),
            configured=configured,
            role=role,
            account_id=str(block.get("account_id", "")) if name == "cloudflare" else "",
        ))
    # primary first, then fallbacks in order, then the rest
    order = {"primary": 0, "fallback": 1, "available": 2}
    out.sort(key=lambda p: (order[p.role], p.name))
    return out


class ProviderConfigurationBody(BaseModel):
    model: str
    api_key: str | None = None
    account_id: str | None = None


class ProviderModelsBody(BaseModel):
    api_key: str | None = None
    account_id: str | None = None


def _account_id(value: str) -> str:
    account_id = value.strip()
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account_id):
        raise HTTPException(400, "Cloudflare account ID must be 32 hexadecimal characters")
    return account_id


@router.put("/providers/{name}/configuration")
def put_provider_configuration(
    name: str, body: ProviderConfigurationBody, user: User = Depends(require_user)
) -> dict:
    name = _validate_provider(name)
    model = body.model.strip()
    if not model or len(model) > 200 or any(ch.isspace() or ord(ch) < 32 for ch in model):
        raise HTTPException(400, "model must be a single model ID of at most 200 characters")
    if body.api_key is not None and len(body.api_key) > 4096:
        raise HTTPException(400, "API key is too long")
    if name == "ollama" and body.api_key:
        raise HTTPException(400, "Ollama does not use an API key")
    if body.account_id is not None and name != "cloudflare":
        raise HTTPException(400, "account ID is only used by Cloudflare")
    account_id = _account_id(body.account_id) if body.account_id is not None else None

    def _mutate(llm: dict) -> None:
        block = llm.get(name)
        if not isinstance(block, dict):
            block = {}
            llm[name] = block
        block["model"] = model
        if body.api_key and body.api_key.strip():
            block["api_token" if name == "cloudflare" else "api_key"] = body.api_key.strip()
        if account_id is not None:
            block["account_id"] = account_id

    # update_llm_config moves a submitted key to encrypted UserSecret storage.
    # An omitted/blank key leaves the currently stored credential in place.
    update_llm_config(user, _mutate)
    return {"ok": True}


@router.post("/providers/{name}/models")
@limiter.limit(LLM_LIMIT)
def list_provider_models(
    request: Request, name: str, body: ProviderModelsBody,
    user: User = Depends(require_user),
) -> dict:
    name = _validate_provider(name)
    block = (load_config(user).get("llm") or {}).get(name) or {}
    key = (body.api_key or "").strip() or str(
        block.get("api_token" if name == "cloudflare" else "api_key") or ""
    ).strip()
    if not key and name != "ollama":
        raise HTTPException(400, "Enter an API key to load this provider's models")
    if len(key) > 4096 or any(ord(ch) < 32 for ch in key):
        raise HTTPException(400, "Invalid API key")
    account_id = (body.account_id or block.get("account_id") or "") if name == "cloudflare" else ""
    if name == "cloudflare":
        account_id = _account_id(account_id)

    from .provider_models import discover_models
    try:
        return {"models": discover_models(
            name, key, account_id=account_id,
            base_url=str(block.get("base_url") or "") if name == "ollama" else "",
        )}
    except (requests.RequestException, ValueError) as exc:
        # Do not send upstream error bodies back: vendors may echo credentials.
        log.warning("model discovery failed for %s: %s", name, type(exc).__name__)
        status = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else None
        detail = f"Could not load {name} models" + (f" (HTTP {status})" if status else "")
        raise HTTPException(502, detail) from exc


class TestBody(BaseModel):
    provider: str


class TestResult(BaseModel):
    ok: bool
    provider: str
    model: str = ""
    latency_ms: int = 0
    sample: str = ""
    error: str = ""


@router.post("/providers/test", response_model=TestResult)
@limiter.limit(LLM_LIMIT)
def test_provider(
    request: Request,
    body: TestBody,
    # Rate limited: makes a real (small) call on this user's own key.
    user: User = Depends(require_user),
) -> TestResult:
    name = body.provider.strip().lower()
    if name not in KNOWN_PROVIDERS:
        raise HTTPException(400, f"unknown provider: {name}")

    llm = load_config(user).get("llm", {}) or {}
    model = str((llm.get(name) or {}).get("model", ""))

    from src.providers import get_provider

    try:
        provider = get_provider(name, llm)
    except Exception as e:
        return TestResult(ok=False, provider=name, model=model,
                          error=f"could not build provider: {e}")

    t0 = time.time()
    try:
        sample = provider.text_call(
            "You are a connectivity check.",
            "Reply with the single word: ok",
            max_tokens=5,
        )
        latency = int((time.time() - t0) * 1000)
        return TestResult(
            ok=True, provider=name, model=model,
            latency_ms=latency, sample=(sample or "").strip()[:80],
        )
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        return TestResult(ok=False, provider=name, model=model,
                          latency_ms=latency, error=str(e)[:300])


# --------------------------------------------------------------------------- #
# Per-workflow LLM routing (structured editor for config.llm)
# --------------------------------------------------------------------------- #
class TaskRouting(BaseModel):
    primary: str | None = None
    fallbacks: list[str] = []
    models: dict[str, str] = {}
    thinking: str | bool | None = None


class LlmGlobal(BaseModel):
    primary: str | None = None
    fallbacks: list[str] = []


class LlmConfigOut(BaseModel):
    # `global` is a Python keyword, so the field is `global_` aliased over the wire.
    model_config = ConfigDict(populate_by_name=True)
    task_names: list[str]
    global_: LlmGlobal = Field(default_factory=LlmGlobal, alias="global")
    providers: list[ProviderInfo]
    tasks: dict[str, TaskRouting]


class LlmConfigIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    global_: LlmGlobal = Field(default_factory=LlmGlobal, alias="global")
    tasks: dict[str, TaskRouting] = {}


def _task_names() -> list[str]:
    from src.providers.factory import _TASK_NAMES
    return list(_TASK_NAMES)


def _validate_provider(name: str) -> str:
    n = name.strip().lower()
    if n not in KNOWN_PROVIDERS:
        raise HTTPException(400, f"unknown provider: {name}")
    return n


@router.get("/llm-config", response_model=LlmConfigOut, response_model_by_alias=True)
def get_llm_config(user: User = Depends(require_user)) -> LlmConfigOut:
    llm = load_config(user).get("llm", {}) or {}
    tasks_cfg = llm.get("tasks", {}) or {}
    tasks: dict[str, TaskRouting] = {}
    for name, block in tasks_cfg.items():
        block = block or {}
        tasks[name] = TaskRouting(
            primary=block.get("primary"),
            fallbacks=list(block.get("fallbacks", []) or []),
            models=dict(block.get("models", {}) or {}),
            thinking=block.get("thinking"),
        )
    return LlmConfigOut(
        task_names=_task_names(),
        global_=LlmGlobal(
            primary=llm.get("primary"),
            fallbacks=list(llm.get("fallbacks", []) or []),
        ),
        # Called directly, not through FastAPI, so the user has to be passed
        # explicitly — the Depends() default is just an object here.
        providers=list_providers(user),
        tasks=tasks,
    )


@router.put("/llm-config")
def put_llm_config(
    body: LlmConfigIn, user: User = Depends(require_user)
) -> dict:
    valid_tasks = set(_task_names())
    # Validate before touching the file.
    if body.global_.primary:
        _validate_provider(body.global_.primary)
    for p in body.global_.fallbacks:
        _validate_provider(p)
    for tname, routing in body.tasks.items():
        if tname not in valid_tasks:
            raise HTTPException(400, f"unknown task: {tname}")
        if routing.primary:
            _validate_provider(routing.primary)
        for p in routing.fallbacks:
            _validate_provider(p)
        for p in routing.models:
            _validate_provider(p)
        if routing.thinking not in (None, True, False, "off", "low", "on"):
            raise HTTPException(400, f"invalid thinking mode for task: {tname}")

    def _mutate(llm: dict) -> None:
        if body.global_.primary:
            llm["primary"] = body.global_.primary
        llm["fallbacks"] = [p.strip().lower() for p in body.global_.fallbacks]
        # Replace the whole tasks map: omitted tasks inherit the global chain.
        new_tasks: dict[str, dict] = {}
        for tname, routing in body.tasks.items():
            entry: dict = {}
            if routing.primary:
                entry["primary"] = routing.primary
            if routing.fallbacks:
                entry["fallbacks"] = [p.strip().lower() for p in routing.fallbacks]
            if routing.models:
                entry["models"] = {k: v for k, v in routing.models.items() if v}
            if routing.thinking is not None:
                entry["thinking"] = routing.thinking
            if entry:
                new_tasks[tname] = entry
        if new_tasks:
            llm["tasks"] = new_tasks
        elif "tasks" in llm:
            del llm["tasks"]

    update_llm_config(user, _mutate)
    return {"ok": True}


class RunSummary(BaseModel):
    id: int
    status: str
    started_at: str | None
    duration_s: float | None
    jobs_found: int
    applications_created: int
    avg_score: float
    by_status: dict[str, int]
    companies: list[str]


class CompareOut(BaseModel):
    a: RunSummary
    b: RunSummary
    shared_companies: list[str]
    only_a: list[str]
    only_b: list[str]


def _summarize(run: Run, apps: list[Application]) -> RunSummary:
    duration = None
    if run.finished_at and run.started_at:
        duration = round((run.finished_at - run.started_at).total_seconds(), 1)
    scores = [a.match_score for a in apps]
    by_status: dict[str, int] = {}
    for a in apps:
        key = a.status.value if hasattr(a.status, "value") else str(a.status)
        by_status[key] = by_status.get(key, 0) + 1
    return RunSummary(
        id=run.id,  # type: ignore[arg-type]
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        started_at=run.started_at.isoformat() if run.started_at else None,
        duration_s=duration,
        jobs_found=run.jobs_found,
        applications_created=run.applications_created,
        avg_score=round(sum(scores) / len(scores), 1) if scores else 0.0,
        by_status=by_status,
        companies=sorted({a.company for a in apps if a.company}),
    )


@router.get("/compare", response_model=CompareOut)
def compare_runs(
    a: int, b: int, user: User = Depends(require_user)
) -> CompareOut:
    with session() as s:
        ra = get_owned(s, Run, a, user, detail="one or both runs not found")
        rb = get_owned(s, Run, b, user, detail="one or both runs not found")
        apps_a = s.exec(
            owned(
                select(Application).where(Application.run_id == a),
                Application,
                user,
            )
        ).all()
        apps_b = s.exec(
            owned(
                select(Application).where(Application.run_id == b),
                Application,
                user,
            )
        ).all()

    sa, sb = _summarize(ra, apps_a), _summarize(rb, apps_b)
    set_a, set_b = set(sa.companies), set(sb.companies)
    return CompareOut(
        a=sa, b=sb,
        shared_companies=sorted(set_a & set_b),
        only_a=sorted(set_a - set_b),
        only_b=sorted(set_b - set_a),
    )
