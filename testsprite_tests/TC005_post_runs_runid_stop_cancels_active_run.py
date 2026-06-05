import requests
import time

BASE_URL = "http://localhost:8000"
TIMEOUT = 30
HEADERS = {"Content-Type": "application/json"}


def test_post_runs_runid_stop_cancels_active_run():
    run_id = None

    # Helper function to create a run with dry_run set to False as stopping dry_run runs returns 422
    def create_run():
        url = f"{BASE_URL}/api/runs"
        payload = {"dry_run": False, "no_pdf": False, "no_cache": False}
        resp = requests.post(url, json=payload, headers=HEADERS, timeout=TIMEOUT)
        assert resp.status_code == 200, f"Create run failed: {resp.status_code} {resp.text}"
        run = resp.json()
        assert "id" in run, "Run response missing id"
        return run["id"]

    run_id = create_run()

    try:
        stop_url = f"{BASE_URL}/api/runs/{run_id}/stop"

        # Attempt to stop the active run - expecting 200 with updated run record
        stop_resp = requests.post(stop_url, headers=HEADERS, timeout=TIMEOUT)
        assert stop_resp.status_code == 200, f"Stop active run expected 200, got {stop_resp.status_code}"
        run_obj = stop_resp.json()
        assert "id" in run_obj and run_obj["id"] == run_id, "Response run id mismatch or missing"
        # Validate status or record indicates cancelled state or non-active
        assert "status" in run_obj, "Run record missing status"
        assert run_obj["status"] != "active", "Run status should not be active after stop"

        # Test stopping a missing run returns 404
        missing_run_id = 999999999
        missing_resp = requests.post(f"{BASE_URL}/api/runs/{missing_run_id}/stop", headers=HEADERS, timeout=TIMEOUT)
        assert missing_resp.status_code == 404, f"Stop missing run expected 404, got {missing_resp.status_code}"

        # Test stopping a non-active run returns 409
        # The stopped run is now non-active, try stopping it again
        second_stop_resp = requests.post(stop_url, headers=HEADERS, timeout=TIMEOUT)
        assert second_stop_resp.status_code == 409, f"Stop non-active run expected 409, got {second_stop_resp.status_code}"

    finally:
        pass


test_post_runs_runid_stop_cancels_active_run()
