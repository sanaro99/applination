"""Bounded public source adapters, adapted from MIT-licensed Jobtracker.

See THIRD_PARTY_NOTICES.md. No personal filters or model calls live here.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import re
from urllib.parse import urlsplit

import requests

from src.scrapers.schema import Job, strip_html
from .identity import canonical_url, digest


@dataclass
class FetchResult:
    jobs: list[Job] = field(default_factory=list)
    complete: bool = False
    not_modified: bool = False
    validators: dict = field(default_factory=dict)


def _text(value):
    return strip_html(html.unescape(str(value or ''))).strip()


def _date(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')) if value else None
    except (ValueError, TypeError):
        return None


def _slug(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', value):
        raise ValueError('Invalid board slug')
    return value


def fetch_source(kind: str, params: dict, validators: dict | None = None, *, request=requests.request) -> FetchResult:
    validators = validators or {}
    name = params.get('name') or params.get('slug', '').replace('-', ' ').title()
    jobs = []
    detail_state = dict(validators.get('details') or {})
    detail_calls = 0

    def get(url, *, conditional=False, method='GET', **kwargs):
        headers = {'User-Agent': 'Applination/0.1 (job discovery)', 'Accept': 'application/json'}
        if conditional:
            if validators.get('etag'):
                headers['If-None-Match'] = validators['etag']
            if validators.get('modified'):
                headers['If-Modified-Since'] = validators['modified']
        headers.update(kwargs.pop('headers', {}))
        response = request(method, url, headers=headers, timeout=20, **kwargs)
        response.raise_for_status()
        return response

    def detail(job, url, parse):
        nonlocal detail_calls
        sig = digest([job.title, job.location, job.url])
        cached = detail_state.get(job.external_id) or {}
        checked = _date(cached.get('checked'))
        fresh = checked and (datetime.now(timezone.utc) - checked.replace(tzinfo=timezone.utc)).total_seconds() < 86400
        if detail_calls >= 10 or (fresh and cached.get('hash') == sig):
            return
        detail_calls += 1
        try:
            data = get(url).json()
            text = parse(data)
            if text:
                job.description = text
                detail_state[job.external_id] = {'checked': datetime.now(timezone.utc).isoformat(), 'hash': sig}
        except (requests.RequestException, ValueError, KeyError):
            # List metadata is still useful. Existing full descriptions survive
            # publication; failed detail calls are retried on a later tick.
            return

    if kind in {'ashby', 'greenhouse', 'lever', 'remotive', 'github'}:
        if kind == 'github':
            repo = params['repo']
            if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
                raise ValueError('Invalid GitHub repository')
            branch = _slug(params.get('branch', 'main'))
            url = f'https://raw.githubusercontent.com/{repo}/{branch}/README.md'
        elif kind == 'remotive':
            url = 'https://remotive.com/api/remote-jobs'
        else:
            slug = _slug(params['slug'])
            url = {'ashby': f'https://api.ashbyhq.com/posting-api/job-board/{slug}',
                   'greenhouse': f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true',
                   'lever': f'https://api.lever.co/v0/postings/{slug}?mode=json'}[kind]
        # Reparse cached community lists once after adding employment metadata.
        conditional = kind != 'github' or validators.get('parser_version') == 2
        r = get(url, conditional=conditional)
        if r.status_code == 304:
            return FetchResult(not_modified=True, validators=validators)
        meta = {k: v for k, v in {'etag': r.headers.get('ETag'), 'modified': r.headers.get('Last-Modified')}.items() if v}
        if kind == 'github':
            meta['parser_version'] = 2
            if not re.search(r'<t[dh]\b|\|\s*(?:company|name)\s*\|', r.text, re.I):
                raise ValueError('Unrecognized community list format')
            # Community README formats can change independently of their HTTP
            # status. An empty parse cannot establish that every job closed.
            parsed = parse_github_list(r.text, params['repo'])
            return FetchResult(parsed, complete=bool(parsed), validators=meta if parsed else {})
        data = r.json()
        if kind != 'lever' and (not isinstance(data, dict) or 'jobs' not in data):
            raise ValueError('Missing board postings field')
        items = data if kind == 'lever' else data['jobs']
        if not isinstance(items, list):
            raise ValueError('Unexpected source response')
        for item in items:
            if kind == 'ashby':
                title, loc = item.get('title', ''), item.get('location') or ''
                desc = item.get('descriptionPlain') or _text(item.get('descriptionHtml'))
                url = item.get('jobUrl') or item.get('applyUrl', '')
                typ, posted = item.get('employmentType', ''), item.get('publishedAt')
            elif kind == 'greenhouse':
                title, loc = item.get('title', ''), (item.get('location') or {}).get('name', '')
                desc, url = _text(item.get('content')), item.get('absolute_url', '')
                typ, posted = '', item.get('updated_at')
            elif kind == 'lever':
                title, loc = item.get('text', ''), (item.get('categories') or {}).get('location', '')
                desc = '\n'.join(filter(None, [item.get('descriptionPlain') or _text(item.get('description')),
                    *[_text(x.get('content')) for x in item.get('lists', [])], _text(item.get('additional'))]))
                url, typ, posted = item.get('hostedUrl') or item.get('applyUrl', ''), (item.get('categories') or {}).get('commitment', ''), None
            else:
                title, loc = item.get('title', ''), item.get('candidate_required_location', '')
                desc, url = _text(item.get('description')), item.get('url', '')
                typ, posted = item.get('job_type', ''), item.get('publication_date')
            if not title or not url:
                continue
            jobs.append(Job(f'{kind}:{params.get("slug", "")}', item.get('company_name') or name, title, str(loc), url,
                            desc, remote=bool(item.get('isRemote')) or kind == 'remotive' or 'remote' in str(loc).lower(),
                            external_id=str(item.get('id') or canonical_url(url)), employment_type=typ or '', posted_at=_date(posted)))
        return FetchResult(jobs, complete=len(jobs) == len(items), validators=meta)

    if kind == 'themuse':
        complete = False
        for page in range(5):
            data = get('https://www.themuse.com/api/public/jobs', params={'page': page, 'descending': 'true'}).json()
            if not isinstance(data.get('results'), list):
                raise ValueError('Missing Muse result list')
            for item in data.get('results', []):
                jobs.append(Job('themuse', (item.get('company') or {}).get('name', ''), item.get('name', ''),
                    ', '.join(x.get('name', '') for x in item.get('locations', [])), (item.get('refs') or {}).get('landing_page', ''),
                    _text(item.get('contents')), external_id=str(item['id']), posted_at=_date(item.get('publication_date'))))
            if not data.get('results') or page + 1 >= data.get('page_count', page + 2):
                complete = True
                break
        return FetchResult(jobs, complete=complete)

    if kind == 'himalayas':
        # Search windows are not authoritative full-board snapshots.
        for page in range(1, 4):
            data = get('https://himalayas.app/jobs/api/search', params={'q': params['query'], 'country': params.get('country', 'US'), 'sort': 'recent', 'page': page}).json()
            if not isinstance(data.get('jobs'), list):
                raise ValueError('Missing Himalayas job list')
            items = data.get('jobs', [])
            for item in items:
                locs = item.get('locationRestrictions') or []
                loc = ', '.join(str(x.get('name') or x.get('alpha2') or '') if isinstance(x, dict) else str(x) for x in locs)
                jobs.append(Job('himalayas', item.get('companyName', ''), item.get('title', ''), loc or 'Remote (worldwide)',
                    item.get('applicationLink', ''), _text(item.get('description')), remote=True,
                    external_id=str(item.get('guid') or item.get('applicationLink', '')), employment_type=item.get('employmentType') or ''))
            if not items:
                break
        return FetchResult(jobs)

    if kind == 'workday':
        slug, site, host = _slug(params['slug']), _slug(params['site']), params['host']
        if not re.fullmatch(r'[\w-]+\.wd\d+\.myworkdayjobs\.com', host):
            raise ValueError('Invalid Workday host')
        complete = False
        for offset in range(0, 100, 20):
            data = get(f'https://{host}/wday/cxs/{slug}/{site}/jobs', method='POST', json={'appliedFacets': {}, 'limit': 20, 'offset': offset, 'searchText': ''}).json()
            if not isinstance(data.get('jobPostings'), list):
                raise ValueError('Missing Workday posting list')
            items = data.get('jobPostings', [])
            for item in items:
                path = item.get('externalPath', '')
                loc = item.get('locationsText') or ''
                jobs.append(Job(f'workday:{slug}', name, item.get('title', ''), loc,
                    f'https://{host}/en-US/{site}{path}', _text(item.get('description')),
                    external_id=str(item.get('jobReqId') or (item.get('bulletFields') or [path])[0])))
                detail(jobs[-1], f'https://{host}/wday/cxs/{slug}/{site}{path}',
                       lambda data: _text((data.get('jobPostingInfo') or {}).get('jobDescription')))
            if len(items) < 20 or (data.get('total') and offset + len(items) >= data['total']):
                complete = True
                break
        return FetchResult(jobs, complete=complete, validators={'details': detail_state})

    if kind == 'smartrecruiters':
        slug = _slug(params['slug'])
        complete = False
        for offset in range(0, 500, 100):
            data = get(f'https://api.smartrecruiters.com/v1/companies/{slug}/postings', params={'limit': 100, 'offset': offset}).json()
            if not isinstance(data.get('content'), list):
                raise ValueError('Missing SmartRecruiters posting list')
            items = data.get('content', [])
            for item in items:
                loc = item.get('location') or {}
                jobs.append(Job(f'smartrecruiters:{slug}', name, item.get('name', ''),
                    ', '.join(str(loc.get(k) or '') for k in ('city', 'country')).strip(', '),
                    f'https://jobs.smartrecruiters.com/{slug}/{item["id"]}', '', external_id=str(item['id']), remote=bool(loc.get('remote'))))
                detail(jobs[-1], f'https://api.smartrecruiters.com/v1/companies/{slug}/postings/{item["id"]}',
                       lambda data: '\n'.join(_text(section.get('text')) for section in (data.get('jobAd', {}).get('sections') or {}).values() if isinstance(section, dict)))
            if not items or offset + len(items) >= data.get('totalFound', 0):
                complete = True
                break
        return FetchResult(jobs, complete=complete, validators={'details': detail_state})
    if kind in {'jsearch', 'adzuna'}:
        for page in range(1, 4):
            if kind == 'jsearch':
                data = get('https://jsearch.p.rapidapi.com/search', params={'query': params['query'], 'country': params.get('country', 'us'), 'page': page, 'num_pages': 1, 'date_posted': 'week'}).json()
                items = data.get('data', [])
                for item in items:
                    loc = ', '.join(filter(None, [item.get('job_city'), item.get('job_state'), item.get('job_country')]))
                    jobs.append(Job('jsearch', item.get('employer_name', ''), item.get('job_title', ''), loc,
                        item.get('job_apply_link') or item.get('job_google_link', ''), _text(item.get('job_description')),
                        external_id=str(item.get('job_id') or ''), remote=bool(item.get('job_is_remote')), employment_type=item.get('job_employment_type') or ''))
            else:
                country = params.get('country', 'us').lower()
                if not re.fullmatch('[a-z]{2}', country):
                    raise ValueError('Invalid country')
                data = get(f'https://api.adzuna.com/v1/api/jobs/{country}/search/{page}', params={'what': params['query'], 'results_per_page': 50, 'sort_by': 'date'}).json()
                items = data.get('results', [])
                for item in items:
                    jobs.append(Job('adzuna', (item.get('company') or {}).get('display_name', ''), _text(item.get('title')),
                        (item.get('location') or {}).get('display_name', ''), item.get('redirect_url', ''), _text(item.get('description')),
                        external_id=str(item.get('id', '')), employment_type=item.get('contract_time') or '', posted_at=_date(item.get('created'))))
            if not items:
                break
        return FetchResult(jobs)  # query/page caps cannot prove closure
    raise ValueError(f'Unsupported discovery source: {kind}')


def parse_github_list(text: str, repo: str) -> list[Job]:
    """Parse HTML and Markdown lists while preserving company carry-forward."""
    rows = [re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S | re.I) for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', text, re.S | re.I)]
    rows += [[c.strip() for c in line.strip().strip('|').split('|')] for line in text.splitlines() if line.startswith('|') and '---' not in line]
    company, jobs = '', {}
    for cells in rows:
        if len(cells) < 4:
            continue
        first = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', _text(cells[0])).strip()
        if first.casefold() in {'company', 'name'}:
            continue
        if first and not first.startswith(('↳', '↪')):
            company = first
        if not company or '🔒' in ''.join(cells):
            continue
        links = re.findall(r'href=["\'](https?://[^"\']+)', ' '.join(cells[3:]), re.I)
        links += re.findall(r'\]\((https?://[^)]+)\)', ' '.join(cells[3:]))
        url = next((html.unescape(u) for u in links if 'simplify.jobs/c/' not in u), '')
        if not url:
            continue
        title = _text(cells[1])
        key = digest(canonical_url(url))
        jobs[key] = Job(f'github:{repo}', company, title, _text(cells[2]), url, '', external_id=key,
                        remote='remote' in cells[2].lower(),
                        employment_type='internship' if 'internship' in repo.casefold() else '')
    return list(jobs.values())
