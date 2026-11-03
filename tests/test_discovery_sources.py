import pytest


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
