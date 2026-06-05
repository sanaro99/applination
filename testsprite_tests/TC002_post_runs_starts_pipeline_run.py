import requests

BASE_URL = "http://localhost:8000"
TIMEOUT = 30


def test_post_runs_starts_pipeline_run():
    url = f"{BASE_URL}/api/runs"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "dry_run": True,
        "no_pdf": False,
        "no_cache": False
    }

    response = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    assert response.status_code == 200, f"Expected status 200 but got {response.status_code}"

    data = response.json()
    # Validate required keys in the returned run record
    expected_keys = {"id", "status"}
    assert isinstance(data, dict), "Response data is not a dict"
    assert expected_keys.issubset(data.keys()), f"Response keys {data.keys()} missing expected keys {expected_keys}"

    # Validate type of fields (basic validation)
    assert isinstance(data["id"], int), "Run id is not an integer"
    assert isinstance(data["status"], str), "Run status is not a string"


test_post_runs_starts_pipeline_run()
