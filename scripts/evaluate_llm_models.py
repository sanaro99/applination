"""Run a private, bounded comparison of supported application-tailoring models.

Examples (run inside the API container so encrypted user keys are available):

  python scripts/evaluate_llm_models.py --user you@example.com --cases cases.json --candidate luna
  python scripts/evaluate_llm_models.py --user you@example.com --cases cases.json --candidate gpt-oss-batch --submit-batch
  python scripts/evaluate_llm_models.py --user you@example.com --candidate gpt-oss-batch --collect-batch batch_id

The cases file is intentionally not part of the repository. Its shape is a JSON
array whose entries contain `id`, `candidate_profile`, and `job` (with title,
company, and description/desc). Results are stored under that user's output
directory, never in the application database or the repository.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from server.cli import UserNotFound, context_for
from src.model_evaluation import (
    CURATED_CANDIDATES,
    GeminiBatchEvaluator,
    GroqBatchEvaluator,
    load_cases,
    run_sync_evaluation,
)


def _save(directory: Path, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare supported LLMs on private tailoring cases.")
    parser.add_argument("--user", default=None, help="Account email or id; defaults to the owner.")
    parser.add_argument("--cases", help="Private JSON array of evaluation cases.")
    parser.add_argument("--candidate", choices=sorted(CURATED_CANDIDATES), help="Model target to run.")
    parser.add_argument("--limit", type=int, default=20, help="Cases to run or submit, between 1 and 30.")
    parser.add_argument("--submit-batch", action="store_true", help="Submit a supported batch target; does not wait for completion.")
    parser.add_argument("--collect-batch", metavar="NAME", help="Collect a previously submitted batch job.")
    args = parser.parse_args()

    try:
        user, cfg, paths = context_for(args.user)
    except UserNotFound as exc:
        parser.error(str(exc))
    output_dir = paths.default_output_dir / "model-evaluations"

    if args.collect_batch:
        if not args.candidate or CURATED_CANDIDATES[args.candidate].mode != "batch":
            parser.error("--collect-batch requires a batch --candidate")
        candidate = CURATED_CANDIDATES[args.candidate]
        block = (cfg.get("llm") or {}).get(candidate.provider) or {}
        evaluator_class = GeminiBatchEvaluator if candidate.provider == "gemini" else GroqBatchEvaluator
        evaluator = evaluator_class(block.get("api_key", ""), model=candidate.model)
        saved = _save(output_dir, {
            "kind": f"{candidate.slug}-collection",
            "candidate": candidate.__dict__,
            "result": evaluator.collect(args.collect_batch),
        })
        print(saved)
        return 0

    if not args.cases or not args.candidate:
        parser.error("--cases and --candidate are required unless using --collect-batch")
    candidate = CURATED_CANDIDATES[args.candidate]
    cases = load_cases(args.cases, limit=args.limit)
    if args.submit_batch:
        if candidate.mode != "batch":
            parser.error("--submit-batch requires a batch --candidate")
        block = (cfg.get("llm") or {}).get(candidate.provider) or {}
        evaluator_class = GeminiBatchEvaluator if candidate.provider == "gemini" else GroqBatchEvaluator
        evaluator = evaluator_class(block.get("api_key", ""), model=candidate.model)
        result = evaluator.submit(cases, display_name=f"applination-eval-user-{user.id}")
        saved = _save(output_dir, {"kind": f"{candidate.slug}-submission", "candidate": candidate.__dict__, "result": result})
        print(f"Submitted {result['name']} ({result['state']}); saved {saved}")
        return 0
    if candidate.mode == "batch":
        parser.error("Batch targets are asynchronous; add --submit-batch, then collect them later.")

    records = run_sync_evaluation((cfg.get("llm") or {}), candidate, cases)
    saved = _save(output_dir, {"kind": "sync-evaluation", "candidate": candidate.__dict__, "records": records})
    print(saved)
    return 0 if all(record["ok"] for record in records) else 1


if __name__ == "__main__":
    sys.exit(main())
