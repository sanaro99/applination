import requests

def test_get_dashboard_home_page():
    base_url = "http://localhost:3000"
    url = f"{base_url}/"
    headers = {
        "Accept": "text/html"
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as e:
        assert False, f"Request to {url} failed with exception: {e}"

    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
    content_type = response.headers.get("Content-Type", "")
    assert "text/html" in content_type.lower(), f"Expected Content-Type to include 'text/html', got '{content_type}'"
    content = response.text
    # Basic checks that the content contains keywords related to the dashboard
    # Since no schema described, validate some expected substrings
    expected_keywords = ["application stats", "recent activity", "dashboard"]
    # Check if at least one expected keyword is present (case insensitive)
    content_lower = content.lower()
    assert any(keyword in content_lower for keyword in expected_keywords), (
        "Dashboard HTML does not seem to contain expected dashboard content keywords"
    )

test_get_dashboard_home_page()