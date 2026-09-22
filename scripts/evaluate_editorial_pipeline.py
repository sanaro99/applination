"""Run the real resume and cover-letter pipeline against private eval cases."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

# Keep the documented ``python scripts/evaluate_editorial_pipeline.py`` form
# working on Windows and Unix, where Python otherwise puts only ``scripts/``
# on the import path.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.cli import UserNotFound, context_for
from src.editorial_evaluation import load_editorial_cases, run_editorial_evaluation
from src.model_evaluation import CURATED_CANDIDATES


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate evidence-led resume and letter generation.")
    parser.add_argument("--user", default=None, help="Account email or id; defaults to owner.")
    parser.add_argument("--cases", required=True, help="Private JSON editorial cases.")
    parser.add_argument("--candidate", required=True, choices=sorted(CURATED_CANDIDATES))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--braintrust", action="store_true",
        help="Publish the completed local run to Braintrust after evaluation.",
    )
    parser.add_argument(
        "--braintrust-project", default="applination-prompt-evals",
        help="Braintrust project name used with --braintrust.",
    )
    parser.add_argument(
        "--experiment", default=None,
        help="Experiment name; defaults to candidate plus the UTC timestamp.",
    )
    parser.add_argument(
        "--base-experiment", default=None,
        help="Optional Braintrust baseline experiment name for comparison.",
    )
    parser.add_argument(
        "--allow-sensitive-upload", action="store_true",
        help="Allow upload of cases not explicitly marked cloud_safe. Use with care.",
    )
    args = parser.parse_args()

    candidate = CURATED_CANDIDATES[args.candidate]
    if candidate.mode != "sync":
        parser.error("The multi-stage pipeline requires a synchronous candidate")
    try:
        _user, cfg, paths = context_for(args.user)
    except UserNotFound as exc:
        parser.error(str(exc))

    cases = load_editorial_cases(args.cases, limit=args.limit)
    records = run_editorial_evaluation(cfg.get("llm") or {}, candidate, cases)
    output_dir = paths.default_output_dir / "editorial-evaluations"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = output_dir / f"{candidate.slug}-{stamp}.json"
    output.write_text(json.dumps({
        "kind": "editorial-pipeline-evaluation",
        "candidate": candidate.__dict__,
        "experiment": args.experiment or f"{candidate.slug}-{stamp}",
        "records": records,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output)

    if args.braintrust:
        from src.braintrust_reporting import publish_editorial_experiment

        remote = publish_editorial_experiment(
            cases,
            records,
            project=args.braintrust_project,
            experiment_name=args.experiment or f"{candidate.slug}-{stamp}",
            candidate=candidate.__dict__,
            base_experiment=args.base_experiment,
            allow_sensitive_upload=args.allow_sensitive_upload,
        )
        if remote["url"]:
            print(remote["url"])
        else:
            print(f"Braintrust experiment: {remote['project']} / {remote['experiment']}")
    return 0 if all(record["ok"] for record in records) else 1


if __name__ == "__main__":
    sys.exit(main())
