"""Small, explicit model-evaluation harness for application-tailoring prompts.

This module deliberately does not participate in normal application routing.
The Gemini and Groq Batch APIs are asynchronous, while the pipeline needs an
answer immediately. Keeping batch evaluation here prevents a configuration
choice from silently changing that contract.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import time
from typing import Any, Iterable

from .providers import get_provider
from .providers.base import resolve_api_key

MAX_CASES = 30

EVALUATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fit_summary": {"type": "string"},
        "matched_evidence": {"type": "array", "items": {"type": "string"}},
        "missing_or_risky_requirements": {"type": "array", "items": {"type": "string"}},
        "tailoring_actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "fit_summary", "matched_evidence", "missing_or_risky_requirements", "tailoring_actions",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You evaluate a candidate against a job posting for an application.
Only use evidence in the supplied candidate profile. Do not invent experience,
metrics, employers, skills, or credentials. Give concrete, useful tailoring
advice in the requested JSON shape."""


@dataclass(frozen=True)
class EvaluationCandidate:
    """One stable model target; ``mode`` is never a workflow provider name."""

    slug: str
    label: str
    provider: str
    model: str
    mode: str = "sync"


CURATED_CANDIDATES: dict[str, EvaluationCandidate] = {
    "luna": EvaluationCandidate("luna", "GPT-5.6 Luna", "openai", "gpt-5.6-luna"),
    "gemini": EvaluationCandidate("gemini", "Gemini 3.8 Flash", "gemini", "gemini-3.8-flash"),
    "gemini-batch": EvaluationCandidate(
        "gemini-batch", "Gemini 3.8 Flash Batch", "gemini", "gemini-3.8-flash", "batch",
    ),
    "gpt-oss": EvaluationCandidate(
        "gpt-oss", "GPT-OSS 120B on Groq", "groq", "openai/gpt-oss-120b",
    ),
    "gpt-oss-batch": EvaluationCandidate(
        "gpt-oss-batch", "GPT-OSS 120B Groq Batch", "groq", "openai/gpt-oss-120b", "batch",
    ),
}


@dataclass(frozen=True)
class EvaluationCase:
    """A private, candidate-owned comparison prompt loaded from a JSON file."""

    case_id: str
    candidate_profile: str
    job: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any], position: int) -> "EvaluationCase":
        case_id = str(value.get("id") or f"case-{position}").strip()
        profile = str(value.get("candidate_profile") or "").strip()
        job = value.get("job")
        if not case_id or not profile or not isinstance(job, dict):
            raise ValueError(
                "Each case needs an id, candidate_profile, and a job object. "
                "Keep the file private because it may contain personal information."
            )
        return cls(case_id=case_id, candidate_profile=profile, job=job)


def load_cases(path: str, *, limit: int = 20) -> list[EvaluationCase]:
    """Load an intentionally bounded private JSON file of comparison cases."""
    if not 1 <= limit <= MAX_CASES:
        raise ValueError(f"limit must be between 1 and {MAX_CASES}")
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list):
        raise ValueError("evaluation cases file must be a JSON array")
    cases = [EvaluationCase.from_dict(item, index + 1) for index, item in enumerate(raw[:limit]) if isinstance(item, dict)]
    if not cases:
        raise ValueError("evaluation cases file has no usable cases")
    return cases


def prompt_for(case: EvaluationCase) -> str:
    """Produce the identical compatibility/evaluation prompt for every model."""
    job = case.job
    return (
        f"CANDIDATE PROFILE:\n{case.candidate_profile}\n\n"
        "JOB POSTING:\n"
        f"Company: {job.get('company', '')}\n"
        f"Title: {job.get('title', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Description: {job.get('description', job.get('desc', ''))}\n"
    )


def _record(case: EvaluationCase, candidate: EvaluationCandidate, *, output: dict | None = None,
            error: str = "", latency_ms: int = 0) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "candidate": asdict(candidate),
        "ok": not error,
        "latency_ms": latency_ms,
        "output": output,
        "error": error[:500],
    }


def run_sync_evaluation(
    llm_cfg: dict[str, Any], candidate: EvaluationCandidate, cases: Iterable[EvaluationCase],
) -> list[dict[str, Any]]:
    """Run one structured, application-relevant prompt per case synchronously."""
    if candidate.mode != "sync":
        raise ValueError("Batch candidates must be submitted through their batch evaluator")
    provider = get_provider(
        candidate.provider, llm_cfg, model_override=candidate.model, thinking="low",
    )
    records: list[dict[str, Any]] = []
    for case in cases:
        started = time.monotonic()
        try:
            output = provider.json_call(
                SYSTEM_PROMPT, prompt_for(case), max_tokens=900, schema=EVALUATION_SCHEMA,
            )
            records.append(_record(
                case, candidate, output=output,
                latency_ms=int((time.monotonic() - started) * 1000),
            ))
        except Exception as exc:
            records.append(_record(
                case, candidate, error=str(exc),
                latency_ms=int((time.monotonic() - started) * 1000),
            ))
    return records


def batch_state_name(job: Any) -> str:
    """Normalize enum/string state values across supported google-genai releases."""
    state = getattr(job, "state", "")
    return str(getattr(state, "name", state) or "")


class GeminiBatchEvaluator:
    """Submit and collect a bounded inline Gemini evaluation batch.

    It only uses the Gemini Developer API's inline-request mode. That is the
    right fit for a 20–30 case comparison and avoids uploading a personal resume
    to a temporary vendor file. The caller is responsible for polling later.
    """

    def __init__(self, api_key: str, model: str = "gemini-3.8-flash", *, client: Any = None):
        if client is None:
            try:
                from google import genai
            except ImportError as exc:  # pragma: no cover
                raise ImportError("pip install google-genai") from exc
            key = resolve_api_key(
                api_key, "GOOGLE_API_KEY", "GEMINI_API_KEY", provider="Gemini",
                config_key="llm.gemini.api_key",
            )
            client = genai.Client(api_key=key)
        self.client = client
        self.model = model

    def submit(self, cases: list[EvaluationCase], *, display_name: str) -> dict[str, str]:
        if not 1 <= len(cases) <= MAX_CASES:
            raise ValueError(f"Gemini Batch needs between 1 and {MAX_CASES} cases")
        requests = [
            {
                "contents": [{"role": "user", "parts": [{"text": prompt_for(case)}]}],
                "config": {
                    "system_instruction": SYSTEM_PROMPT,
                    "max_output_tokens": 900,
                    "response_mime_type": "application/json",
                    "response_schema": EVALUATION_SCHEMA,
                },
                "metadata": {"case_id": case.case_id},
            }
            for case in cases
        ]
        job = self.client.batches.create(
            model=self.model,
            src=requests,
            config={"display_name": display_name},
        )
        return {"name": str(job.name), "state": batch_state_name(job)}

    def collect(self, name: str) -> dict[str, Any]:
        """Return status plus inline text/error results when the job is done."""
        job = self.client.batches.get(name=name)
        result: dict[str, Any] = {"name": str(job.name), "state": batch_state_name(job), "results": []}
        destination = getattr(job, "dest", None)
        for inline in getattr(destination, "inlined_responses", None) or []:
            metadata = getattr(inline, "metadata", None) or {}
            response = getattr(inline, "response", None)
            error = getattr(inline, "error", None)
            text = ""
            if response and getattr(response, "candidates", None):
                parts = getattr(response.candidates[0].content, "parts", None) or []
                text = "".join(str(getattr(part, "text", "") or "") for part in parts)
            result["results"].append({
                "case_id": str(getattr(metadata, "get", lambda *_: "")("case_id", "")),
                "text": text,
                "error": str(error or ""),
            })
        return result


class GroqBatchEvaluator:
    """Submit and collect a bounded Groq Batch evaluation.

    Groq Batch takes JSONL rather than inline requests. The JSONL file is only
    kept locally for the duration of the upload; its contents are never written
    to the repository or the application database. Groq's batch job remains
    asynchronous, so this evaluator is intentionally unavailable to normal
    workflow routing.
    """

    def __init__(self, api_key: str, model: str = "openai/gpt-oss-120b", *, client: Any = None):
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover
                raise ImportError("pip install openai") from exc
            key = resolve_api_key(
                api_key, "GROQ_API_KEY", provider="Groq", config_key="llm.groq.api_key",
            )
            client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
        self.client = client
        self.model = model

    def submit(self, cases: list[EvaluationCase], *, display_name: str) -> dict[str, str]:
        if not 1 <= len(cases) <= MAX_CASES:
            raise ValueError(f"Groq Batch needs between 1 and {MAX_CASES} cases")
        lines = [json.dumps({
            "custom_id": case.case_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt_for(case)},
                ],
                "max_tokens": 900,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "tailoring_evaluation",
                        "schema": EVALUATION_SCHEMA,
                        "strict": True,
                    },
                },
                "include_reasoning": False,
            },
        }) for case in cases]

        # The OpenAI-compatible client accepts a binary file object. A temporary
        # file is unavoidable because Groq Batch accepts JSONL through Files API.
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w+b", suffix=".jsonl") as handle:
            handle.write(("\n".join(lines) + "\n").encode("utf-8"))
            handle.flush()
            handle.seek(0)
            uploaded = self.client.files.create(file=handle, purpose="batch")
        job = self.client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={"display_name": display_name},
        )
        return {"name": str(job.id), "state": str(job.status)}

    def collect(self, name: str) -> dict[str, Any]:
        """Return job state plus completed JSONL entries, if any."""
        job = self.client.batches.retrieve(name)
        result: dict[str, Any] = {
            "name": str(job.id),
            "state": str(job.status),
            "results": [],
        }
        output_file_id = getattr(job, "output_file_id", None)
        if not output_file_id:
            return result
        content = self.client.files.content(output_file_id)
        raw = content.read().decode("utf-8")
        for line in raw.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            body = ((item.get("response") or {}).get("body") or {})
            choices = body.get("choices") or []
            message = (choices[0].get("message") or {}) if choices else {}
            result["results"].append({
                "case_id": str(item.get("custom_id") or ""),
                "text": str(message.get("content") or ""),
                "error": str((item.get("error") or {}).get("message") or ""),
            })
        return result
