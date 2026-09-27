"""Exercise the content script against real browser form controls."""
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


@pytest.mark.skipif(not CHROME.exists(), reason="Chrome is unavailable")
def test_content_script_fills_and_attaches_in_browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME), headless=True)
        page = browser.new_page()
        page.set_content("""
            <script type="application/ld+json">{"@type":"JobPosting","title":"Software Engineer",
              "hiringOrganization":{"name":"Acme"},"description":"Build reliable software."}</script>
            <h1>Software Engineer</h1>
            <form>
              <label for="first">First name</label><input id="first">
              <label for="last">Last name</label><input id="last">
              <label for="email">Email</label><input id="email">
              <label for="work">Work authorization</label>
              <select id="work"><option value="">Choose one</option><option>Yes</option><option>No</option></select>
              <label for="state">State</label><select id="state"><option value="">Choose state</option>
                <option value="California">California</option><option value="Nevada">Nevada</option></select>
              <label for="salary">Salary expectation</label><select id="salary"><option value="">Choose salary</option>
                <option value="100000">100,000</option><option value="150000">150,000</option></select>
              <label for="relocate"><input id="relocate" type="checkbox">Willing to relocate</label>
              <label for="dial">Phone country code</label><button id="dial" type="button" role="combobox"
                onclick="document.querySelector('#dial-options').hidden = false">Choose phone country</button>
              <div id="dial-options" hidden><div role="option" onclick="document.querySelector('#dial').textContent = 'United States (+1)'; this.parentElement.hidden = true">United States (+1)</div>
                <div role="option" onclick="document.querySelector('#dial').textContent = 'Canada (+1)'; this.parentElement.hidden = true">Canada (+1)</div></div>
              <fieldset><legend>Will you require sponsorship?</legend>
                <label><input type="radio" name="sponsor" value="Yes">Yes</label>
                <label><input type="radio" name="sponsor" value="No">No</label>
              </fieldset>
              <label for="essay">Why this role?</label><textarea id="essay"></textarea>
              <label for="resume">Resume</label><input id="resume" type="file">
              <button type="submit">Submit application</button>
            </form>
        """)
        page.evaluate("""() => {
          window.messages = [];
          window.chrome = {runtime: {
            onMessage: {addListener: (handler) => { window.extensionHandler = handler; }},
            sendMessage: (message, callback) => {
              window.messages.push(message);
              if (callback) callback({ok: true});
            }
          }};
        }""")
        page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
        detected = page.evaluate("""() => {
          let response;
          window.extensionHandler({type: 'GET_PAGE'}, {}, (value) => { response = value; });
          return response;
        }""")
        assert detected["isApplication"] is True
        assert detected["job"]["company"] == "Acme"
        assert detected["job"]["description"] == "Build reliable software."
        assert sum(field["required"] for field in detected["fields"]) == 0
        result = page.evaluate("""() => {
          let response;
          window.extensionHandler({
            type: 'AUTOFILL', job: {company: 'Acme', title: 'Software Engineer', url: location.href},
            profile: {contact: {full_name: 'Ada Lovelace', email: 'ada@example.com'},
                      extra: {work_authorization: 'Yes', sponsorship: 'No', state: 'CA',
                        salary: '120000', relocation: 'Yes', country: 'US'}, resume: {}},
            answers: [{prompt: 'Why this role?', content: 'My relevant work fits this role.'}]
          }, {}, (value) => { response = value; });
          return response;
        }""")
        assert result == {"ok": True, "started": True}
        page.wait_for_function("""() => {
          let result;
          window.extensionHandler({type: 'GET_PROGRESS'}, {}, (value) => { result = value; });
          return result?.started && !result.running;
        }""")
        assert page.locator("#first").input_value() == "Ada"
        assert page.locator("#last").input_value() == "Lovelace"
        assert page.locator("#email").input_value() == "ada@example.com"
        assert page.locator("#work").input_value() == "Yes"
        assert page.locator("#state").input_value() == "California"
        assert page.locator("#salary").input_value() == ""
        assert page.locator("#relocate").is_checked()
        assert page.locator("#dial").inner_text() == "United States (+1)"
        assert page.locator('input[name="sponsor"][value="No"]').is_checked()
        assert page.locator("#essay").input_value() == "My relevant work fits this role."
        assert page.evaluate("document.querySelector('#applination-progress-host').shadowRoot.querySelector('#title').textContent") == "Autofill complete"
        assert "Salary expectation" in page.evaluate("document.querySelector('#applination-progress-host').shadowRoot.querySelector('#list').textContent")

        upload = page.evaluate("""() => {
          let result;
          const send = (message) => window.extensionHandler(message, {}, (value) => { result = value; });
          send({type: 'UPLOAD_START', kind: 'resume', name: 'Ada_Resume.pdf', mime: 'application/pdf'});
          send({type: 'UPLOAD_CHUNK', bytes: [37, 80, 68, 70, 45, 49, 46, 52]});
          send({type: 'UPLOAD_COMMIT'});
          return {result, name: document.querySelector('#resume').files[0]?.name,
                  size: document.querySelector('#resume').files[0]?.size};
        }""")
        assert upload == {"result": {"ok": True, "filename": "Ada_Resume.pdf"},
                          "name": "Ada_Resume.pdf", "size": 8}
        page.evaluate("""() => {
          const panel = document.querySelector('#applination-progress-host').shadowRoot;
          panel.querySelector('#again').click();
          panel.querySelector('#stop').click();
        }""")
        page.wait_for_function("""() => {
          let result;
          window.extensionHandler({type: 'GET_PROGRESS'}, {}, (value) => { result = value; });
          return result?.cancelled && !result.running;
        }""")
        browser.close()


@pytest.mark.skipif(not CHROME.exists(), reason="Chrome is unavailable")
def test_greenhouse_embed_uses_board_token_not_embed_as_company():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME), headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body="""
          <h1>Engineer</h1><main>Job description: Build great software. Responsibilities include design and testing.</main>
          <form><label>First name<input name="first_name"></label><label>Last name<input name="last_name"></label></form>
        """))
        page.goto("https://boards.greenhouse.io/embed/job_app?for=acme&token=123")
        page.evaluate("""() => { window.chrome = {runtime: {
          onMessage: {addListener: (handler) => window.extensionHandler = handler},
          sendMessage: (_message, callback) => callback?.({ok: true})
        }}; }""")
        page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
        company = page.evaluate("""() => {
          let result;
          window.extensionHandler({type: 'GET_PAGE'}, {}, (value) => result = value);
          return result.job.company;
        }""")
        assert company == "acme"
        page.goto("https://boards.greenhouse.io/embed/job_app?token=123")
        page.evaluate("""() => { window.chrome = {runtime: {
          onMessage: {addListener: (handler) => window.extensionHandler = handler},
          sendMessage: (_message, callback) => callback?.({ok: true})
        }}; }""")
        page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
        company_without_board = page.evaluate("""() => {
          let result;
          window.extensionHandler({type: 'GET_PAGE'}, {}, (value) => result = value);
          return result.job.company;
        }""")
        assert company_without_board == ""
        browser.close()


@pytest.mark.skipif(not CHROME.exists(), reason="Chrome is unavailable")
def test_popup_tailors_only_after_autofill_click():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME), headless=True)
        page = browser.new_page()
        page.add_init_script("""(() => {
          window.requests = [];
          const local = {appUrl: 'https://applination.example', token: 'test-token'};
          const session = {};
          const storage = (items) => ({
            get: async (keys) => typeof keys === 'string' ? {[keys]: items[keys]} : {...keys, ...items},
            set: async (entries) => Object.assign(items, entries),
            remove: async (keys) => { for (const key of Array.isArray(keys) ? keys : [keys]) delete items[key]; }
          });
          window.chrome = {
            storage: {local: storage(local), session: storage(session)},
            tabs: {
              query: async () => [{id: 8, url: 'https://jobs.example/apply'}],
              sendMessage: async (_id, message) => {
                if (message.type === 'GET_PAGE') return {ok: true, isApplication: true,
                  job: {url: 'https://jobs.example/apply', company: 'Acme',
                    title: 'Software Engineer', description: 'Build great software.'},
                  fields: [{id: '1', kind: 'first_name', required: true},
                    {id: '2', kind: 'resume', required: true}], questions: []};
                if (message.type === 'AUTOFILL') return {ok: true, started: true};
                if (message.type === 'GET_PROGRESS') return {ok: true, started: true, running: false, filled: 1, review: 0};
                return {ok: true};
              },
              create: async () => {},
            },
          };
          window.fetch = async (url) => {
            window.requests.push(url);
            if (url.endsWith('/profile')) return Response.json({account: 'ada@example.com', contact: {}, extra: {}, resume: {}});
            if (url.endsWith('/answers')) return Response.json([]);
            if (url.endsWith('/generate-resume') && !url.match(/\\/generate-resume\\/\\d+$/)) return Response.json({run_id: 7});
            if (url.endsWith('/generate-resume/7')) return Response.json({status: 'done', application_id: 12,
              resume_id: 'app:12:resume', cover_id: null, error: ''});
            if (url.includes('/documents/')) return new Response(new Blob(['%PDF-1.4\\n%%EOF'],
              {type: 'application/pdf'}), {headers: {'content-type': 'application/pdf',
                'content-disposition': 'attachment; filename="resume.pdf"'}});
            throw new Error(`Unexpected URL: ${url}`);
          };
        })()""")
        page.goto((ROOT / "extension" / "popup.html").as_uri())
        page.locator("#job-card").wait_for(state="visible")
        assert page.locator("#job-title").inner_text() == "Software Engineer"
        assert page.evaluate("window.requests.filter(url => url.endsWith('/generate-resume')).length") == 0
        page.locator("#fill-button").click()
        page.locator("#resume-actions").wait_for(state="visible")
        assert page.evaluate("window.requests.filter(url => url.endsWith('/generate-resume')).length") == 1
        assert "1 fields filled" in page.locator("#fill-result").inner_text()
        browser.close()
