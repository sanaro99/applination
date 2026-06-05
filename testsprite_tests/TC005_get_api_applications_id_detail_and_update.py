import requests
import uuid

BASE_URL = "http://localhost:3000"
TIMEOUT = 30
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def create_application():
    # Using the single job wizard APIs to create a valid application for testing
    extract_url = f"{BASE_URL}/api/single-job/extract"
    generate_url = f"{BASE_URL}/api/single-job/generate"

    job_url = "https://example.com/fake-job-url-for-testing"
    extract_payload = {"url": job_url}
    resp = requests.post(extract_url, json=extract_payload, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    # Assume extraction was successful if keys like company, title exist
    if not all(k in data for k in ["company", "title"]):
        raise RuntimeError("Failed to extract job data for test application creation")

    generate_payload = {
        "job": data,
        "overwrite": True
    }
    gen_resp = requests.post(generate_url, json=generate_payload, headers=HEADERS, timeout=TIMEOUT)
    gen_resp.raise_for_status()
    gen_data = gen_resp.json()
    application_id = gen_data.get("id") or gen_data.get("application_id")
    if not application_id:
        raise RuntimeError("Application ID missing in generation response")
    return application_id

def delete_application(app_id):
    url = f"{BASE_URL}/api/applications/{app_id}"
    try:
        response = requests.delete(url, timeout=TIMEOUT)
        # No assertion here because delete may not be supported, ignore failures silently
    except requests.RequestException:
        pass

def test_get_and_update_application_detail():
    app_id = None
    # Try-finally to clean up created application
    try:
        # Create application if no valid app_id provided
        app_id = create_application()

        get_url = f"{BASE_URL}/api/applications/{app_id}"
        put_url = get_url

        # 1. Test GET with valid id
        get_resp = requests.get(get_url, headers=HEADERS, timeout=TIMEOUT)
        assert get_resp.status_code == 200, f"Expected 200 OK but got {get_resp.status_code}"
        app_data = get_resp.json()
        # Validate required fields in application data
        assert "job" in app_data, "Response JSON missing 'job'"
        assert "status" in app_data, "Response JSON missing 'status'"
        assert "notes" in app_data, "Response JSON missing 'notes'"
        assert "artifacts" in app_data or "artifact_metadata" in app_data, "Response JSON missing artifact metadata"

        # 2. Test GET with invalid id returns 404 or error
        invalid_id = str(uuid.uuid4())
        invalid_get_url = f"{BASE_URL}/api/applications/{invalid_id}"
        invalid_resp = requests.get(invalid_get_url, headers=HEADERS, timeout=TIMEOUT)
        assert invalid_resp.status_code == 404 or invalid_resp.status_code >= 400, (
            f"Expected 404 or error status for invalid id, got {invalid_resp.status_code}"
        )

        # 3. Test GET with missing id (empty string) - expect 404 or error
        missing_id_url = f"{BASE_URL}/api/applications/"
        missing_resp = requests.get(missing_id_url, headers=HEADERS, timeout=TIMEOUT)
        assert missing_resp.status_code == 404 or missing_resp.status_code >= 400, (
            f"Expected 404 or error status for missing id URL, got {missing_resp.status_code}"
        )

        # 4. Test PUT update notes and status successfully returns 200
        update_payload = {
            "notes": "Updated notes for testing",
            "status": "In Progress"
        }
        put_resp = requests.put(put_url, json=update_payload, headers=HEADERS, timeout=TIMEOUT)
        assert put_resp.status_code == 200, f"Expected 200 OK on update but got {put_resp.status_code}"

        updated_data = put_resp.json()
        assert updated_data.get("notes") == update_payload["notes"], "Notes not updated correctly"
        assert updated_data.get("status") == update_payload["status"], "Status not updated correctly"

    finally:
        if app_id:
            delete_application(app_id)

test_get_and_update_application_detail()