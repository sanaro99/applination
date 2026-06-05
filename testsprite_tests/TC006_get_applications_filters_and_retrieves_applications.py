import requests

BASE_URL = "http://localhost:8000"
TIMEOUT = 30

def test_get_applications_filters_and_retrieves_applications():
    """
    Test GET /api/applications with optional run_id and status filters returns 200 with matching application array.
    If no applications exist, create a run and generate applications by triggering a dry_run, then test filtering.
    """
    try:
        # Step 1: Try GET /api/applications without filters
        resp = requests.get(f"{BASE_URL}/api/applications", timeout=TIMEOUT)
        assert resp.status_code == 200
        applications = resp.json()
        assert isinstance(applications, list)

        if not applications:
            # No applications exist, create a run first (dry_run to avoid side effects)
            run_resp = requests.post(
                f"{BASE_URL}/api/runs",
                json={"dry_run": True, "no_pdf": True, "no_cache": True},
                timeout=TIMEOUT,
            )
            assert run_resp.status_code == 200
            run_data = run_resp.json()
            run_id = run_data.get("id") or run_data.get("run_id") or run_data.get("runId")
            assert run_id is not None

            # We can't wait for the full pipeline or generated apps because dry_run: true disables that
            # So only assert the run creation contract here and then test GET /api/applications again

            apps_resp_after = requests.get(f"{BASE_URL}/api/applications", timeout=TIMEOUT)
            assert apps_resp_after.status_code == 200
            applications = apps_resp_after.json()
            assert isinstance(applications, list)

            if not applications:
                # No applications created by dry_run; unable to filter by run_id or status meaningfully
                # Just test that empty list is returned properly and exit test
                return

        # Collect a valid run_id and a valid status from existing applications if possible
        valid_run_id = None
        valid_status = None
        for app in applications:
            if "run_id" in app and app["run_id"]:
                valid_run_id = app["run_id"]
            if "status" in app and app["status"]:
                valid_status = app["status"]
            if valid_run_id and valid_status:
                break

        # Test filter by run_id
        if valid_run_id:
            resp_run_filter = requests.get(
                f"{BASE_URL}/api/applications", params={"run_id": valid_run_id}, timeout=TIMEOUT
            )
            assert resp_run_filter.status_code == 200
            filtered_apps = resp_run_filter.json()
            assert isinstance(filtered_apps, list)
            for a in filtered_apps:
                # run_id should match filter
                assert a.get("run_id") == valid_run_id

        # Test filter by status
        if valid_status:
            resp_status_filter = requests.get(
                f"{BASE_URL}/api/applications", params={"status": valid_status}, timeout=TIMEOUT
            )
            assert resp_status_filter.status_code == 200
            filtered_apps = resp_status_filter.json()
            assert isinstance(filtered_apps, list)
            for a in filtered_apps:
                # status should match filter
                assert a.get("status") == valid_status

        # Test filter by run_id and status combined if both available
        if valid_run_id and valid_status:
            resp_both_filter = requests.get(
                f"{BASE_URL}/api/applications",
                params={"run_id": valid_run_id, "status": valid_status},
                timeout=TIMEOUT,
            )
            assert resp_both_filter.status_code == 200
            filtered_apps = resp_both_filter.json()
            assert isinstance(filtered_apps, list)
            for a in filtered_apps:
                assert a.get("run_id") == valid_run_id
                assert a.get("status") == valid_status

    except requests.RequestException as e:
        assert False, f"Request failed: {e}"

test_get_applications_filters_and_retrieves_applications()