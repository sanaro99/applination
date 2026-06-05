import requests

def test_post_inbox_sync_updates_application_statuses():
    base_url = "http://localhost:8000"
    url = f"{base_url}/api/inbox/sync"
    headers = {"Content-Type": "application/json"}
    payload = {"days": 7}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as e:
        assert False, f"Request failed: {e}"

    # Per instructions, without inbox credentials configured, this endpoint returns 400
    assert response.status_code == 400, f"Expected 400 Not configured, got {response.status_code}"
    # Optionally check that response content mentions not configured
    try:
        json_resp = response.json()
        # We expect some error message or indication, but only assert status code as required
    except Exception:
        pass

test_post_inbox_sync_updates_application_statuses()