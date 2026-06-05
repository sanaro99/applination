import requests

BASE_URL = "http://localhost:8000"
TIMEOUT = 30


def test_get_health_endpoint_returns_service_status():
    url = f"{BASE_URL}/api/health"
    try:
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        assert False, f"Request to {url} failed: {e}"

    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
    try:
        data = response.json()
    except ValueError:
        assert False, "Response body is not valid JSON"

    assert isinstance(data, dict), "Response JSON is not an object"
    assert "ok" in data, "Response JSON does not have 'ok' key"
    assert data["ok"] is True, f"Expected 'ok' to be True, got {data['ok']}"


test_get_health_endpoint_returns_service_status()