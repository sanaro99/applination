import requests

BASE_URL = "http://localhost:3000"
TIMEOUT = 30
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def test_get_api_onboarding_status_and_post_complete():
    # Step 1: GET /api/onboarding/status to check current state
    try:
        response_status = requests.get(f"{BASE_URL}/api/onboarding/status", headers=HEADERS, timeout=TIMEOUT)
        assert response_status.status_code == 200, f"Expected 200 but got {response_status.status_code}"
        data = response_status.json()
        # Validate expected fields in status response
        assert isinstance(data, dict), "Response JSON is not an object"
        assert "completed" in data, "'completed' field missing in status response"
        assert "can_run" in data, "'can_run' field missing in status response"
        assert isinstance(data["completed"], bool), "'completed' field is not boolean"
        assert isinstance(data["can_run"], bool), "'can_run' field is not boolean"
    except Exception as e:
        raise AssertionError(f"GET /api/onboarding/status failed: {e}")

    # Step 2: POST /api/onboarding/complete with missing required fields to verify error responses
    incomplete_payloads = [
        {},  # completely empty
        {"provider": {}},  # missing contact, resume, search_setup
        {"contact": {}},  # missing provider, resume, search_setup
        {"provider": {}, "contact": {}},  # missing resume, search_setup
        {"provider": {}, "contact": {}, "resume": {}},  # missing search_setup
    ]
    for payload in incomplete_payloads:
        try:
            response_post = requests.post(
                f"{BASE_URL}/api/onboarding/complete", json=payload, headers=HEADERS, timeout=TIMEOUT
            )
            assert response_post.status_code >= 400, (
                f"Expected error status for incomplete payload, got {response_post.status_code} with payload {payload}"
            )
        except Exception as e:
            raise AssertionError(f"POST /api/onboarding/complete with incomplete payload failed: {e}")

    # Step 3: POST valid /api/onboarding/complete to confirm onboarding completion
    valid_payload = {
        "provider": {
            "key": "test-provider-key",
            "name": "test-provider"
        },
        "contact": {
            "name": "John Doe",
            "email": "johndoe@example.com",
            "phone": "+1234567890"
        },
        "resume": {
            "summary": "Experienced software engineer with a focus on backend development",
            "skills": ["Python", "FastAPI", "SQL", "Docker"],
            "experience": [
                {
                    "company": "ExampleCorp",
                    "position": "Software Engineer",
                    "start_date": "2020-01-01",
                    "end_date": "2023-01-01",
                    "description": "Developed backend services and APIs"
                }
            ],
            "education": [
                {
                    "school": "University of Examples",
                    "degree": "B.Sc. Computer Science",
                    "start_date": "2015-09-01",
                    "end_date": "2019-06-01"
                }
            ]
        },
        "search_setup": {
            "job_titles": ["Software Engineer", "Backend Developer"],
            "locations": ["Remote", "New York, NY"],
            "salary_range": {"min": 70000, "max": 120000},
            "keywords": ["Python", "API", "Cloud"]
        }
    }

    try:
        response_complete = requests.post(
            f"{BASE_URL}/api/onboarding/complete", json=valid_payload, headers=HEADERS, timeout=TIMEOUT
        )
        assert response_complete.status_code == 200, f"Expected 200 but got {response_complete.status_code}"
        complete_data = response_complete.json()
        assert isinstance(complete_data, dict), "Response JSON is not an object"
        # Validate if onboarding is confirmed complete and can_run is true in response if provided
        if "completed" in complete_data:
            assert complete_data["completed"] is True, "'completed' field expected to be True after completion"
        if "can_run" in complete_data:
            assert complete_data["can_run"] is True, "'can_run' field expected to be True after completion"
    except Exception as e:
        raise AssertionError(f"POST /api/onboarding/complete with valid payload failed: {e}")

    # Step 4: GET /api/onboarding/status again to verify updated onboarding status
    try:
        response_status_after = requests.get(f"{BASE_URL}/api/onboarding/status", headers=HEADERS, timeout=TIMEOUT)
        assert response_status_after.status_code == 200, f"Expected 200 but got {response_status_after.status_code}"
        data_after = response_status_after.json()
        assert isinstance(data_after, dict), "Response JSON is not an object"
        # After completion onboarding should be completed and can_run true
        assert data_after.get("completed") is True, "'completed' field expected to be True after onboarding"
        assert data_after.get("can_run") is True, "'can_run' field expected to be True after onboarding"
    except Exception as e:
        raise AssertionError(f"GET /api/onboarding/status after completion failed: {e}")


test_get_api_onboarding_status_and_post_complete()