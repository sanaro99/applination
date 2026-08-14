"""
tweak.py — interactive CLI for adjusting a generated resume.

Usage:
  # One-shot tweak
  python -m src.tweak output/2026-04-24/Stripe_SoftwareEngineerIntern/resume.docx \\
      "Emphasize the LangGraph/LLM work more; de-emphasize the SRE stuff"

  # Specify a different provider
  python -m src.tweak resume.docx "more ML focus" --provider gemini

  # Interactive REPL — iterate until satisfied, then save
  python -m src.tweak resume.docx --interactive

How versioning works:
  resume.docx  →  resume.v2.docx  →  resume.v3.docx  …
  resume.json  →  resume.v2.json  …

The original resume.docx is never overwritten.

Interactive mode uses TweakSession, which accumulates the full instruction
history so the LLM can reason about cumulative intent across edits.
"""
from __future__ import annotations
import argparse
import json
import logging
import re
import sys
from pathlib import Path

import yaml

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_version(docx_path: Path) -> tuple[Path, Path]:
    """Return (next_docx_path, next_json_path) by incrementing the version suffix."""
    stem = docx_path.stem          # e.g. "resume" or "resume.v2"
    folder = docx_path.parent

    # Find highest existing version
    m = re.match(r"^(.+?)(?:\.v(\d+))?$", stem)
    base = m.group(1)              # "resume"
    current_v = int(m.group(2)) if m.group(2) else 1
    next_v = current_v + 1

    next_stem = f"{base}.v{next_v}"
    return folder / f"{next_stem}.docx", folder / f"{next_stem}.json"


def _find_sibling_json(docx_path: Path) -> Path | None:
    """Given resume.v3.docx, look for resume.v3.json, then resume.json."""
    stem = docx_path.stem
    candidates = [
        docx_path.with_suffix(".json"),
        docx_path.parent / "resume.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _load_config(user_spec: str | None = None) -> dict:
    """The config of the account this tweak runs as, API keys merged in.

    Config is per-user now, so there is no repo-root config.yaml to read.
    Imported here rather than at module scope: server/tweak.py imports
    ``apply_tweak`` from this module and already has its own user in hand — it
    must not drag a database import along with it.
    """
    from server.cli import context_for

    _user, cfg, _paths = context_for(user_spec)
    return cfg


def _build_provider(provider_name: str | None, cfg: dict):
    from .providers import get_provider, get_provider_with_fallback
    llm_cfg = cfg.get("llm", {})
    if provider_name:
        return get_provider(provider_name, llm_cfg)
    return get_provider_with_fallback(llm_cfg)


# ---------------------------------------------------------------------------
# Core tweak logic
# ---------------------------------------------------------------------------

def apply_tweak(
    resume_json: dict,
    job_json: dict,
    instruction: str,
    provider,
    edit_history: list[str] | None = None,
) -> dict:
    """Call the LLM to produce a modified resume JSON from the instruction.

    edit_history is the ordered list of prior instructions for this session.
    Injecting it lets the LLM reason about cumulative intent rather than
    treating each edit in isolation.
    """
    from .tailor import RESUME_CONSTRAINTS

    c = RESUME_CONSTRAINTS

    history_block = ""
    if edit_history:
        history_block = "PRIOR EDITS IN THIS SESSION (cumulative context — build on these):\n"
        for i, h in enumerate(edit_history, 1):
            history_block += f"  {i}. {h}\n"
        history_block += "\n"

    system = (
        "You are an expert resume editor. You will be given a structured resume "
        "JSON and a job description. Apply the user's editing instruction to "
        "produce an updated version of the resume JSON.\n\n"
        "Rules:\n"
        "- Preserve the exact JSON schema (same top-level keys).\n"
        "- Do not fabricate new experience or projects that aren't in the original.\n"
        "- Honour any length limits: "
        f"summary ≤ {c['summary_max_chars']} chars, "
        f"≤ {c['experience_max_items']} experience entries, "
        f"≤ {c['projects_max_items']} project entries.\n"
        "- Apply the new instruction AND respect the intent of all prior instructions.\n"
        "- Only change what the instructions ask about. Preserve everything else.\n"
        "Return ONLY valid JSON — no prose, no fences."
    )
    user_prompt = (
        f"{history_block}"
        f"CURRENT RESUME JSON:\n{json.dumps(resume_json, indent=2)}\n\n"
        f"JOB:\nCompany: {job_json.get('company','')}\n"
        f"Title: {job_json.get('title','')}\n\n"
        f"NEW EDITING INSTRUCTION:\n{instruction}\n\n"
        "Produce the updated resume JSON now."
    )
    return provider.json_call(system, user_prompt, max_tokens=2500)


# ---------------------------------------------------------------------------
# Stateful tweak session (plain Python — no LangGraph dependency)
# ---------------------------------------------------------------------------

class TweakSession:
    """Stateful interactive tweak session.

    Each call to .apply(instruction) passes the full instruction history to the
    LLM so it can reason about cumulative intent rather than isolated edits.
    """

    def __init__(self, resume_json: dict, job_json: dict, provider):
        self._provider = provider
        self._job_json = job_json
        self._current_json = resume_json
        self._edit_history: list[str] = []

    def apply(self, instruction: str) -> dict:
        """Apply instruction and return the updated resume JSON."""
        updated = apply_tweak(
            self._current_json,
            self._job_json,
            instruction,
            self._provider,
            edit_history=list(self._edit_history),
        )
        self._current_json = updated
        self._edit_history.append(instruction)
        return self._current_json

    @property
    def current(self) -> dict:
        return self._current_json

    @property
    def history(self) -> list[str]:
        return list(self._edit_history)


def render_docx(tailored: dict, user: dict, out_path: Path, cfg: dict):
    """Render tailored JSON to a one-page docx."""
    from .resume_builder import build_resume_onepage

    out_cfg = cfg.get("output", {})
    build_resume_onepage(
        tailored, user, out_path,
        font=out_cfg.get("font_name", "Calibri"),
        base_size=out_cfg.get("base_font_size", 10.5),
        margins=out_cfg.get("margins_inches", 0.5),
    )


def _diff_summary(old: dict, new: dict) -> str:
    """Very brief human-readable diff of two resume dicts."""
    lines = []
    for key in ["summary", "skills", "experience", "projects"]:
        o = json.dumps(old.get(key, ""), ensure_ascii=False)
        n = json.dumps(new.get(key, ""), ensure_ascii=False)
        if o != n:
            lines.append(f"  • {key} changed")
    return "\n".join(lines) if lines else "  (no structural changes detected)"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Tweak a generated resume with a plain-English instruction."
    )
    ap.add_argument("docx", help="Path to the resume.docx to tweak")
    ap.add_argument(
        "instruction", nargs="?", default=None,
        help="Editing instruction (omit if using --interactive)"
    )
    ap.add_argument(
        "--provider",
        choices=["claude", "gemini", "ollama", "nim", "openrouter", "deepseek", "mistral"],
        default=None,
        help="LLM provider to use for this tweak (overrides config primary)"
    )
    ap.add_argument(
        "--interactive", action="store_true",
        help="Open a REPL to iterate on tweaks"
    )
    ap.add_argument(
        "--no-pdf", action="store_true",
        help="Skip PDF conversion after tweak"
    )
    ap.add_argument(
        "--user", default=None,
        help="Account whose config and API keys to use: an email or a numeric "
             "id. Defaults to the owner.",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s :: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    docx_path = Path(args.docx).resolve()
    if not docx_path.exists():
        sys.exit(f"Error: {docx_path} does not exist.")

    # Load sibling JSON
    json_path = _find_sibling_json(docx_path)
    if json_path is None:
        sys.exit(
            f"Error: could not find resume.json alongside {docx_path.name}. "
            "Make sure to run main.py first (it saves resume.json next to the docx)."
        )

    # Load job context
    job_json_path = docx_path.parent / "job.json"
    job_json: dict = {}
    if job_json_path.exists():
        job_json = json.loads(job_json_path.read_text(encoding="utf-8"))

    resume_json = json.loads(json_path.read_text(encoding="utf-8"))

    from server.cli import UserNotFound

    try:
        cfg = _load_config(args.user)
    except UserNotFound as e:
        ap.error(str(e))
        return
    user = cfg.get("user", {})
    provider = _build_provider(args.provider, cfg)

    if args.interactive:
        _run_interactive(docx_path, resume_json, job_json, user, provider, cfg, args)
    else:
        if not args.instruction:
            ap.error("Provide an instruction, or use --interactive for REPL mode.")
        _run_one_shot(docx_path, resume_json, job_json, user, provider, cfg,
                      args.instruction, args.no_pdf)


def _run_one_shot(
    docx_path: Path,
    resume_json: dict,
    job_json: dict,
    user: dict,
    provider,
    cfg: dict,
    instruction: str,
    no_pdf: bool,
):
    print(f"Applying tweak: {instruction!r}")
    updated = apply_tweak(resume_json, job_json, instruction, provider, edit_history=[])

    print("\nChanges detected:")
    print(_diff_summary(resume_json, updated))

    next_docx, next_json = _next_version(docx_path)

    next_json.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    render_docx(updated, user, next_docx, cfg)
    print(f"\nSaved: {next_docx}")

    if not no_pdf and cfg.get("output", {}).get("produce_pdf", True):
        try:
            from .pdf_convert import docx_to_pdf
            pdf = docx_to_pdf(next_docx)
            if pdf:
                print(f"PDF:   {pdf}")
        except Exception as e:
            LOG.warning("PDF conversion failed: %s", e)


def _run_interactive(
    docx_path: Path,
    initial_json: dict,
    job_json: dict,
    user: dict,
    provider,
    cfg: dict,
    args,
):
    print("Interactive tweak mode (LangGraph session — prior instructions are remembered).")
    print("  save   — save current version and exit")
    print("  quit   — exit without saving")
    print("  diff   — show what changed vs. original")
    print("  hist   — show all instructions applied this session")
    print()

    session = TweakSession(initial_json, job_json, provider)
    original_json = initial_json
    prev_json = initial_json

    while True:
        try:
            instruction = input("tweak> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not instruction:
            continue

        if instruction.lower() in ("quit", "exit", "q"):
            print("Exiting without saving.")
            break

        if instruction.lower() in ("save", "s"):
            next_docx, next_json = _next_version(docx_path)
            next_json.write_text(json.dumps(session.current, indent=2), encoding="utf-8")
            render_docx(session.current, user, next_docx, cfg)
            print(f"Saved: {next_docx}")

            if not args.no_pdf and cfg.get("output", {}).get("produce_pdf", True):
                try:
                    from .pdf_convert import docx_to_pdf
                    pdf = docx_to_pdf(next_docx)
                    if pdf:
                        print(f"PDF:   {pdf}")
                except Exception as e:
                    LOG.warning("PDF conversion failed: %s", e)
            break

        if instruction.lower() in ("diff", "d"):
            print(_diff_summary(original_json, session.current))
            continue

        if instruction.lower() in ("hist", "history"):
            history = session.history
            if history:
                for i, h in enumerate(history, 1):
                    print(f"  {i}. {h}")
            else:
                print("  (no instructions applied yet)")
            continue

        print("Applying...")
        try:
            updated = session.apply(instruction)
            print("Changes from previous version:")
            print(_diff_summary(prev_json, updated))
            prev_json = updated
        except Exception as e:
            print(f"Error: {e}")
            print("Keeping previous version.")


if __name__ == "__main__":
    main()
