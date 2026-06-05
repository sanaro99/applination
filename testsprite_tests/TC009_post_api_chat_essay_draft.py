import requests

BASE_URL = "http://localhost:8000"
TIMEOUT = 30
HEADERS = {"Content-Type": "application/json"}


def test_post_api_chat_essay_draft():
    url = f"{BASE_URL}/api/chat/essay"

    # Test valid prompt with optional parameters
    payload_valid = {
        "prompt": "Describe your passion for software engineering.",
        "word_limit": 300,
        "instructions": "Focus on your experience and goals."
    }
    try:
        response = requests.post(url, json=payload_valid, headers=HEADERS, timeout=TIMEOUT)
        assert response.status_code == 200, f"Expected status 200 but got {response.status_code}"
        json_response = response.json()
        assert isinstance(json_response, dict), "Response should be a JSON object"
        assert "essay" in json_response or "draft" in json_response, "Response should include 'essay' or 'draft'"
        essay_content = json_response.get("essay") or json_response.get("draft")
        assert isinstance(essay_content, str) and len(essay_content.strip()) > 0, "Essay draft must be a non-empty string"
    except requests.RequestException as e:
        assert False, f"Request failed: {e}"

    # Test missing prompt returns error
    payload_missing_prompt = {
        # intentionally no "prompt" key
        "word_limit": 300,
        "instructions": "Focus on your experience and goals."
    }
    try:
        response = requests.post(url, json=payload_missing_prompt, headers=HEADERS, timeout=TIMEOUT)
        # Assuming API returns 400 or another 4xx for missing prompt
        assert response.status_code >= 400 and response.status_code < 500, (
            f"Expected client error status code for missing prompt but got {response.status_code}"
        )
        json_response = response.json()
        # Check error indication keys or messages
        error_keys = ["error", "message", "detail"]
        assert any(key in json_response for key in error_keys), "Error response should contain error message"
    except requests.RequestException as e:
        assert False, f"Request failed: {e}"


test_post_api_chat_essay_draft()
