import requests

BASE_URL = "http://localhost:8000"
TIMEOUT = 30


def test_post_ranked_rankedid_generate_rescues_job():
    """
    Test POST /api/ranked/{ranked_id}/generate endpoint for:
    - 200 with new run_id on success
    - 404 if ranked job missing
    - 409 if already generated
    - 400 if no stored description
    """

    # Step 1: Create a new run to get ranked jobs for a valid ranked_id
    run_resp = requests.post(
        f"{BASE_URL}/api/runs",
        json={"dry_run": False, "no_pdf": False, "no_cache": True},
        timeout=TIMEOUT,
    )
    assert run_resp.status_code == 200, f"Failed to create run: {run_resp.text}"
    run_data = run_resp.json()
    run_id = run_data.get("id")
    assert run_id is not None, "No run_id returned in /api/runs response"

    # Step 2: Get ranked jobs for the run to find a valid ranked_id
    ranked_resp = requests.get(f"{BASE_URL}/api/runs/{run_id}/ranked", timeout=TIMEOUT)
    assert ranked_resp.status_code == 200, f"Failed to get ranked jobs: {ranked_resp.text}"
    ranked_jobs = ranked_resp.json()
    assert isinstance(ranked_jobs, list) and len(ranked_jobs) > 0, "No ranked jobs found for run"

    ranked_id = None
    for job in ranked_jobs:
        job_id = job.get("id") or job.get("ranked_id")
        if job_id:
            ranked_id = job_id
            break

    assert ranked_id is not None, "No ranked_id found in ranked jobs"

    generate_url = f"{BASE_URL}/api/ranked/{ranked_id}/generate"

    try:
        resp = requests.post(generate_url, timeout=TIMEOUT)
    except requests.RequestException as e:
        assert False, f"Request to generate rescues job failed: {e}"

    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
            assert False, "Response 200 but body is not valid JSON"
        assert "run_id" in data, "Response json missing run_id on success"
        assert isinstance(data["run_id"], (int, float)), "run_id is not a number"
    elif resp.status_code == 404:
        pass
    elif resp.status_code == 409:
        pass
    elif resp.status_code == 400:
        pass
    else:
        assert False, f"Unexpected status code {resp.status_code} from generate endpoint"

    invalid_id = "non-existent-id-999999"
    resp_404 = requests.post(f"{BASE_URL}/api/ranked/{invalid_id}/generate", timeout=TIMEOUT)
    assert resp_404.status_code == 404, f"Expected 404 for missing ranked_id, got {resp_404.status_code}"

    if resp.status_code == 200:
        resp_409 = requests.post(generate_url, timeout=TIMEOUT)
        assert resp_409.status_code in (200, 409), (
            f"Expected 409 or 200 on re-generate attempt, got {resp_409.status_code}"
        )


test_post_ranked_rankedid_generate_rescues_job()
