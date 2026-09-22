# Model evaluation harness

The application supports these comparison targets without changing its live routing:

- GPT-5.6 Luna through OpenAI
- Gemini 3.8 Flash through the normal Gemini API
- Gemini 3.8 Flash through the asynchronous Gemini Batch API
- GPT-OSS 120B through Groq, including Groq Batch

The test uses the same structured, evidence-only application-tailoring prompt for every target. Put a private JSON array in a file outside the repository. Each entry needs an `id`, `candidate_profile`, and `job` object. The job should include `company`, `title`, and `description` (or `desc`). Start with 20 representative postings and increase only to 30 after reviewing the first outputs.

Run the script inside the API container, where a user's encrypted configuration is available:

```text
python scripts/evaluate_llm_models.py --user you@example.com --cases /private/cases.json --candidate luna
python scripts/evaluate_llm_models.py --user you@example.com --cases /private/cases.json --candidate gemini
python scripts/evaluate_llm_models.py --user you@example.com --cases /private/cases.json --candidate gpt-oss
python scripts/evaluate_llm_models.py --user you@example.com --cases /private/cases.json --candidate gpt-oss-batch --submit-batch
python scripts/evaluate_llm_models.py --user you@example.com --cases /private/cases.json --candidate gemini-batch --submit-batch
```

The final two commands submit work and return immediately. Both batch APIs are intended for non-urgent evaluation work, so neither is an interactive application-run provider. Collect a batch later using the returned job name and the matching candidate:

```text
python scripts/evaluate_llm_models.py --user you@example.com --candidate gpt-oss-batch --collect-batch YOUR_JOB_ID
python scripts/evaluate_llm_models.py --user you@example.com --candidate gemini-batch --collect-batch batches/YOUR_JOB_NAME
```

Results are private JSON files under `data/users/<user id>/output/model-evaluations/`. Review factual grounding, useful evidence, missed requirements, and whether the tailoring actions make a better resume and letter. The harness does not change the configured primary or fallback model; make that routing decision only after reviewing the comparison.

For the complete multi-stage resume and cover-letter workflow, use
`scripts/evaluate_editorial_pipeline.py` and the protocol in
`docs/EDITORIAL-PIPELINE.md`. Batch candidates are intentionally unavailable
there because evidence selection, writing, validation, and conditional repair
are sequential stages.

Google documents the Gemini Batch API as asynchronous batch processing at half the standard cost, with inline requests appropriate for small batches. Groq Batch also provides a half-price asynchronous path for GPT-OSS and accepts JSONL through its Files API. See the [Gemini Batch API documentation](https://ai.google.dev/gemini-api/docs/batch-api) and [Groq Batch API documentation](https://console.groq.com/docs/batch).
