# Evidence-led resume and cover-letter pipeline

The v2 pipeline makes content decisions before layout decisions:

1. `src/evidence.py` normalizes the master resume and matched stories into a ledger with stable IDs.
2. `src/resume_pipeline.py` asks the configured tailoring model for a job-specific content plan.
3. The editorial writer may select, rewrite, merge, split, compress, and reorder the selected evidence.
4. `src/grounding.py` combines deterministic quantitative checks with an LLM semantic review. It classifies claims as `direct`, `entailed`, `adjacent`, `unsupported`, or `contradictory`.
5. One narrowly scoped repair pass handles rejected claims. Anything still unsupported is removed deterministically.
6. `src/layout_policy.py` and `src/resume_builder.py` enforce the page budget without restoring omitted master content or forcing every bullet into an exact character band.

The public `run_tailor_graph` function remains as a compatibility seam. The old keyword-fix, critique/revise, and line-fit graph is no longer behind it. `line_fitter.py` remains temporarily for external callers and historical regression tests, but the production pipeline does not invoke it.

## Grounding policy

- Direct and entailed claims may appear as ordinary resume claims.
- Adjacent knowledge may support explicitly qualified transfer language. It is not sufficient evidence that the candidate used a particular technology professionally.
- A planner may select at most four adjacent skills, only when the job explicitly requests them and cited source evidence makes the transfer technically defensible. They render with a visible qualifier such as `MongoDB (transferable familiarity)` under `Related Knowledge`, never as unqualified hands-on skills.
- Metrics, employers, titles, dates, technologies, responsibilities, and outcomes may not be invented.
- The grounding audit is written separately as `grounding_audit.json`; renderer-facing `resume.json` stays compatible with the existing document and tweak flows.

For example, SQL/PostgreSQL experience can support `MongoDB (transferable familiarity)` or summary language about transferable data-modeling foundations for a MongoDB role. It cannot support an unqualified `MongoDB` skill or a claim that the candidate operated MongoDB in production unless another source item says so. The same policy applies to neighboring tools, architectures, domains, and operating concepts; the semantic reviewer judges the relationship rather than relying on a hard-coded technology map.

## Layout policy

- Most bullets should be approximately one printed line.
- A 1.5-line bullet is valid.
- One to three genuinely important bullets may occupy two lines.
- A small orphan wrap is cleaned only when a semantics-preserving phrase reduction can pull it back. Complete meaning wins when no safe cleanup exists.
- Page overflow removes lowest-priority tail content selected and ordered by the editorial stage.
- The generated PDF is checked for its real page count. If it exceeds one page, the renderer makes up to three narrow tail-removal repairs and re-renders.
- Sparse pages are not padded with generic bullets or projects from the master resume.

## Compatibility and migration

- Existing master-resume YAML requires no migration.
- Existing provider task names continue to work. `relinefit` configuration is accepted but unused so persisted configs do not fail.
- `Tailor.tailor_resume`, `run_tailor_graph`, `build_resume_onepage`, and the renderer-facing resume JSON shape remain compatible.
- New run output includes `grounding_audit.json` and v2 stage details in `pipeline_metrics.json`.
- The public demo skips semantic-model calls and uses deterministic grounding because its fixture provider is not a factual judge.

## Evaluation

Run the actual multi-stage pipeline, not only a single compatibility prompt:

```bash
python scripts/evaluate_editorial_pipeline.py \
  --user you@example.com \
  --candidate luna \
  --cases /private/editorial-cases.json
```

Results are stored under the user's `output/editorial-evaluations/` directory. The case file may contain real resume data, so keep it outside the repository. `docs/editorial-evaluation-cases.example.json` is a synthetic starting point.

Every serious comparison should include:

1. A rewrite case where wording changes but every fact remains stable.
2. A merge case where two related source bullets become one stronger achievement.
3. A split case where one dense source bullet becomes two independently useful bullets.
4. A subset case with substantially more source bullets and projects than fit on one page.
5. Two jobs against the same master resume that should select different evidence.
6. An adjacent-skill case such as SQL/PostgreSQL evidence against a MongoDB requirement.
7. A metric trap where the job asks for scale but the source contains no number.
8. An attribution trap where similar facts belong to different employers or projects.
9. A cover-letter transfer case that should explain relevance without claiming direct experience.
10. A page-pressure case containing several strong items, including one achievement worth a two-line bullet.

Compare unsupported-claim recall first, then human-rated relevance and writing quality. Also review rewritten-bullet ratio, evidence selection, bullet-length distribution, actual PDF page count, latency, and model cost. A higher rewrite ratio is not automatically better; it matters only when factual support and recruiter usefulness remain strong.
