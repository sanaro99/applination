import pytest


def test_internship_list_metadata_blocks_generic_titles_for_full_time():
    from src.discovery.sources import parse_github_list
    from src.discovery.matching import score_job
    text = '| Acme | Software Engineer | US | [Apply](https://a/1) |'
    job = parse_github_list(text, 'SimplifyJobs/Summer2026-Internships')[0]
    assert job.employment_type == 'internship'
    assert score_job(job, {'job_type': 'full_time', 'keywords': ['software engineer']}, {}) is None


def test_github_reparses_old_validators_once_for_employment_metadata():
    from src.discovery.sources import fetch_source
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs['headers'])
        response = Response(text='| Company | Role | Location | Application |\n| Acme | Engineer | US | [Apply](https://a/1) |')
        response.headers = {'ETag': 'v1'}
        return response
    params = {'repo': 'SimplifyJobs/Summer2026-Internships', 'branch': 'dev'}
    first = fetch_source('github', params, {'etag': 'v1'}, request=request)
    assert 'If-None-Match' not in calls[0]
    assert first.jobs[0].employment_type == 'internship'
    fetch_source('github', params, first.validators, request=request)
    assert calls[1]['If-None-Match'] == 'v1'


class Response:
    status_code = 200
    headers = {}
    def __init__(self, data=None, text='', status=200):
        self.data, self.text, self.status_code = data, text, status
    def json(self):
        return self.data
    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError('HTTP error')


def test_ashby_returns_full_jd_and_conditional_metadata():
    from src.discovery.sources import fetch_source
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        r = Response({'jobs': [{'id': '1', 'title': 'Engineer', 'location': 'Seattle',
                               'jobUrl': 'https://jobs.ashbyhq.com/acme/1', 'descriptionHtml': '<p>Python engineer</p>', 'employmentType': 'FullTime'}]})
        r.headers = {'ETag': 'v2'}
        return r
    result = fetch_source('ashby', {'slug': 'acme'}, {'etag': 'v1'}, request=request)
    assert result.complete and result.jobs[0].description == 'Python engineer'
    assert result.validators['etag'] == 'v2'
    assert calls[0][2]['headers']['If-None-Match'] == 'v1'


def test_conditional_304_and_bad_slug():
    from src.discovery.sources import fetch_source
    assert fetch_source('greenhouse', {'slug': 'acme'}, {}, request=lambda *a, **k: Response(status=304)).not_modified
    with pytest.raises(ValueError):
        fetch_source('ashby', {'slug': '../localhost'}, {})


def test_github_list_preserves_requisitions_and_closed_company_carryover():
    from src.discovery.sources import parse_github_list
    text = '''| Company | Role | Location | Application |
| --- | --- | --- | --- |
| Acme | Engineer | Seattle | [Apply](https://a/1) |
| ↳ | Engineer | London | [Apply](https://a/2) |
| Other | Closed 🔒 | US | no |
| ↳ | Engineer | US | [Apply](https://b/3) |'''
    jobs = parse_github_list(text, 'test')
    assert len(jobs) == 3 and jobs[2].company == 'Other'
    assert jobs[0].external_id != jobs[1].external_id
    assert not jobs[0].description


def test_workday_page_cap_is_incomplete_not_an_empty_authoritative_snapshot():
    from src.discovery.sources import fetch_source
    result = fetch_source('workday', {'slug': 'acme', 'host': 'acme.wd1.myworkdayjobs.com', 'site': 'External'}, {},
                          request=lambda *a, **k: Response({'total': 10000, 'jobPostings': [
                              {'title': 'Engineer', 'externalPath': f'/job/{i}', 'bulletFields': [str(i)]} for i in range(20)]}))
    assert result.jobs and not result.complete


def test_malformed_board_and_unrecognized_community_format_are_not_authoritative():
    from src.discovery.sources import fetch_source
    with pytest.raises(ValueError):
        fetch_source('ashby', {'slug': 'acme'}, {}, request=lambda *a, **k: Response({}))
    with pytest.raises(ValueError):
        fetch_source('github', {'repo': 'acme/jobs'}, {}, request=lambda *a, **k: Response(text='Temporarily unavailable'))
    result = fetch_source('ashby', {'slug': 'acme'}, {}, request=lambda *a, **k: Response({'jobs': [
        {'id': '1', 'title': 'Engineer', 'jobUrl': 'https://a/1'}, {'id': '2', 'title': 'Missing URL'}]}))
    assert not result.complete
    empty = fetch_source('github', {'repo': 'acme/jobs'}, {}, request=lambda *a, **k: Response(text='<table><tr><td>Format changed</td></tr></table>'))
    assert not empty.complete and not empty.validators
