import requests

BASE_URL = "http://localhost:3000"
HEADERS = {"Content-Type": "application/json"}
TIMEOUT = 30

def test_post_api_chat_sessions_create_and_message():
    session_id = None
    try:
        # 1. Create a new chat session with valid grounding data (assuming minimal grounding data required)
        grounding_data = {
            "grounding": {
                "bio": "Experienced software developer with a background in test automation.",
                "resume": "Worked extensively in Python, API testing, and automation frameworks."
            }
        }
        create_resp = requests.post(
            f"{BASE_URL}/api/chat/sessions",
            json=grounding_data,
            headers=HEADERS,
            timeout=TIMEOUT
        )
        assert create_resp.status_code == 201, f"Expected 201, got {create_resp.status_code}"
        create_json = create_resp.json()
        assert "id" in create_json, "Response missing session id"
        session_id = create_json["id"]

        # 2. Send a message to the created session and expect a grounded assistant response
        message_payload = {
            "message": "Can you help me prepare for my upcoming job interview?"
        }
        msg_resp = requests.post(
            f"{BASE_URL}/api/chat/sessions/{session_id}/messages",
            json=message_payload,
            headers=HEADERS,
            timeout=TIMEOUT
        )
        assert msg_resp.status_code == 200, f"Expected 200, got {msg_resp.status_code}"
        msg_json = msg_resp.json()
        # Check typical keys for grounded assistant response, e.g. "response" field and grounding reference
        assert "response" in msg_json, "Response missing assistant's reply"
        assert isinstance(msg_json["response"], str) and len(msg_json["response"]) > 0, "Empty assistant response"

        # 3. Test error handling for invalid grounding data on session creation
        invalid_grounding = {"grounding": "invalid_string_instead_of_object"}
        err_resp = requests.post(
            f"{BASE_URL}/api/chat/sessions",
            json=invalid_grounding,
            headers=HEADERS,
            timeout=TIMEOUT
        )
        # Expecting error status, usually 400 or 422
        assert err_resp.status_code >= 400, f"Expected error status >=400, got {err_resp.status_code}"
        err_json = err_resp.json()
        # Expect some error message or indication of invalid grounding
        assert ("error" in err_json) or ("message" in err_json), "Error response missing error details"

    finally:
        # Cleanup: delete the created chat session if session_id was assigned
        if session_id:
            try:
                requests.delete(
                    f"{BASE_URL}/api/chat/sessions/{session_id}",
                    timeout=TIMEOUT
                )
            except Exception:
                pass

test_post_api_chat_sessions_create_and_message()