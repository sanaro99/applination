import requests
import datetime

BASE_URL = "http://localhost:8000"
TIMEOUT = 30

def test_patch_applications_runid_updates_application():
    # Helper function to get an existing application ID
    def get_existing_application_id():
        apps_resp = requests.get(
            f"{BASE_URL}/api/applications",
            timeout=TIMEOUT
        )
        assert apps_resp.status_code == 200, f"Failed to list applications: {apps_resp.text}"
        apps = apps_resp.json()
        assert isinstance(apps, list) and len(apps) > 0, "No applications found to test with"
        app_id = apps[0].get("id") or apps[0].get("app_id") or apps[0].get("application_id")
        assert app_id is not None, "Application ID is missing"
        return app_id

    app_id = None
    try:
        app_id = get_existing_application_id()

        patch_url = f"{BASE_URL}/api/applications/{app_id}"
        headers = {"Content-Type": "application/json"}

        # Prepare valid payload updating status, notes, tags, and deadline
        new_deadline = (datetime.datetime.utcnow() + datetime.timedelta(days=7)).date().isoformat()
        valid_payload = {
            "status": "applied",
            "notes": "Submitted application via test.",
            "tags": ["test", "automated"],
            "deadline": new_deadline
        }
        # PATCH with valid data - expect 200 and updated application with matching fields
        patch_resp = requests.patch(patch_url, json=valid_payload, headers=headers, timeout=TIMEOUT)
        assert patch_resp.status_code == 200, f"Valid patch failed: {patch_resp.text}"
        updated_app = patch_resp.json()
        # Validate updated fields presence and correctness
        assert updated_app.get("status") == valid_payload["status"], "Status not updated correctly"
        assert updated_app.get("notes") == valid_payload["notes"], "Notes not updated correctly"
        assert isinstance(updated_app.get("tags"), list), "Tags field missing or invalid"
        assert set(valid_payload["tags"]).issubset(set(updated_app.get("tags"))), "Tags not updated correctly"
        assert updated_app.get("deadline") == valid_payload["deadline"], "Deadline not updated correctly"

        # PATCH with invalid status - expect 422 validation error
        invalid_payload = {"status": "not_a_valid_status"}
        patch_resp_invalid = requests.patch(patch_url, json=invalid_payload, headers=headers, timeout=TIMEOUT)
        assert patch_resp_invalid.status_code == 422, f"Invalid status should return 422, got {patch_resp_invalid.status_code}"

        # PATCH on a non-existent application id - expect 404
        fake_app_id = "00000000-0000-0000-0000-000000000000"
        patch_resp_404 = requests.patch(f"{BASE_URL}/api/applications/{fake_app_id}", json=valid_payload, headers=headers, timeout=TIMEOUT)
        assert patch_resp_404.status_code == 404, f"Patching missing app should return 404, got {patch_resp_404.status_code}"

    finally:
        if app_id:
            pass

test_patch_applications_runid_updates_application()
