"""JSON schemas used to constrain LLM outputs at the API level.

Providers that support strict structured outputs (DeepSeek json_schema,
Mistral json_schema, Gemini response_schema, Claude tool_use) accept these
schemas via the `schema` kwarg on LLMProvider.json_call().
"""
from .resume_schema import RESUME_SCHEMA, CRITIQUE_SCHEMA, RELINEFIT_SCHEMA
from .story_schema import STORY_SCHEMA
from .master_resume_schema import MASTER_RESUME_SCHEMA
from .keywords_schema import KEYWORDS_SCHEMA

__all__ = [
    "RESUME_SCHEMA",
    "CRITIQUE_SCHEMA",
    "RELINEFIT_SCHEMA",
    "STORY_SCHEMA",
    "MASTER_RESUME_SCHEMA",
    "KEYWORDS_SCHEMA",
]
