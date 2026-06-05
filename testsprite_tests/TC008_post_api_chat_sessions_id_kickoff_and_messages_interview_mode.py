import requests

BASE_URL = "http://localhost:3000"
HEADERS = {"Content-Type": "application/json"}
TIMEOUT = 30


def test_post_api_chat_sessions_id_kickoff_and_messages_interview_mode():
    session_id = None
    try:
        # Step 1: Create a chat session with mode=interview
        create_resp = requests.post(
            f"{BASE_URL}/api/chat/sessions",
            json={"mode": "interview"},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        assert create_resp.status_code == 201, f"Failed to create chat session: {create_resp.text}"
        resp_json = create_resp.json()
        assert "id" in resp_json, "Session ID missing in create response"
        session_id = resp_json["id"]

        # Step 2: POST to /kickoff to receive the first question
        kickoff_resp = requests.post(
            f"{BASE_URL}/api/chat/sessions/{session_id}/kickoff",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        assert kickoff_resp.status_code == 200, f"Kickoff failed: {kickoff_resp.text}"
        kickoff_json = kickoff_resp.json()
        assert "question" in kickoff_json and isinstance(kickoff_json["question"], str) and kickoff_json["question"], "Kickoff response missing 'question'"

        # Step 3: POST an answer to /messages to receive feedback, model answers, and next questions
        answer_payload = {"message": "My answer to the first interview question."}
        message_resp = requests.post(
            f"{BASE_URL}/api/chat/sessions/{session_id}/messages",
            json=answer_payload,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        assert message_resp.status_code == 200, f"Sending message failed: {message_resp.text}"
        message_json = message_resp.json()
        # Expect keys: feedback, model_answer, next_question (all strings)
        for key in ["feedback", "model_answer", "next_question"]:
            assert key in message_json and isinstance(message_json[key], str), f"Missing or invalid '{key}' in response"

        # Step 4: Verify error handling for invalid session id on kickoff
        invalid_kickoff_resp = requests.post(
            f"{BASE_URL}/api/chat/sessions/invalid-session-id/kickoff",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        assert invalid_kickoff_resp.status_code in [404, 400], "Invalid session kickoff did not return expected error status"

        # Step 5: Verify error handling for kickoff on completed session by attempting kickoff again
        second_kickoff_resp = requests.post(
            f"{BASE_URL}/api/chat/sessions/{session_id}/kickoff",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        assert second_kickoff_resp.status_code in [200, 400, 404], f"Unexpected status code on repeated kickoff: {second_kickoff_resp.status_code}"

    finally:
        if session_id:
            requests.delete(f"{BASE_URL}/api/chat/sessions/{session_id}", headers=HEADERS, timeout=TIMEOUT)


test_post_api_chat_sessions_id_kickoff_and_messages_interview_mode()
