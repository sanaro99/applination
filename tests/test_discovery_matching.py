from src.scrapers.schema import Job


def test_identity_preserves_namespaces_and_metadata_changes():
    from src.discovery.identity import posting_key, fingerprint
    a = Job('greenhouse:a', 'Acme', 'Engineer', 'Seattle', 'https://a/jobs/1', 'Python')
    b = Job('greenhouse:b', 'Acme', 'Engineer', 'Seattle', 'https://a/jobs/1', 'Python')
    a.external_id = b.external_id = '1'
    assert posting_key(a) != posting_key(b)
    old = fingerprint(a)
    a.location = 'New York'
    assert fingerprint(a) != old


def test_matching_uses_rules_and_word_boundaries_without_ai():
    from src.discovery.matching import score_job
    job = Job('ashby', 'Acme', 'Software Engineer', 'Seattle', 'https://a/1', 'Requirements: Python, SQL and JavaScript')
    master = {'skills': {'Languages': ['Python', 'Java', 'SQL']}}
    search = {'job_type': 'full_time', 'keywords': ['software engineer'], 'onsite_cities': ['Seattle']}
    result = score_job(job, search, master)
    assert result is not None
    assert 'Python' in result[1] and 'SQL' in result[1]
    assert 'Java,' not in result[1] and 'Java ' not in result[1]
    job.title = 'Staff Software Engineer'
    master['profile'] = {'seniority': 'student'}
    assert score_job(job, search, master) is None
    job.title = 'Software Engineer'
    job.location = 'London'
    assert score_job(job, search, master) is None


def test_distinct_same_title_requisitions_are_not_collapsed():
    from src.discovery.identity import posting_key
    a = Job('ashby:acme', 'Acme', 'Engineer', 'Seattle', 'https://a/1', 'Python', external_id='1')
    b = Job('ashby:acme', 'Acme', 'Engineer', 'London', 'https://a/2', 'Python', external_id='2')
    assert posting_key(a) != posting_key(b)
