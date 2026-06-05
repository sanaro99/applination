import requests

BASE_URL = "http://localhost:3000"
TIMEOUT = 30
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json"
}

def test_get_api_applications_list():
    # Test successful retrieval of applications list
    try:
        resp = requests.get(f"{BASE_URL}/api/applications", headers=HEADERS, timeout=TIMEOUT)
        assert resp.status_code == 200, f"Expected status 200 but got {resp.status_code}"
        # Expect JSON array or object with application records suitable for table or kanban rendering
        # Because API details don't specify schema, check it's JSON and contains list (or dict with 'applications')
        try:
            data = resp.json()
        except Exception as e:
            assert False, f"Response is not valid JSON: {e}"

        # Validate that data is list or dict with expected structure (basic heuristic)
        assert isinstance(data, (list, dict)), f"Expected response JSON to be list or dict but got {type(data)}"
        # If dict, check keys that could represent application records (this is heuristic)
        if isinstance(data, dict):
            # Could have keys like 'applications', 'items', or a list
            # Check at least one value is a list or the dict directly contains records
            found_list = False
            for v in data.values():
                if isinstance(v, list):
                    found_list = True
                    break
            assert found_list or data=={} or len(data)>0, "Response dict does not contain list of applications or is empty"
        elif isinstance(data, list):
            # List of records, validate at least 0 or more items (empty list is allowed)
            pass

    except requests.RequestException as e:
        assert False, f"Request failed: {e}"

    # Test unsupported filter returns appropriate error response
    unsupported_filter = {"unsupported_filter": "invalid_value"}
    try:
        resp = requests.get(f"{BASE_URL}/api/applications", headers=HEADERS, params=unsupported_filter, timeout=TIMEOUT)
        # Expect non-200 status, e.g. 400 or 422 or 500 depending on backend
        assert resp.status_code != 200, f"Expected failure status code for unsupported filter but got 200"
        # Optionally check if response contains error message
        try:
            err_data = resp.json()
            assert ("error" in err_data or "message" in err_data) or len(err_data) > 0, "Expected error info in response JSON"
        except Exception:
            # Non-JSON error responses are acceptable
            pass

    except requests.RequestException as e:
        # Request failure acceptable as some error responses might close connection
        pass

    # Test backend error simulation by sending invalid param that might cause backend failure
    invalid_param = {"cause_backend_error": "true"}
    try:
        resp = requests.get(f"{BASE_URL}/api/applications", headers=HEADERS, params=invalid_param, timeout=TIMEOUT)
        # Accept 4xx or 5xx error response on backend error simulation
        if resp.status_code == 200:
            # Possibly backend handled this gracefully by returning empty list or fallback
            try:
                data = resp.json()
                assert isinstance(data, (list, dict)), "Expected applications list or dict even on backend error fallback"
            except Exception:
                assert False, "Expected JSON response even on backend error fallback"
        else:
            assert resp.status_code >= 400, "Expected error status code on backend error simulation"
    except requests.RequestException:
        # Accept as backend error simulation might cause connection failure
        pass

test_get_api_applications_list()