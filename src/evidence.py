"""Evidence normalization for resume and cover-letter generation.

The master resume is intentionally permissive YAML.  This module turns it into
a stable, addressable evidence ledger so downstream prompts can cite facts
without coupling themselves to that storage shape.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
import re
from typing import Iterable


_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "our", "that", "the", "their", "this",
    "to", "we", "will", "with", "you", "your",
    "software", "engineer", "engineering", "team", "teams", "work", "working",
    "project", "projects", "develop", "development", "built", "building",
    "experience", "role", "candidate", "applications", "users", "across",
}

_ROLE_FAMILIES = (
    {"ai", "ml", "machine", "learning", "llm", "rag", "genai", "model", "models", "embeddings", "inference"},
    {"reliability", "sre", "monitoring", "observability", "incident", "infrastructure", "infra", "platform", "distributed", "cloud"},
    {"backend", "api", "fastapi", "django", "flask", "server", "microservices"},
    {"frontend", "react", "next.js", "web", "ui"},
    {"data", "database", "sql", "mongodb", "storage", "ingestion"},
    {"testing", "test", "tests", "ci", "cd", "automation"},
)


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    kind: str
    text: str
    source_id: str
    support: str = "direct"

    def as_dict(self) -> dict:
        return asdict(self)


def _dates(entry: dict) -> str:
    explicit = str(entry.get("dates") or "").strip()
    if explicit:
        return explicit
    start = str(entry.get("start_date") or "").strip()
    end = str(entry.get("end_date") or "").strip()
    return " - ".join(part for part in (start, end) if part)


def _recency(entry: dict) -> tuple[int, int]:
    """Sort display identities by their most recent date, not planner rank."""
    value = str(entry.get("end_date") or entry.get("date") or entry.get("dates") or "").strip()
    if value.lower() in {"present", "current", "ongoing"} or re.search(
        r"\b(?:present|current|ongoing)\b", value, re.IGNORECASE,
    ):
        return (9999, 12)
    month_years = re.findall(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\.?\s+\d{4}\b",
        value, re.IGNORECASE,
    )
    candidates = list(reversed(month_years)) or list(reversed(re.split(r"\s+-\s+", value)))
    for pattern in ("%b %Y", "%B %Y", "%Y-%m", "%Y"):
        for part in candidates:
            try:
                date = datetime.strptime(part.strip().replace(".", ""), pattern)
                return date.year, date.month
            except ValueError:
                continue
    years = re.findall(r"\b(?:19|20)\d{2}\b", value)
    if years:
        return int(years[-1]), 1
    return (0, 0)


def _skill_groups(master: dict) -> Iterable[tuple[str, list]]:
    raw = master.get("skills") or {}
    if isinstance(raw, dict):
        for group, values in raw.items():
            if isinstance(values, list):
                yield str(group), values
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                yield str(entry.get("group") or "Skills"), list(entry.get("items") or [])


def build_evidence_ledger(master: dict, stories: list[dict] | None = None) -> list[EvidenceItem]:
    """Return a stable evidence ledger derived only from user-provided sources."""
    items: list[EvidenceItem] = []

    for i, text in enumerate(master.get("summary_options") or []):
        if str(text).strip():
            items.append(EvidenceItem(f"summary.{i}", "summary", str(text).strip(), "summary"))

    for i, skill in enumerate(master.get("core_skills") or []):
        if str(skill).strip():
            items.append(EvidenceItem(f"core_skill.{i}", "skill", str(skill).strip(), "skills"))

    for i, skill in enumerate(master.get("ats_adjacent_skills") or []):
        if str(skill).strip():
            items.append(EvidenceItem(
                f"adjacent_skill.{i}", "skill", str(skill).strip(), "skills", "adjacent",
            ))

    skill_idx = 0
    for group, values in _skill_groups(master):
        for value in values:
            value = str(value).strip()
            if not value:
                continue
            items.append(EvidenceItem(
                f"skill.{skill_idx}", "skill", f"{group}: {value}", "skills",
            ))
            skill_idx += 1

    for i, entry in enumerate(master.get("experience") or []):
        source_id = f"experience.{i}"
        identity = " | ".join(filter(None, [
            str(entry.get("company") or "").strip(),
            str(entry.get("role") or "").strip(),
            str(entry.get("location") or "").strip(),
            _dates(entry),
        ]))
        items.append(EvidenceItem(source_id, "experience_identity", identity, source_id))
        for j, bullet in enumerate(entry.get("bullets_all") or entry.get("bullets") or []):
            if str(bullet).strip():
                items.append(EvidenceItem(
                    f"{source_id}.bullet.{j}", "experience_bullet",
                    str(bullet).strip(), source_id,
                ))

    for i, entry in enumerate(master.get("projects") or []):
        source_id = f"project.{i}"
        identity = " | ".join(filter(None, [
            str(entry.get("name") or "").strip(),
            str(entry.get("tech") or "").strip(),
            str(entry.get("link") or "").strip(),
            _dates(entry),
        ]))
        items.append(EvidenceItem(source_id, "project_identity", identity, source_id))
        if entry.get("tech"):
            items.append(EvidenceItem(
                f"{source_id}.tech", "project_technology", str(entry["tech"]).strip(), source_id,
            ))
        for j, bullet in enumerate(entry.get("bullets_all") or entry.get("bullets") or []):
            if str(bullet).strip():
                items.append(EvidenceItem(
                    f"{source_id}.bullet.{j}", "project_bullet",
                    str(bullet).strip(), source_id,
                ))

    for i, entry in enumerate(master.get("education") or []):
        source_id = f"education.{i}"
        parts = [
            entry.get("school"), entry.get("degree"), entry.get("location"), _dates(entry),
            entry.get("gpa"), ", ".join(entry.get("coursework") or [])
            if isinstance(entry.get("coursework"), list) else entry.get("coursework"),
        ]
        items.append(EvidenceItem(
            source_id, "education", " | ".join(str(p).strip() for p in parts if p), source_id,
        ))

    for i, certification in enumerate(master.get("certifications") or []):
        if str(certification).strip():
            items.append(EvidenceItem(
                f"certification.{i}", "certification", str(certification).strip(), "certifications",
            ))

    for i, award in enumerate(master.get("awards") or []):
        if isinstance(award, dict):
            value = " | ".join(str(award.get(key) or "").strip() for key in ("name", "date", "description") if award.get(key))
        else:
            value = str(award).strip()
        if value:
            items.append(EvidenceItem(f"award.{i}", "award", value, "awards"))

    for i, story in enumerate(stories or []):
        source_id = f"story.{i}"
        text = "\n".join(filter(None, [
            str(story.get("title") or "").strip(),
            str(story.get("one_liner") or "").strip(),
            str(story.get("body") or "").strip(),
        ]))
        if text:
            items.append(EvidenceItem(source_id, "story", text, source_id))

    return items


def format_evidence_packet(
    ledger: list[EvidenceItem], evidence_ids: Iterable[str] | None = None,
    *, max_chars_per_item: int = 900,
) -> str:
    allowed = set(evidence_ids or [])
    selected = ledger if not allowed else [
        item for item in ledger if item.id in allowed
    ]
    return "\n".join(
        f"[{item.id}] ({item.kind}; {item.support}) {item.text[:max_chars_per_item]}"
        for item in selected
    )


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS and len(t) > 1}


def _relevance(item: EvidenceItem, job_text: str, job_title: str = "") -> tuple[int, int]:
    item_tokens = _tokens(item.text)
    title_tokens = _tokens(job_title)
    overlap = len(item_tokens & _tokens(job_text))
    overlap += 3 * len(item_tokens & title_tokens)
    overlap += 2 * sum(bool(item_tokens & family) and bool(title_tokens & family)
                       for family in _ROLE_FAMILIES)
    outcome_bonus = 1 if re.search(r"\d", item.text) else 0
    return overlap, outcome_bonus


def job_focus_text(job: dict) -> str:
    """Use requirements over company marketing copy for deterministic fallback."""
    description = str(job.get("description") or "")
    match = re.search(
        r"\b(?:what we are looking for in you|about you|requirements|qualifications|"
        r"what you(?:'|’)ll bring|who you are|must have)\b",
        description, re.IGNORECASE,
    )
    focus = description[match.end():] if match else description
    return " ".join([str(job.get("title") or ""), focus[:3000]])


def default_content_plan(master: dict, job: dict, ledger: list[EvidenceItem]) -> dict:
    """Conservative deterministic plan used when the planning model fails."""
    job_text = job_focus_text(job)
    job_title = str(job.get("title") or "")

    def select_sections(kind: str, cap: int, default_bullets: int) -> list[dict]:
        identities = [item for item in ledger if item.kind == f"{kind}_identity"]
        ranked: list[tuple[tuple[int, int], int, EvidenceItem, list[EvidenceItem]]] = []
        for order, identity in enumerate(identities):
            bullets = [
                item for item in ledger
                if item.source_id == identity.source_id and item.kind == f"{kind}_bullet"
            ]
            def bullet_score(item: EvidenceItem) -> tuple[int, int]:
                relevance, outcome = _relevance(item, job_text, job_title)
                source_position = int(item.id.rsplit(".", 1)[-1])
                return relevance + max(0, 7 - source_position), outcome

            bullets.sort(key=bullet_score, reverse=True)
            score = max((bullet_score(item) for item in bullets), default=(0, 0))
            if kind == "project":
                # Earlier projects in the master are usually the candidate's
                # curated showcase. A small tie-breaker keeps fallback output
                # from chasing generic JD vocabulary into old side projects.
                score = (score[0] + max(0, 2 - order), score[1])
                preferred = {str(name).casefold() for name in master.get("preferred_projects") or []}
                project_name = str((master.get("projects") or [])[order].get("name") or "").casefold()
                if project_name in preferred:
                    score = (score[0] + 6, score[1])
            ranked.append((score, order, identity, bullets))
        ranked.sort(key=lambda row: (-row[0][0], -row[0][1], row[1]))

        out = []
        for index, (_, _, identity, bullets) in enumerate(ranked[:cap]):
            target = min(default_bullets if index else default_bullets + 1, len(bullets), 5)
            target = max(1, target)
            chosen = bullets[:max(target + 1, 2)]
            out.append({
                "source_id": identity.source_id,
                "evidence_ids": [item.id for item in chosen] or [identity.id],
                "target_bullets": target,
                "highlight": index == 0,
                "reason": "Best deterministic overlap with the role.",
            })
        return out

    skills = [item for item in ledger if item.kind == "skill" and item.support == "direct"]
    skills.sort(key=lambda item: _relevance(item, job_text, job_title), reverse=True)
    selected_skills = []
    seen_skills: set[str] = set()
    for item in skills:
        label = item.text.split(":", 1)[-1].strip()
        if label.lower() in seen_skills:
            continue
        selected_skills.append({"skill": label, "evidence_ids": [item.id], "support": "direct"})
        seen_skills.add(label.lower())
        if len(selected_skills) >= 38:
            break

    summary_ids = [item.id for item in ledger if item.kind == "summary"][:1]
    if not summary_ids:
        summary_ids = [item.id for item in ledger if item.kind.endswith("_bullet")][:3]

    return {
        "role_strategy": "Lead with the strongest directly supported experience relevant to the role.",
        "requirements": [],
        "selected_experience": select_sections("experience", 3, 3),
        "selected_projects": select_sections("project", 2, 2),
        "selected_skills": selected_skills,
        "summary_evidence_ids": summary_ids,
        "ats_keywords": [],
    }


def normalize_content_plan(plan: object, master: dict, job: dict, ledger: list[EvidenceItem]) -> dict:
    """Validate model-selected IDs and fall back when a plan is incomplete."""
    fallback = default_content_plan(master, job, ledger)
    if not isinstance(plan, dict):
        return fallback
    valid_ids = {item.id for item in ledger}
    valid_sources = {item.source_id for item in ledger}
    direct_corpus = "\n".join(item.text for item in ledger if item.support == "direct")
    job_tokens = _tokens(" ".join([
        str(job.get("title") or ""), str(job.get("description") or ""),
    ]))

    def selections(key: str, prefix: str, cap: int) -> list[dict]:
        result = []
        for raw in plan.get(key) or []:
            if not isinstance(raw, dict):
                continue
            source_id = str(raw.get("source_id") or "")
            if source_id not in valid_sources or not source_id.startswith(prefix):
                continue
            ids = [str(value) for value in raw.get("evidence_ids") or [] if str(value) in valid_ids]
            ids = [value for value in ids if value == source_id or value.startswith(source_id + ".")]
            if not ids:
                continue
            result.append({
                "source_id": source_id,
                "evidence_ids": list(dict.fromkeys(ids)),
                "target_bullets": max(1, min(5, int(raw.get("target_bullets") or 2))),
                "highlight": bool(raw.get("highlight")),
                "reason": str(raw.get("reason") or "Selected for role relevance."),
            })
            if len(result) >= cap:
                break
        return result

    normalized = {
        "role_strategy": str(plan.get("role_strategy") or fallback["role_strategy"]),
        "requirements": [],
        "selected_experience": selections("selected_experience", "experience.", 3),
        "selected_projects": selections("selected_projects", "project.", 3),
        "selected_skills": [],
        "summary_evidence_ids": [
            str(value) for value in plan.get("summary_evidence_ids") or [] if str(value) in valid_ids
        ][:8],
        "ats_keywords": [str(value).strip() for value in plan.get("ats_keywords") or [] if str(value).strip()][:16],
    }

    for raw in plan.get("requirements") or []:
        if not isinstance(raw, dict):
            continue
        normalized["requirements"].append({
            "id": str(raw.get("id") or f"requirement.{len(normalized['requirements'])}"),
            "text": str(raw.get("text") or ""),
            "priority": max(1, min(5, int(raw.get("priority") or 3))),
            "evidence_ids": [str(v) for v in raw.get("evidence_ids") or [] if str(v) in valid_ids],
        })
        if len(normalized["requirements"]) >= 12:
            break

    adjacent_count = 0
    for raw in plan.get("selected_skills") or []:
        if not isinstance(raw, dict):
            continue
        ids = [str(v) for v in raw.get("evidence_ids") or [] if str(v) in valid_ids]
        support = str(raw.get("support") or "direct")
        skill = str(raw.get("skill") or "").strip()
        if not ids or not skill or support not in {"direct", "entailed", "adjacent"}:
            continue
        # A direct label must actually occur in direct source evidence. Models
        # sometimes call a plausible neighboring technology "direct" merely
        # because the job asks for it; downgrade that case instead of trusting
        # the label. Entailed and adjacent claims are reviewed semantically.
        if support == "direct" and not _grounded_skill(skill, direct_corpus.lower()):
            support = "adjacent"
        if support == "adjacent":
            # Adjacent knowledge is an ATS aid, not a general brainstorming
            # license: it must be requested by this job and is capped so it
            # cannot crowd out demonstrated skills.
            if not _tokens(skill) or not _tokens(skill).issubset(job_tokens):
                continue
            if adjacent_count >= 2:
                continue
            adjacent_count += 1
        normalized["selected_skills"].append({
            "skill": skill,
            "evidence_ids": ids,
            "support": support,
        })
        if len(normalized["selected_skills"]) >= 42:
            break

    # The source resume's core languages and other explicitly pinned skills
    # are a hard contract. Planner relevance cannot silently remove them.
    chosen = {row["skill"].casefold() for row in normalized["selected_skills"]}
    for skill in reversed(master.get("core_skills") or []):
        label = str(skill).strip()
        if not label or label.casefold() in chosen or not _grounded_skill(label, direct_corpus.lower()):
            continue
        evidence = next((item.id for item in ledger if item.kind == "skill" and item.support == "direct" and _grounded_skill(label, item.text.lower())), None)
        if evidence:
            normalized["selected_skills"].insert(0, {
                "skill": label, "evidence_ids": [evidence], "support": "direct",
            })
            chosen.add(label.casefold())

    # A resume with an established skills inventory should not collapse to a
    # dozen tokens because the model returned a short plan. The planner still
    # chooses the highest-priority skills; fill only to a modest breadth floor.
    breadth_floor = min(34, len(fallback["selected_skills"]))
    for row in fallback["selected_skills"]:
        direct_count = sum(item.get("support") == "direct" for item in normalized["selected_skills"])
        if direct_count >= breadth_floor:
            break
        label = row["skill"]
        if label.casefold() not in chosen:
            normalized["selected_skills"].append(row)
            chosen.add(label.casefold())

    for key in ("selected_experience", "selected_projects", "selected_skills", "summary_evidence_ids"):
        if not normalized[key]:
            normalized[key] = deepcopy(fallback[key])
    project_target = min(2, len([item for item in ledger if item.kind == "project_identity"]))
    for row in fallback["selected_projects"]:
        if len(normalized["selected_projects"]) >= project_target:
            break
        if not any(existing["source_id"] == row["source_id"] for existing in normalized["selected_projects"]):
            normalized["selected_projects"].append(deepcopy(row))
    return normalized


def selected_evidence_ids(plan: dict, ledger: list[EvidenceItem]) -> list[str]:
    ids: list[str] = []
    for key in ("selected_experience", "selected_projects"):
        for selection in plan.get(key) or []:
            ids.append(selection.get("source_id", ""))
            ids.extend(selection.get("evidence_ids") or [])
    for selection in plan.get("selected_skills") or []:
        ids.extend(selection.get("evidence_ids") or [])
    ids.extend(plan.get("summary_evidence_ids") or [])
    # Education is identity data, not an editorial claim. Always make it available.
    ids.extend(item.id for item in ledger if item.kind == "education")
    ids.extend(item.id for item in ledger if item.kind in {"certification", "award"})
    return list(dict.fromkeys(value for value in ids if value))


def _normal_role(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower().split("(")[0]).strip()


def _match_experience(entry: dict, master: dict) -> tuple[int, dict] | None:
    company = str(entry.get("company") or "").strip().lower()
    role = _normal_role(str(entry.get("role") or ""))
    for index, candidate in enumerate(master.get("experience") or []):
        if str(candidate.get("company") or "").strip().lower() != company:
            continue
        candidate_role = _normal_role(str(candidate.get("role") or ""))
        if role == candidate_role or role.startswith(candidate_role) or candidate_role.startswith(role):
            return index, candidate
    return None


def _match_project(entry: dict, master: dict) -> tuple[int, dict] | None:
    name = str(entry.get("name") or "").strip().lower()
    for index, candidate in enumerate(master.get("projects") or []):
        if str(candidate.get("name") or "").strip().lower() == name:
            return index, candidate
    return None


def _selected_source_bullets(source: dict, selection: dict) -> list[str]:
    pool = list(source.get("bullets_all") or source.get("bullets") or [])
    chosen = []
    for evidence_id in selection.get("evidence_ids") or []:
        match = re.search(r"\.bullet\.(\d+)$", str(evidence_id))
        if not match:
            continue
        index = int(match.group(1))
        if index < len(pool) and pool[index] not in chosen:
            chosen.append(pool[index])
    return chosen or pool


def _grounded_skill(skill: str, master_corpus: str) -> bool:
    lowered = skill.strip().lower()
    if not lowered:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])", master_corpus) is not None


_ADJACENT_QUALIFIER_RE = re.compile(
    r"\b(?:adjacent|familiar(?:ity)?|transferable|foundations?|related knowledge|exposure)\b",
    re.IGNORECASE,
)


def _matches_planned_skill(candidate: str, planned: dict, master_corpus: str) -> bool:
    """Accept a rendered skill only under the planner's declared support level."""
    label = str(planned.get("skill") or "").strip()
    support = str(planned.get("support") or "direct")
    if not label:
        return False
    if support == "direct":
        return candidate.casefold() == label.casefold() and _grounded_skill(label, master_corpus)
    if support == "entailed":
        return candidate.casefold() == label.casefold()
    if support != "adjacent" or not _ADJACENT_QUALIFIER_RE.search(candidate):
        return False
    return re.search(
        rf"(?<![a-z0-9]){re.escape(label.casefold())}(?![a-z0-9])",
        candidate.casefold(),
    ) is not None


def finalize_resume(draft: object, master: dict, plan: dict) -> dict:
    """Pin identities and source sections while preserving editorial bullets."""
    draft = deepcopy(draft) if isinstance(draft, dict) else {}
    selected_exp = {row["source_id"] for row in plan.get("selected_experience") or []}
    selected_projects = {row["source_id"] for row in plan.get("selected_projects") or []}

    experience = []
    seen_experience: set[int] = set()
    for entry in draft.get("experience") or []:
        if not isinstance(entry, dict):
            continue
        matched = _match_experience(entry, master)
        if not matched:
            continue
        index, source = matched
        if selected_exp and f"experience.{index}" not in selected_exp:
            continue
        # A writer can repeat a role or mislabel an older role at the same
        # employer. Never print two entries under one source identity.
        if index in seen_experience:
            continue
        bullets = [str(b).strip() for b in entry.get("bullets") or [] if str(b).strip()][:5]
        if not bullets:
            continue
        experience.append({
            "company": source.get("company", ""),
            "role": source.get("role", ""),
            "location": source.get("location", ""),
            "dates": _dates(source),
            "bullets": bullets,
            "_recency": _recency(source),
        })
        seen_experience.add(index)
    # A planned source role omitted or wrongly re-titled by the model gets a
    # conservative source-backed entry; identities are not editorial prose.
    for selection in plan.get("selected_experience") or []:
        try:
            index = int(selection["source_id"].split(".")[1])
            source = (master.get("experience") or [])[index]
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        if index in seen_experience:
            continue
        bullets = _selected_source_bullets(source, selection)
        experience.append({
            "company": source.get("company", ""), "role": source.get("role", ""),
            "location": source.get("location", ""), "dates": _dates(source),
            "bullets": bullets[:selection.get("target_bullets", 3)],
            "_recency": _recency(source),
        })
        seen_experience.add(index)
    experience.sort(key=lambda row: row["_recency"], reverse=True)
    for entry in experience:
        entry.pop("_recency", None)

    projects = []
    seen_projects: set[int] = set()
    for entry in draft.get("projects") or []:
        if not isinstance(entry, dict):
            continue
        matched = _match_project(entry, master)
        if not matched:
            continue
        index, source = matched
        if selected_projects and f"project.{index}" not in selected_projects:
            continue
        if index in seen_projects:
            continue
        bullets = [str(b).strip() for b in entry.get("bullets") or [] if str(b).strip()][:3]
        if not bullets:
            continue
        projects.append({
            "name": source.get("name", ""), "tech": source.get("tech", ""),
            "link": source.get("link", ""), "dates": _dates(source), "bullets": bullets,
            "_recency": _recency(source),
        })
    if not projects:
        for selection in plan.get("selected_projects") or []:
            try:
                index = int(selection["source_id"].split(".")[1])
                source = (master.get("projects") or [])[index]
            except (IndexError, KeyError, TypeError, ValueError):
                continue
            bullets = _selected_source_bullets(source, selection)
            projects.append({
                "name": source.get("name", ""), "tech": source.get("tech", ""),
                "link": source.get("link", ""), "dates": _dates(source),
                "bullets": bullets[:selection.get("target_bullets", 1)],
                "_recency": _recency(source),
            })

    # A model may omit a planned project despite the user asking for two.
    # Restore only a selected source project, never an unselected generic one.
    for selection in plan.get("selected_projects") or []:
        if len(projects) >= 2:
            break
        try:
            source = (master.get("projects") or [])[int(selection["source_id"].split(".")[1])]
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        if any(row["name"].casefold() == str(source.get("name") or "").casefold() for row in projects):
            continue
        projects.append({
            "name": source.get("name", ""), "tech": source.get("tech", ""),
            "link": source.get("link", ""), "dates": _dates(source),
            "bullets": _selected_source_bullets(source, selection)[:1],
            "_recency": _recency(source),
        })
    projects.sort(key=lambda row: row["_recency"], reverse=True)
    for entry in projects:
        entry.pop("_recency", None)

    master_corpus = "\n".join(
        item.text.lower() for item in build_evidence_ledger(master)
        if item.support != "adjacent"
    )
    planned_skills = [
        row for row in plan.get("selected_skills") or []
        if isinstance(row, dict) and str(row.get("skill") or "").strip()
    ]
    skills = []
    seen: set[str] = set()
    selected_direct = {
        str(row["skill"]).casefold() for row in planned_skills
        if row.get("support") == "direct" and _grounded_skill(str(row["skill"]), master_corpus)
    }
    for group_name, values in _skill_groups(master):
        kept = []
        for value in values:
            label = str(value).strip()
            if label.casefold() in selected_direct and label.casefold() not in seen:
                kept.append(label)
                seen.add(label.casefold())
        if kept:
            skills.append({"group": group_name, "items": kept})

    raw_skills = draft.get("skills") or []
    if isinstance(raw_skills, dict):
        raw_skills = [{"group": key, "items": value} for key, value in raw_skills.items()]
    for group in raw_skills:
        if not isinstance(group, dict):
            continue
        kept = []
        for skill in group.get("items") or []:
            skill = str(skill).strip()
            key = skill.lower()
            if key in seen or not any(
                planned.get("support") != "direct" and _matches_planned_skill(skill, planned, master_corpus)
                for planned in planned_skills
            ):
                continue
            seen.add(key)
            kept.append(skill)
        if kept:
            skills.append({"group": str(group.get("group") or "Skills"), "items": kept})

    # The writer may ignore a pinned skill even when the planner selected it.
    # Put it back in its source category, without granting a new skill claim.
    for core in master.get("core_skills") or []:
        label = str(core).strip()
        if not label or label.casefold() in seen or not _grounded_skill(label, master_corpus):
            continue
        source_group = next((group for group, values in _skill_groups(master)
                             if any(str(value).casefold() == label.casefold() for value in values)), "Core Skills")
        target = next((group for group in skills if group["group"].casefold() == source_group.casefold()), None)
        if target is None:
            target = {"group": source_group, "items": []}
            skills.append(target)
        target["items"].append(label)
        seen.add(label.casefold())

    education = []
    for source in sorted(master.get("education") or [], key=_recency, reverse=True)[:2]:
        education.append({
            "school": source.get("school", ""), "degree": source.get("degree", ""),
            "location": source.get("location", ""), "dates": _dates(source),
            "gpa": source.get("gpa", ""),
            "coursework": ", ".join(source.get("coursework") or [])
            if isinstance(source.get("coursework"), list) else source.get("coursework", ""),
            **({"minor": source["minor"]} if source.get("minor") else {}),
            **({"specializations": source["specializations"]} if source.get("specializations") else {}),
            **({"honors": source["honors"]} if source.get("honors") else {}),
        })

    summary = str(draft.get("summary") or "").strip()
    if not summary:
        summary = str((master.get("summary_options") or [""])[0]).strip()

    return {
        "summary": summary,
        "skills": skills,
        "experience": experience[:3],
        "projects": projects[:3],
        "education": education,
        "certifications": sorted(deepcopy(master.get("certifications") or []),
                                 key=lambda value: _recency({"date": str(value)}), reverse=True),
        "awards": sorted(deepcopy(master.get("awards") or []),
                         key=lambda value: _recency(value if isinstance(value, dict) else {"date": str(value)}),
                         reverse=True),
        "ats_keywords": [
            str(value).strip() for value in draft.get("ats_keywords") or plan.get("ats_keywords") or []
            if str(value).strip()
        ][:16],
    }
