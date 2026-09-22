# Prompt evaluation workflow

Applination evaluates prompts through the real local pipeline. Braintrust is an
optional experiment reporter, not a runtime dependency, provider proxy, or
production prompt store. Prompt text remains code-reviewed in Git.

## Prompt identities

Prompts that participate in the editorial evaluation are registered in
`src/prompt_registry.py`. A prompt change must bump its registered version.
Evaluation artifacts record the prompt-version manifest, and individual
cover-letter debug records also include a SHA-256 hash of the exact rendered
invocation. The hash supports reproduction without exposing prompt contents in
metadata.

Change one prompt and one variable at a time. Use the same dataset version,
model, thinking mode, and output limits for the baseline and candidate runs.
For stochastic writing comparisons, run each variant multiple times and review
paired case-level regressions rather than trusting only an aggregate average.

## Local evaluation

```bash
python scripts/evaluate_editorial_pipeline.py \
  --user you@example.com \
  --candidate deepseek \
  --cases /private/editorial-cases.json \
  --experiment cover-letter-v2-local
```

The complete JSON result is written below the user's
`output/editorial-evaluations/` directory and remains the durable source of
truth.

Treat these as release-blocking checks:

- the run completed;
- semantic grounding passed;
- no unsupported numbers were introduced;
- structured output and cover-letter validation passed;
- required sections and core skills survived;
- the rendered resume is one page when PDF rendering is part of the run.

Use blinded human comparison for relevance, specificity, readability, and
recruiter usefulness. Calibrate any LLM judge against those labels before using
it as a release gate.

## Optional Braintrust publishing

Install the developer-only dependency and set an API key outside source control:

```bash
pip install -r requirements-eval.txt
export BRAINTRUST_API_KEY=...
```

PowerShell uses `$env:BRAINTRUST_API_KEY="..."` instead of `export`.

Then add `--braintrust`:

```bash
python scripts/evaluate_editorial_pipeline.py \
  --user you@example.com \
  --candidate deepseek \
  --cases docs/editorial-evaluation-cases.example.json \
  --experiment resume-prompts-v1 \
  --braintrust
```

For a candidate run compared with an existing baseline:

```bash
python scripts/evaluate_editorial_pipeline.py \
  --user you@example.com \
  --candidate deepseek \
  --cases docs/editorial-evaluation-cases.example.json \
  --experiment resume-prompts-v2 \
  --base-experiment resume-prompts-v1 \
  --braintrust
```

Publishing happens only after local generation finishes. It sends case inputs,
generated resume and cover-letter outputs, deterministic scores, latency, model
metadata, and prompt versions. It never sends provider API keys or application
configuration.

## Privacy rule

Every case is private by default. Braintrust publishing refuses a case unless
its JSON contains `"cloud_safe": true`. Mark only synthetic or thoroughly
redacted cases this way. The CLI offers `--allow-sensitive-upload` as an explicit
escape hatch, but routine experiments should not use it.

Real resumes, personal contact information, and candidate-owned stories should
stay in local-only case files. If unredacted evaluation data must be analyzed in
a shared UI, use a self-hosted evaluation platform instead of the cloud
publisher.
