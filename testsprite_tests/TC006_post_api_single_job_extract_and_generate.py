import requests

BASE_URL = "http://localhost:3000"
TIMEOUT = 30
HEADERS = {"Content-Type": "application/json"}


def test_post_api_single_job_extract_and_generate():
    extract_url = f"{BASE_URL}/api/single-job/extract"
    generate_url = f"{BASE_URL}/api/single-job/generate"

    # Sample valid job URL for extraction
    valid_job_url_payload = {
        "source_url": "https://example.com/jobs/software-engineer-1234"
    }

    # Sample manual job entry payload (alternative)
    manual_job_entry_payload = {
        "company": "Example Corp",
        "title": "Software Engineer",
        "description": "Develop and maintain software applications.",
        "questions": [
            "Why do you want to work here?",
            "Describe your experience with Python."
        ]
    }

    def delete_application(app_id):
        try:
            response = requests.delete(f"{BASE_URL}/api/applications/{app_id}", timeout=TIMEOUT)
            # We do not assert delete success here because it is cleanup
        except Exception:
            pass

    # Try extraction by URL first
    try:
        resp_extract = requests.post(extract_url, json=valid_job_url_payload, headers=HEADERS, timeout=TIMEOUT)
        # Accept both success and extraction failure gracefully
        if resp_extract.status_code == 200:
            extracted_data = resp_extract.json()

            # Validate extracted data contains expected keys
            assert "company" in extracted_data, "Extraction response missing 'company'"
            assert "title" in extracted_data, "Extraction response missing 'title'"
            assert "description" in extracted_data, "Extraction response missing 'description'"
            assert "questions" in extracted_data, "Extraction response missing 'questions'"

            # Now generate application materials using the extracted data
            resp_generate = requests.post(generate_url, json=extracted_data, headers=HEADERS, timeout=TIMEOUT)
            assert resp_generate.status_code == 200, f"Generate response status not 200: {resp_generate.status_code}"
            generate_data = resp_generate.json()

            # Validate generate response contains new application ID and artifacts info
            assert "application_id" in generate_data, "Generate response missing 'application_id'"
            assert "artifacts" in generate_data, "Generate response missing 'artifacts'"

            application_id = generate_data["application_id"]
            # Cleanup created application
            delete_application(application_id)

        elif resp_extract.status_code >= 400:
            # Extraction failed (e.g., unsupported URL), try manual entry
            resp_manual_extract = requests.post(extract_url, json=manual_job_entry_payload, headers=HEADERS, timeout=TIMEOUT)
            assert resp_manual_extract.status_code == 200, f"Manual extract status not 200: {resp_manual_extract.status_code}"
            manual_extracted_data = resp_manual_extract.json()

            # Validate manual extraction keys
            assert manual_extracted_data.get("company") == manual_job_entry_payload["company"]
            assert manual_extracted_data.get("title") == manual_job_entry_payload["title"]
            assert manual_extracted_data.get("description") == manual_job_entry_payload["description"]
            assert manual_extracted_data.get("questions") == manual_job_entry_payload["questions"]

            resp_generate_manual = requests.post(generate_url, json=manual_extracted_data, headers=HEADERS, timeout=TIMEOUT)
            assert resp_generate_manual.status_code == 200, f"Generate manual status not 200: {resp_generate_manual.status_code}"
            gen_manual_data = resp_generate_manual.json()

            assert "application_id" in gen_manual_data
            assert "artifacts" in gen_manual_data

            application_id = gen_manual_data["application_id"]
            # Cleanup created application
            delete_application(application_id)

        else:
            assert False, f"Unexpected extract response status: {resp_extract.status_code}"

    except requests.RequestException as e:
        assert False, f"Request failed: {e}"


test_post_api_single_job_extract_and_generate()