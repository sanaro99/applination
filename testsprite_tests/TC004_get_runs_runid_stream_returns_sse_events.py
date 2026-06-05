import requests

BASE_URL = "http://localhost:8000"
TIMEOUT = 30

def test_get_runs_runid_stream_returns_sse_events():
    run = None
    try:
        # Create a new run with dry_run to avoid real side effects
        post_resp = requests.post(
            f"{BASE_URL}/api/runs",
            json={"dry_run": True, "no_pdf": True, "no_cache": True},
            timeout=TIMEOUT
        )
        assert post_resp.status_code == 200, f"Expected 200, got {post_resp.status_code}"
        run = post_resp.json()
        run_id = run.get("id")
        assert run_id is not None, "Run ID is missing in response"

        # Request the SSE stream for the created run
        stream_resp = requests.get(
            f"{BASE_URL}/api/runs/{run_id}/stream",
            stream=True,
            timeout=TIMEOUT
        )
        assert stream_resp.status_code == 200, f"Expected 200, got {stream_resp.status_code}"
        content_type = stream_resp.headers.get("Content-Type", "")
        assert "text/event-stream" in content_type, f"Expected 'text/event-stream' in Content-Type, got '{content_type}'"

        # Read few lines from the stream to confirm streaming content
        lines = []
        try:
            for idx, line in enumerate(stream_resp.iter_lines(decode_unicode=True)):
                if line:
                    lines.append(line)
                if idx >= 10:
                    break
        except requests.exceptions.ChunkedEncodingError:
            # If server closes connection, that's acceptable for a stream test
            pass

        assert any(line.startswith("data:") or line.startswith("event:") for line in lines), "No SSE event lines found in stream"

    finally:
        if run and run.get("id"):
            # Cleanup: no documented delete endpoint for runs, skip deletion

            # If endpoint existed:
            # requests.delete(f"{BASE_URL}/api/runs/{run_id}", timeout=TIMEOUT)
            pass

test_get_runs_runid_stream_returns_sse_events()