"""Deterministic matching; no provider imports or network calls."""
import re

from src.profile import derive_profile, role_is_above_level
from src.scrapers.schema import Job
from src.target_rules import allows_job, matches_keywords, role_keywords


def score_job(job: Job, search: dict, master: dict) -> tuple[int, str] | None:
    keywords = role_keywords(search)
    if not allows_job(job, search) or not matches_keywords(job.title, keywords):
        return None
    if role_is_above_level(job.title, derive_profile(master)):
        return None
    skills = list(dict.fromkeys(str(skill).strip() for group in (master.get('skills') or {}).values()
                               for skill in (group if isinstance(group, list) else []) if str(skill).strip()))
    text = f'{job.title}\n{job.description}'.casefold()
    matched = [skill for skill in skills if re.search(r'(?<![\w+#])' + re.escape(skill.casefold()) + r'(?![\w+#])', text)]
    score = min(100, 50 + round(40 * len(matched) / max(1, min(len(skills), 10))) + (10 if job.description else 0))
    reason = 'Matches saved role and location preferences.'
    if matched:
        reason += ' Skills found: ' + ', '.join(matched[:8]) + '.'
    if not job.description:
        reason += ' Full description not yet available.'
    return score, reason
