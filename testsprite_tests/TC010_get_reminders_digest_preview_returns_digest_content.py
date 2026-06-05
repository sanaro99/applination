import requests

BASE_URL = "http://localhost:8000"
TIMEOUT = 30


def test_get_reminders_digest_preview_returns_digest_content():
    url = f"{BASE_URL}/api/reminders/digest/preview"
    try:
        response = requests.get(url, timeout=TIMEOUT)
    except requests.RequestException as e:
        assert False, f"Request to {url} failed: {e}"

    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"

    try:
        body = response.json()
    except ValueError:
        assert False, "Response is not valid JSON"

    # Validate presence and type of expected fields
    expected_fields = {
        "subject": str,
        "html": str,
        "text": str,
        "empty": bool,
    }

    for field, field_type in expected_fields.items():
        assert field in body, f"Response JSON missing required field '{field}'"
        assert isinstance(body[field], field_type), f"Field '{field}' expected to be {field_type.__name__}, got {type(body[field]).__name__}"


test_get_reminders_digest_preview_returns_digest_content()