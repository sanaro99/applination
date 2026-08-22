"""Generate the demo account's committed documents. Run by hand, not at runtime.

The documents under demo_data/output/ are produced by the real renderer from
the real fixture, driven by the demo provider, rather than hand-made. That way
they cannot drift from what a visitor sees when they click "Generate" in the
demo, which is the one inconsistency a demo cannot afford.

Deliberately NOT run through src.pipeline.run_pipeline: that fetches live
postings from eight job boards, so its output folders would be whatever is
hiring today and would never match the fixed postings in demo_data/seed.json.
This drives src.main.process_job over exactly the applications that carry a
"folder" in the fixture.

    python scripts/build_demo_output.py

Then review the output and commit it.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from server.demo import DEMO_DATA, seed_demo  # noqa: E402
from server.deps import load_config, paths_for  # noqa: E402


def _letter_issues(text: str) -> list[str]:
    from src.tailor import validate_cover_letter

    return validate_cover_letter(text)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("build_demo_output")

    from src.main import process_job
    from src.providers import get_task_chains
    from src.reference_loader import (
        load_example_letters,
        load_guidelines,
        load_stories,
    )
    from src.scrapers.schema import Job
    from src.tailor import Tailor

    fixture = json.loads((DEMO_DATA / "seed.json").read_text(encoding="utf-8"))
    wanted = [a for a in fixture["applications"] if a.get("folder")]
    if not wanted:
        log.error("no application in seed.json carries a 'folder'")
        return 1

    user_id = seed_demo()
    cfg = load_config(user_id)
    paths = paths_for(user_id)

    if cfg["llm"]["primary"] != "demo":
        log.error("the demo config must route to the demo provider, not a real one")
        return 1

    master = yaml.safe_load(paths.resume_path.read_text(encoding="utf-8"))
    bio = paths.bio_path.read_text(encoding="utf-8")
    stories = load_stories(paths.stories_dir)
    examples = load_example_letters(paths.cover_letter_examples_dir)
    guidelines = load_guidelines(paths.guidelines_dir)

    tailor = Tailor(task_chains=get_task_chains(cfg["llm"]))
    out_cfg = dict(cfg["output"])
    out_cfg["root"] = str(paths.resolve_output(cfg))

    staging = Path(out_cfg["root"]) / "demo-build"
    staging.mkdir(parents=True, exist_ok=True)

    produced: list[tuple[str, Path]] = []
    for spec in wanted:
        job = Job(
            source=spec.get("source", "greenhouse"),
            company=spec["company"],
            title=spec["title"],
            location=spec.get("location", ""),
            url=spec.get("url", ""),
            description=spec.get("description", ""),
            remote="remote" in spec.get("location", "").lower(),
        )
        log.info("generating %s / %s", job.company, job.title)
        result = process_job(
            job, master, cfg["user"], bio,
            stories, examples, guidelines,
            staging, tailor, out_cfg, log,
        )
        folder_name = result.get("folder_name") or job.safe_folder_name()
        if folder_name != spec["folder"]:
            # The fixture names the folder in three places (seed.json's folder,
            # the copied tree, and every Application.folder_rel). A mismatch
            # here means the demo's download links resolve to nothing.
            log.error(
                "folder mismatch: seed.json says %r, process_job wrote %r. "
                "Update seed.json to the latter.",
                spec["folder"], folder_name,
            )
            return 1
        folder = staging / folder_name
        # process_job logs the placeholder fallback as an ERROR and then
        # returns normally, so without this check the script reports success
        # while committing a letter that says nothing. It happened once: the
        # fixture was 210 words against validate_cover_letter's 220 floor.
        letter = folder / "cover_letter.txt"
        if letter.is_file():
            issues = _letter_issues(letter.read_text(encoding="utf-8"))
            if issues:
                log.error(
                    "%s: the generated cover letter is a placeholder or failed "
                    "validation (%s). Fix demo_data/llm/cover_letter.txt.",
                    folder_name, ", ".join(issues),
                )
                return 1
        produced.append((folder_name, folder))

    dest_root = DEMO_DATA / "output"
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True)
    for name, folder in produced:
        # Committed without a date component: the seeder places each under the
        # rebased day of the run that produced it, so they never look stale.
        shutil.copytree(folder, dest_root / name)
        files = sorted(p.name for p in (dest_root / name).iterdir())
        log.info("committed %s: %s", name, ", ".join(files))

    shutil.rmtree(staging, ignore_errors=True)
    log.info(
        "done. Review the documents, set resume_file/cover_file in "
        "demo_data/seed.json, then commit demo_data/output/."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
