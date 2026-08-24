"""Per-user filesystem layout.

Before PR 3 there was exactly one of everything: ``config.yaml`` in the repo
root, one ``master_data/``, one ``output/``. Every user now gets their own::

    data/users/<user_id>/
      config.yaml
      master_data/{resume.yaml,bio.md,stories/,cover_letters/examples/}
      output/<date>/<Company_Role>/

Two directories deliberately stay global and shared: ``master_data/guidelines/``
and ``master_data/templates/``. They are committed to the repository and
generic — writing advice, not personal data — so they are read from the repo for
every user and never copied per account.

Everything that touches a user's files goes through a ``UserPaths``. Nothing
outside this module should join a path onto ``data/users`` by hand: the
containment guard in :func:`resolve_within` is what keeps one account's request
from reading another's resume, and it only helps if it is the single door.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USERS_DIR = ROOT / "data" / "users"
EXAMPLE_CONFIG_PATH = ROOT / "config.example.yaml"

# Shared, committed, read-only as far as the app is concerned.
GLOBAL_MASTER_DIR = ROOT / "master_data"
GUIDELINES_DIR = GLOBAL_MASTER_DIR / "guidelines"
TEMPLATES_DIR = GLOBAL_MASTER_DIR / "templates"


class PathEscape(ValueError):
    """A caller-supplied relative path resolved outside its allowed base."""


def resolve_within(base: Path, *parts: str | Path) -> Path:
    """Join ``parts`` onto ``base`` and prove the result stays inside it.

    ``.resolve()`` before the check, not after joining alone: ``..`` segments,
    absolute components (``Path("/a") / "/etc/passwd"`` discards ``/a``
    entirely), and symlinks all have to be collapsed before containment means
    anything.

    Raises :class:`PathEscape` rather than returning None so a forgotten check
    at a call site cannot degrade into serving the wrong file.
    """
    base_resolved = base.resolve()
    candidate = base_resolved.joinpath(*parts).resolve()
    if candidate != base_resolved and not candidate.is_relative_to(base_resolved):
        raise PathEscape(f"{candidate} is outside {base_resolved}")
    return candidate


@dataclass(frozen=True)
class UserPaths:
    """Where one user's files live. Cheap to construct; construct it per request
    rather than caching it — see the note on :func:`output_root` in deps.py."""

    user_id: int

    @cached_property
    def root(self) -> Path:
        return USERS_DIR / str(self.user_id)

    @cached_property
    def config_path(self) -> Path:
        return self.root / "config.yaml"

    @cached_property
    def master_dir(self) -> Path:
        return self.root / "master_data"

    @cached_property
    def resume_path(self) -> Path:
        return self.master_dir / "resume.yaml"

    @cached_property
    def bio_path(self) -> Path:
        return self.master_dir / "bio.md"

    @cached_property
    def stories_dir(self) -> Path:
        return self.master_dir / "stories"

    @cached_property
    def intake_dir(self) -> Path:
        """Raw material captured during onboarding, before any LLM has touched
        it. Underscore-prefixed like ``stories/_INDEX.md``, and deliberately
        *outside* ``stories/``: ``reference_loader`` and
        ``onboarding._count_stories`` glob ``stories/*.md``, so a draft parked
        there would be matched into a real cover letter as though the user had
        written and approved it."""
        return self.master_dir / "_intake"

    @cached_property
    def intake_stories_dir(self) -> Path:
        return self.intake_dir / "stories"

    @cached_property
    def intake_consumed_dir(self) -> Path:
        """Drafts are moved here after enrichment rather than deleted, so a
        failed or unsatisfying enrichment never destroys the user's own words."""
        return self.intake_dir / "consumed"

    @cached_property
    def intake_resume_path(self) -> Path:
        return self.intake_dir / "resume_raw.txt"

    @cached_property
    def intake_notes_path(self) -> Path:
        return self.intake_dir / "notes.md"

    @cached_property
    def cover_letter_examples_dir(self) -> Path:
        return self.master_dir / "cover_letters" / "examples"

    @cached_property
    def default_output_dir(self) -> Path:
        return self.root / "output"

    # Global, shared, identical for every user. Exposed here so callers can take
    # a single UserPaths and not also have to import the module constants.
    @property
    def guidelines_dir(self) -> Path:
        return GUIDELINES_DIR

    @property
    def templates_dir(self) -> Path:
        return TEMPLATES_DIR

    @property
    def taxonomy_dir(self) -> Path:
        """Where ``stories/_INDEX.md`` lives — the committed, generic tag/role/
        company taxonomy. Global like the guidelines: it describes the shape of
        a story, not anybody's stories."""
        return GLOBAL_MASTER_DIR / "stories"

    def ensure(self) -> UserPaths:
        """Create the directory tree and seed config.yaml from the committed
        template. Idempotent — safe to call on every request.

        Seeding matters: without a config.yaml a brand-new account cannot reach
        the onboarding wizard, because the wizard itself reads config to work
        out what is still missing.
        """
        for d in (
            self.master_dir,
            self.stories_dir,
            self.cover_letter_examples_dir,
            self.default_output_dir,
            self.intake_stories_dir,
            self.intake_consumed_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists() and EXAMPLE_CONFIG_PATH.exists():
            self.config_path.write_text(
                EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8"
            )
        return self

    def resolve_output(self, cfg: dict | None = None) -> Path:
        """This user's output root, honouring ``output.root`` from their config
        only while it stays inside their own directory.

        The config value is user-editable through the raw YAML editor, so an
        absolute ``/`` or a ``../2/output`` would otherwise let one account
        write into another's tree — or anywhere on the host. A value that
        escapes is ignored in favour of the default rather than raising: the
        run should still happen, just sandboxed.
        """
        raw = str(((cfg or {}).get("output") or {}).get("root") or "").strip()
        if not raw:
            return self.default_output_dir
        try:
            resolved = resolve_within(self.root, raw)
        except PathEscape:
            return self.default_output_dir
        # "./output" and "output" both land on the default; anything else is a
        # deliberate subdirectory choice and is honoured.
        return resolved


def user_paths(user: object) -> UserPaths:
    """Build a :class:`UserPaths` from a ``User`` row or a bare id."""
    user_id = getattr(user, "id", user)
    if not isinstance(user_id, int):
        raise TypeError(f"expected a User or an int user id, got {user!r}")
    return UserPaths(user_id=user_id)
