import requests
import sseclient
import time

BASE_URL = "http://localhost:3000"
HEADERS = {
    "Accept": "text/event-stream",
    "Content-Type": "application/json"
}
TIMEOUT = 30


def test_get_api_runs_id_stream_sse_events():
    # Step 1: Create a new run to get an active run id
    run_start_url = f"{BASE_URL}/api/runs"
    payload = {}  # Assuming no specific config required or minimal config; adjust if needed

    run_id = None
    try:
        resp = requests.post(run_start_url, json=payload, timeout=TIMEOUT)
        assert resp.status_code in (200, 201), f"Failed to start run, status: {resp.status_code}"
        run_data = resp.json()
        run_id = run_data.get("id")
        assert run_id, "Run ID missing in response"

        # Step 2: Subscribe to the SSE stream for the run
        stream_url = f"{BASE_URL}/api/runs/{run_id}/stream"
        with requests.get(stream_url, headers=HEADERS, stream=True, timeout=TIMEOUT) as stream_resp:
            assert stream_resp.status_code == 200, f"SSE stream connection failed: {stream_resp.status_code}"
            client = sseclient.SSEClient(stream_resp)

            received_stage_update = False
            received_job_progress = False
            stream_closed_correctly = False

            start_time = time.time()

            for event in client.events():
                data = event.data.strip()
                # Empty or heartbeat events should be ignored if present
                if not data or data == "ping":
                    continue

                # Parse event data assuming JSON format with stage and job progress info
                try:
                    event_json = event.data
                    parsed = None
                    try:
                        parsed = event.data if isinstance(event.data, dict) else event.data
                        import json
                        parsed = json.loads(event.data)
                    except Exception:
                        pass

                    # Check for live stage update keys
                    if parsed:
                        if "stage" in parsed:
                            received_stage_update = True
                        if "job" in parsed and "progress" in parsed:
                            received_job_progress = True
                        # Check if the run is in 'cancelled' or 'completed' final state
                        if parsed.get("status") in ("cancelled", "completed"):
                            stream_closed_correctly = True
                            break
                except Exception:
                    # If unable to parse, continue reading events
                    pass

                # Timeout after 25 seconds (within 30s total timeout)
                if time.time() - start_time > 25:
                    break

            # Assert we received live updates and stream closed properly after run ends
            assert received_stage_update or received_job_progress, "Did not receive live stage or job progress events"
            assert stream_closed_correctly, "Stream did not close properly on run cancellation or completion"

    finally:
        # Cleanup: attempt to cancel the run if active, then delete it if API supports it
        if run_id:
            try:
                # Cancel the run (assuming PUT with status update supported)
                cancel_url = f"{BASE_URL}/api/runs/{run_id}"
                cancel_resp = requests.put(cancel_url, json={"status": "cancelled"}, timeout=TIMEOUT)
                # Ignore response code here; best-effort cancellation

                # No explicit delete endpoint given; so skipping deletion
            except Exception:
                pass


test_get_api_runs_id_stream_sse_events()