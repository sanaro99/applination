"""Stable identities for prompts that participate in evaluation experiments.

Prompt text remains in the module that owns the behavior.  This registry gives
those prompts a small, vendor-neutral identity so local artifacts and optional
experiment reporters can compare like with like without making production
generation depend on a remote prompt service.

The rendered hash deliberately covers the complete invocation while metadata
contains hashes only, never candidate or job text.  Git remains the source of
truth for recovering the exact prompt implementation behind a version.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    version: str
    description: str

    @property
    def id(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True)
class PromptInvocation:
    definition: PromptDefinition
    system: str
    user: str
    schema: dict[str, Any] | None = None

    @property
    def rendered_sha256(self) -> str:
        payload = json.dumps(
            {
                "id": self.definition.id,
                "system": self.system,
                "user": self.user,
                "schema": self.schema,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def metadata(self) -> dict[str, str]:
        """Return reproducibility metadata without returning prompt contents."""
        return {
            "name": self.definition.name,
            "version": self.definition.version,
            "id": self.definition.id,
            "rendered_sha256": self.rendered_sha256,
        }


class PromptRegistry:
    """Resolve registered prompt versions and construct tracked invocations."""

    def __init__(self, definitions: Iterable[PromptDefinition]):
        self._definitions: dict[str, PromptDefinition] = {}
        for definition in definitions:
            if definition.name in self._definitions:
                raise ValueError(f"Duplicate prompt name: {definition.name}")
            self._definitions[definition.name] = definition

    def build(
        self,
        name: str,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> PromptInvocation:
        try:
            definition = self._definitions[name]
        except KeyError as exc:
            raise KeyError(f"Unregistered prompt: {name}") from exc
        if version is not None and version != definition.version:
            raise ValueError(
                f"Prompt {name} has version {definition.version}, not {version}"
            )
        return PromptInvocation(definition, system, user, schema)

    def manifest(self, names: Iterable[str] | None = None) -> dict[str, str]:
        selected = list(names) if names is not None else sorted(self._definitions)
        manifest: dict[str, str] = {}
        for name in selected:
            try:
                manifest[name] = self._definitions[name].version
            except KeyError as exc:
                raise KeyError(f"Unregistered prompt: {name}") from exc
        return manifest


PROMPTS = PromptRegistry([
    PromptDefinition(
        "resume.content_plan", "1",
        "Select grounded evidence and plan job-specific resume content.",
    ),
    PromptDefinition(
        "resume.editorial_write", "1",
        "Write renderer-compatible resume JSON from an approved evidence plan.",
    ),
    PromptDefinition(
        "resume.grounding_review", "1",
        "Classify generated claims against cited source evidence.",
    ),
    PromptDefinition(
        "resume.grounding_repair", "1",
        "Repair only claims rejected by the grounding review.",
    ),
    PromptDefinition(
        "cover_letter.write", "1",
        "Write the grounded three-paragraph cover-letter body.",
    ),
    PromptDefinition(
        "cover_letter.critique", "1",
        "Score a cover letter before an optional revision.",
    ),
    PromptDefinition(
        "cover_letter.revise", "1",
        "Revise a weak cover letter while preserving grounded facts.",
    ),
])


EDITORIAL_PROMPT_NAMES = (
    "resume.content_plan",
    "resume.editorial_write",
    "resume.grounding_review",
    "resume.grounding_repair",
    "cover_letter.write",
    "cover_letter.critique",
    "cover_letter.revise",
)


def editorial_prompt_manifest() -> dict[str, str]:
    return PROMPTS.manifest(EDITORIAL_PROMPT_NAMES)
