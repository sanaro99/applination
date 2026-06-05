import requests

BASE_URL = "http://localhost:8000"
TIMEOUT = 30

def test_get_runs_list_recent_runs():
    url = f"{BASE_URL}/api/runs"
    try:
        response = requests.get(url, timeout=TIMEOUT)
    except requests.RequestException as e:
        assert False, f"Request to {url} failed: {e}"

    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"

    try:
        runs = response.json()
    except ValueError:
        assert False, "Response is not valid JSON"

    assert isinstance(runs, list), f"Response JSON is not a list but {type(runs)}"

    # If there are 0 or 1 runs, ordering is trivially correct
    if len(runs) > 1:
        # Runs should be ordered from newest to oldest by a timestamp or id - try to identify ordering key
        # We check if runs have an 'id' or 'created_at' or 'start_time' field for ordering
        # Try common keys, fallback if missing
        def get_run_key(run):
            for k in ('created_at', 'start_time', 'id'):
                if k in run:
                    return run[k]
            return None

        keys = [get_run_key(run) for run in runs]
        # Only compare keys that are not None and comparable
        filtered_keys = [k for k in keys if k is not None]
        if len(filtered_keys) >= 2:
            # Check descending order (newest first)
            is_descending = all(
                filtered_keys[i] >= filtered_keys[i + 1] for i in range(len(filtered_keys) - 1)
            )
            assert is_descending, "Runs are not ordered from newest to oldest"

test_get_runs_list_recent_runs()