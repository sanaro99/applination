import requests

BASE_URL = "http://localhost:3000"
TIMEOUT = 30
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def test_post_api_runs_start_pipeline_run():
    """Test starting a pipeline run with valid and invalid configurations"""

    # Valid configuration payload (example based on plausible config)
    valid_payload = {
        "config": {
            "pipeline": "default",
            "parameters": {
                "job_search": True,
                "resume_generation": True,
                "application_tracking": True
            }
        }
    }
    # Invalid configuration payload: missing prerequisites or malformed
    invalid_payloads = [
        {},  # empty payload
        {"config": {}},  # missing required fields inside config
        {"config": {"pipeline": ""}},  # empty pipeline name
        {"config": {"parameters": {}}},  # missing pipeline field
    ]

    # Send valid pipeline run start request
    try:
        response = requests.post(
            f"{BASE_URL}/api/runs",
            headers=HEADERS,
            json=valid_payload,
            timeout=TIMEOUT,
        )
        assert response.status_code in (200, 201), f"Valid run start failed with status {response.status_code}"
        data = response.json()
        # Validate run metadata presence (id and status are expected keys)
        assert isinstance(data, dict), "Response JSON is not a dict"
        assert "id" in data and data["id"], "Missing run id in response"
        assert "status" in data and isinstance(data["status"], str), "Missing or invalid status in response"
    except Exception as e:
        assert False, f"Exception during valid run start: {e}"

    # Test invalid payloads return error responses
    for invalid_payload in invalid_payloads:
        try:
            resp = requests.post(
                f"{BASE_URL}/api/runs",
                headers=HEADERS,
                json=invalid_payload,
                timeout=TIMEOUT,
            )
            # Expecting error response, typically 4xx (e.g. 400 Bad Request)
            assert resp.status_code >= 400 and resp.status_code < 500, (
                f"Invalid payload did not return client error status, got {resp.status_code}"
            )
            # Optionally check error message in response body
            try:
                err_data = resp.json()
                # Error response expected to be dict with error details or message
                assert isinstance(err_data, dict), "Error response is not a JSON object"
                assert ("error" in err_data or "message" in err_data), "No 'error' or 'message' key in error response"
            except Exception:
                # If not JSON, just pass for error response validation
                pass
        except Exception as e:
            assert False, f"Exception during invalid payload test: {e}"


test_post_api_runs_start_pipeline_run()
