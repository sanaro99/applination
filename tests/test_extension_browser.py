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
def test_ashby_style_fields_use_profile_and_available_choices():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME), headless=True)
        page = browser.new_page(viewport={"width": 900, "height": 640})
        page.set_content("""
          <form>
            <div><label>Autofill from resume</label><input type="file" id="helper-resume"></div>
            <div class="ashby-application-form-field-entry" data-field-path="_systemfield_name">
              <label for="_systemfield_name">Name</label>
              <input id="_systemfield_name" name="_systemfield_name" required placeholder="Type here...">
            </div>
            <div class="ashby-application-form-field-entry">
              <label for="linkedin">LinkedIn URL</label><input id="linkedin" type="url">
            </div>
            <div class="ashby-application-form-field-entry">
              <label for="application-resume">Resume</label><input id="application-resume" type="file" required>
            </div>
            <div class="ashby-application-form-field-entry">
              <label>Current Location</label>
              <input role="combobox" aria-haspopup="listbox" placeholder="Start typing..."
                oninput="showOptions(this, 'location')">
            </div>
            <div class="ashby-application-form-field-entry">
              <label>Will you now or in the future require sponsorship for employment visa status?</label>
              <div class="ashby-application-form-input-yesno">
                <button type="button" data-option="yes" aria-pressed="false" onclick="chooseYesNo(this)">Yes</button>
                <button type="button" data-option="no" aria-pressed="false" onclick="chooseYesNo(this)">No</button>
                <input type="checkbox" name="sponsorship" style="position:absolute;width:1px;height:1px;opacity:0">
              </div>
            </div>
            <div class="ashby-application-form-input-education-entry">
              <div><label>School</label><input role="combobox" aria-haspopup="listbox"
                placeholder="Search schools..." oninput="showOptions(this, 'school')"></div>
              <div><label for="degree">Degree</label><input id="degree"></div>
              <div><label for="major">Field of Study</label><input id="major"></div>
              <div><label>Start Date</label><select id="start-month"><option value="">Month...</option>
                <option value="9">September</option></select><select id="start-year"><option value="">Year...</option>
                <option>2022</option></select></div>
              <div><label>End Date</label><select id="end-month"><option value="">Month...</option>
                <option value="6">June</option></select><select id="end-year"><option value="">Year...</option>
                <option>2026</option></select></div>
            </div>
            <div class="ashby-application-form-field-entry" data-field-path="qualifications">
              <fieldset><label>Academic Qualifications</label>
                <label><input type="radio" name="qualifications">Yes, I meet all criteria.</label>
                <label><input type="radio" name="qualifications">No, I do not meet all criteria.</label>
              </fieldset>
            </div>
            <div><label for="essay-one">What are the most interesting aspects of this company
              that you're excited to work on?</label><textarea id="essay-one"></textarea></div>
            <div><label for="essay-two">How do you use AI in your day-to-day work?
              What are some of the underappreciated benefits and pain points?</label>
              <textarea id="essay-two"></textarea></div>
            <div><label for="essay-three">Is there anything else you'd like to tell us?</label>
              <textarea id="essay-three"></textarea></div>
          </form>
          <div id="options" role="listbox" hidden></div>
          <script>
            function chooseYesNo(button) {
              button.parentElement.querySelectorAll('button').forEach(el =>
                el.setAttribute('aria-pressed', String(el === button)));
              button.parentElement.querySelector('input').checked = button.dataset.option === 'yes';
            }
            function showOptions(input, kind) {
              const list = document.querySelector('#options');
              list.hidden = true;
              setTimeout(() => {
                list.innerHTML = kind === 'school'
                  ? '<div role="option" onclick="pick(this)"><span>University of Washington</span><span>United States</span></div>'
                  : '<div role="option" onclick="pick(this)"><span>Seattle, Washington</span><span>United States</span></div>';
                list.hidden = false;
                window.activeCombo = input;
              }, 220);
            }
            function pick(option) {
              window.activeCombo.value = option.querySelector('span').textContent;
              document.querySelector('#options').hidden = true;
            }
          </script>
        """)
        page.evaluate("""() => { window.chrome = {runtime: {
          onMessage: {addListener: handler => window.extensionHandler = handler},
          sendMessage: (message, callback) => {
            if (message.type === 'GENERATE_ANSWER') {
              window.generatedPrompts.push(message.question);
              callback?.({ok: true, content: window.completeDraft});
            } else callback?.({ok: true});
          }
        }};
        window.generatedPrompts = [];
        window.completeDraft = 'I enjoy building reliable products with careful attention to users. '
          .repeat(6) + 'I would bring that approach to this role.';
        }""")
        page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
        snapshot = page.evaluate("""() => {
          let result;
          window.extensionHandler({type: 'GET_PAGE'}, {}, value => result = value);
          return result;
        }""")
        sponsorship = next(field for field in snapshot["fields"] if field["kind"] == "sponsorship")
        assert [option["label"] for option in sponsorship["options"]] == ["Yes", "No"]
        month = next(field for field in snapshot["fields"] if field["kind"] == "education_start_month")
        assert "September" in [option["label"] for option in month["options"]]
        page.evaluate("""() => window.extensionHandler({
          type: 'AUTOFILL', job: {company: 'Perplexity', title: 'Engineer', url: location.href},
          profile: {contact: {full_name: 'Ada Lovelace', linkedin: 'linkedin.com/in/ada',
            location_city: 'Seattle, WA'}, extra: {sponsorship: 'No'},
            resume: {education: [{school: 'University of Washington', degree: 'BS Computer Science',
              start_date: 'Sep 2022', end_date: 'Jun 2026'}]}},
          answers: [{prompt: 'Academic Qualifications', content: 'No'}]
        }, {}, () => {})""")
        page.wait_for_function("""() => {
          let result;
          window.extensionHandler({type: 'GET_PROGRESS'}, {}, value => result = value);
          return result?.started && !result.running;
        }""")
        assert page.locator("#_systemfield_name").input_value() == "Ada Lovelace"
        assert page.locator("#linkedin").input_value() == "https://linkedin.com/in/ada"
        assert page.locator('input[placeholder="Start typing..."]').input_value() == "Seattle, Washington"
        assert page.locator('input[placeholder="Search schools..."]').input_value() == "University of Washington"
        assert page.locator("#major").input_value() == "Computer Science"
        assert page.locator("#start-month").input_value() == "9"
        assert page.locator("#start-year").input_value() == "2022"
        assert page.locator("#end-month").input_value() == "6"
        assert page.locator("#end-year").input_value() == "2026"
        assert page.locator('button[data-option="no"]').get_attribute("aria-pressed") == "true"
        assert page.locator('input[name="qualifications"]').nth(1).is_checked()
        assert len(page.evaluate("window.completeDraft")) > 300
        for essay in ("#essay-one", "#essay-two", "#essay-three"):
            assert page.locator(essay).input_value() == page.evaluate("window.completeDraft")
        assert len(page.evaluate("window.generatedPrompts")) == 3
        layout = page.evaluate("""() => {
          const shadow = document.querySelector('#applination-progress-host').shadowRoot;
          const box = selector => shadow.querySelector(selector).getBoundingClientRect();
          const rows = [...shadow.querySelectorAll('.item')];
          return {
            header: box('h2').bottom <= box('.brand').top + 1 &&
              box('.brand').bottom <= box('.stage').top + 1,
            rowText: rows.every(row => row.querySelector('strong').getBoundingClientRect().bottom <=
              row.querySelector('small').getBoundingClientRect().top + 1),
            rows: rows.every((row, index) => index === 0 ||
              rows[index - 1].getBoundingClientRect().bottom <= row.getBoundingClientRect().top + 1),
          };
        }""")
        assert layout == {"header": True, "rowText": True, "rows": True}
        upload = page.evaluate("""() => {
          let result;
          const send = message => window.extensionHandler(message, {}, value => result = value);
          send({type: 'UPLOAD_START', kind: 'resume', name: 'Ada_Resume.pdf', mime: 'application/pdf'});
          send({type: 'UPLOAD_CHUNK', bytes: [37, 80, 68, 70]});
          send({type: 'UPLOAD_COMMIT'});
          return {ok: result.ok, required: document.querySelector('#application-resume').files.length,
                  helper: document.querySelector('#helper-resume').files.length};
        }""")
        assert upload == {"ok": True, "required": 1, "helper": 0}
        browser.close()


@pytest.mark.skipif(not CHROME.exists(), reason="Chrome is unavailable")
def test_incomplete_or_page_truncated_answers_are_left_for_review():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(CHROME), headless=True)
        page = browser.new_page()
        page.set_content("""
          <form><label for="one">Why this role?</label><textarea id="one"></textarea>
          <label for="two">How would you contribute?</label><textarea id="two"
            oninput="setTimeout(() => this.value = this.value.slice(0, 250), 50)"></textarea></form>
        """)
        page.evaluate("""() => {
          window.chrome = {runtime: {
            onMessage: {addListener: handler => window.extensionHandler = handler},
            sendMessage: (message, callback) => callback?.(message.type === 'GENERATE_ANSWER'
              ? {ok: true, content: message.question.prompt.startsWith('Why')
                ? 'This partial draft ends halfway through an important thought and gives no complete answer. '
                  .repeat(3) + 'The result was'
                : 'I improved a production system by tracing its failures and testing each change. '
                  .repeat(5) + 'The work made the service reliable.'}
              : {ok: true})
          }};
        }""")
        page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
        page.evaluate("""() => window.extensionHandler({type: 'AUTOFILL', job: {company: 'Acme',
          title: 'Engineer', url: location.href}, profile: {contact: {}, extra: {}, resume: {}},
          answers: []}, {}, () => {})""")
        page.wait_for_function("""() => {
          let result;
          window.extensionHandler({type: 'GET_PROGRESS'}, {}, value => result = value);
          return result?.started && !result.running;
        }""")
        assert page.locator("#one").input_value() == ""
        assert page.locator("#two").input_value() == ""
        progress = page.evaluate("""() => {
          let result;
          window.extensionHandler({type: 'GET_PROGRESS'}, {}, value => result = value);
          return result;
        }""")
        assert progress["review"] == 2
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
