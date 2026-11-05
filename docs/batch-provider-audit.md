# Native batch provider audit — 2026-10-02

This audit used Context7 for `/openai/openai-python`,
`/anthropics/anthropic-sdk-python`, and `/googleapis/python-genai`, then checked
the official provider documentation and installed SDK behavior.

## Findings

- **OpenAI:** Run #63's persisted errors were OpenAI responses. PR #91 fixes
  optional/open schemas being sent with strict mode and reserves bounded output
  room when reasoning is enabled. This is transport behavior; saved request
  identities and successful transcript entries remain reusable on explicit retry.
- **Claude:** The adapter uses Message Batches with forced tool output for schemas,
  without extended thinking. Optional tool-input fields do not use OpenAI's strict
  schema contract. The audit found two unfinished stop reasons being treated as
  success: `model_context_window_exceeded` and `pause_turn`. Both now fail the item,
  retaining content, usage and the reason for explicit review.
- **Gemini:** The inline request/schema/metadata/result shapes match the installed
  SDK. However, Gemini 2.5 counts thinking in its total output limit. Batch calls
  now set thinking explicitly and reserve that allowance in addition to the
  caller's final-answer budget, rather than inheriting dynamic thinking.
  Flash/Flash-Lite use zero for `off`; Pro requires 128. Enabled thinking is bounded
  at 4,000 tokens, or 1,024 for `low`, respecting model minimums. This allowance is
  a guide, not a guarantee of how many thoughts the model produces; the total
  output cap remains enforced and `MAX_TOKENS` remains a failure.

Ordinary call budgets/configuration, automatic retry policy and result validation
are unchanged. Batch estimates and retry notices include the additional reasoning
room. Discounts apply to token rates, not a guarantee of half the total run cost.

## Validation boundary

`tests/test_batch_provider_contracts.py` uses **real installed SDKs with mocked
HTTP transports**, checking native submission serialization, schema transport,
request/result keys, usage, completion, cancellation, provider errors and truncated
results. Installed versions: OpenAI 2.38.0, Anthropic 0.104.1, google-genai 2.6.0.

The existing replay/coordinator/application publication test now runs with all
three native provider routes. Its generated responses are deterministic fixtures.
It verifies local pipeline behavior, not real model quality or API acceptance.

No paid requests were made. A live trial still needs to confirm account access,
current model availability, quotas, provider acceptance and quality/grounding of
real generated output. Start with a small trial after deployment.

## Primary references

- [OpenAI Batch API](https://developers.openai.com/api/docs/guides/batch)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Claude batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
- [Claude stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)
- [Gemini Batch API](https://ai.google.dev/gemini-api/docs/batch-api)
- [Gemini generateContent thinking and token limits](https://ai.google.dev/gemini-api/docs/generate-content/thinking)
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
