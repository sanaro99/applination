// This script has no account credential. It only reads the current form and
// fills fields after the user invokes the extension.
const fieldIds = new WeakMap();
let nextFieldId = 1;
let transfer = null;
let fillRun = null;
let lastFill = null;
let overlay = null;

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const backgroundMessage = (message) => new Promise((resolve) => {
  chrome.runtime.sendMessage(message, (result) => resolve(result || { ok: false }));
});

function progressPanel() {
  if (overlay) return overlay;
  const host = document.createElement("div");
  host.id = "applination-progress-host";
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `<style>
    :host { all: initial; position: fixed; right: 16px; bottom: 16px; z-index: 2147483647;
      width: min(380px, calc(100vw - 32px)); color: #20202a; font: 13px/1.45 Inter, system-ui, sans-serif; }
    * { box-sizing: border-box; } button { font: inherit; cursor: pointer; }
    .panel { overflow: hidden; border: 1px solid #e4e3eb; border-radius: 15px; background: white;
      box-shadow: 0 18px 55px #1b173a30, 0 3px 9px #1b173a12; }
    .head { padding: 17px 18px 13px; border-bottom: 1px solid #efedf4; }
    .top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
    h2 { margin: 0; font-size: 16px; font-weight: 750; letter-spacing: -.02em; }
    .brand { margin: 4px 0 0; color: #736f82; font-size: 11px; }
    .stop { width: 25px; height: 25px; border: 0; border-radius: 7px; color: #51496b; background: #f2f0f8; font-size: 15px; }
    .stage { margin: 13px 0 7px; color: #5a51ba; font-weight: 650; }
    .count { color: #777383; font-size: 11px; }
    .bar { height: 5px; margin-top: 10px; overflow: hidden; border-radius: 10px; background: #efedf7; }
    .bar > span { display: block; height: 100%; width: 0; border-radius: inherit;
      background: linear-gradient(90deg, #5d54d9, #a65ad3); transition: width .2s ease; }
    .list { max-height: min(45vh, 330px); min-height: 64px; overflow-y: auto; padding: 6px 18px; }
    .item { display: flex; align-items: flex-start; gap: 9px; padding: 6px 0; color: #565362; }
    .icon { display: grid; flex: 0 0 18px; place-items: center; width: 18px; height: 18px;
      border-radius: 50%; color: white; background: #b6b0c8; font-size: 11px; font-weight: 750; }
    .done .icon { background: #6156d6; } .active .icon { background: #aa83e7; }
    .review .icon { background: #d19a49; } .failed .icon { background: #c87976; }
    .item strong { display: block; color: #34303e; font-weight: 600; }
    .item small { display: block; color: #8a8595; font-size: 10px; }
    .foot { padding: 12px 18px 15px; border-top: 1px solid #efedf4; }
    .summary { margin: 0 0 10px; color: #777383; font-size: 11px; }
    .again { width: 100%; padding: 9px; border: 1px solid #e1deee; border-radius: 9px;
      color: #5b50b8; background: #f8f7fc; font-weight: 700; }
    .again:disabled { opacity: .5; cursor: default; }
  </style><section class="panel" role="status" aria-live="polite">
    <div class="head"><div class="top"><div><h2 id="title">Autofilling this page…</h2>
    <p class="brand">Using Applination</p></div><button id="stop" class="stop" title="Stop autofill" aria-label="Stop autofill">■</button></div>
    <p id="stage" class="stage">Detecting questions &amp; input fields</p><span id="count" class="count"></span>
    <div class="bar"><span id="bar"></span></div></div>
    <div id="list" class="list"></div><div class="foot"><p id="summary" class="summary">Review each field before submitting.</p>
    <button id="again" class="again" disabled>Run Autofill Again ↻</button></div></section>`;
  document.documentElement.append(host);
  shadow.getElementById("stop").onclick = () => {
    if (fillRun?.running) {
      fillRun.cancelled = true;
      shadow.getElementById("stage").textContent = "Stopping after the current field…";
    } else {
      host.remove();
      overlay = null;
    }
  };
  shadow.getElementById("again").onclick = () => { if (lastFill) startFill(lastFill); };
  overlay = { host, shadow, items: new Map() };
  return overlay;
}

function progressStage(run, title) {
  run.stage = title;
  progressPanel().shadow.getElementById("stage").textContent = title;
}

function progressItem(run, key, label, state, detail = "") {
  const panel = progressPanel();
  let row = panel.items.get(key);
  if (!row) {
    row = document.createElement("div");
    row.className = "item";
    const icon = document.createElement("span");
    icon.className = "icon";
    const words = document.createElement("span");
    const heading = document.createElement("strong");
    const note = document.createElement("small");
    words.append(heading, note);
    row.append(icon, words);
    panel.shadow.getElementById("list").append(row);
    panel.items.set(key, row);
  }
  row.className = `item ${state}`;
  row.querySelector(".icon").textContent = { done: "✓", active: "…", review: "!", failed: "×" }[state] || "·";
  row.querySelector("strong").textContent = label || "Application field";
  row.querySelector("small").textContent = detail;
  if (state !== "active") run.results.set(key, state);
  const checked = run.results.size;
  panel.shadow.getElementById("count").textContent = `${checked} fields checked · ${run.detected} detected`;
  panel.shadow.getElementById("bar").style.width = `${Math.min(100, 100 * checked / Math.max(run.total, checked, 1))}%`;
  const list = panel.shadow.getElementById("list");
  list.scrollTop = list.scrollHeight;
}

function progressFinish(run, error = "") {
  run.running = false;
  run.final = { running: false, cancelled: run.cancelled, filled: run.added,
    review: [...run.results.values()].filter((state) => state === "review" || state === "failed").length,
    error };
  const panel = progressPanel().shadow;
  const completed = [...run.results.values()];
  const filled = completed.filter((state) => state === "done").length;
  const review = completed.filter((state) => state === "review" || state === "failed").length;
  panel.getElementById("title").textContent = run.cancelled ? "Autofill stopped" : error ? "Autofill needs attention" : "Autofill complete";
  panel.getElementById("stage").textContent = run.cancelled ? "Stopped" : error || "Review the application before submitting";
  panel.getElementById("count").textContent = `${completed.length} fields checked · ${run.detected} detected`;
  panel.getElementById("summary").textContent = `${filled} filled · ${review} need review. Nothing was submitted.`;
  panel.getElementById("stop").textContent = "×";
  panel.getElementById("stop").title = "Close progress";
  panel.getElementById("again").disabled = false;
  if (!run.cancelled) panel.getElementById("bar").style.width = "100%";
}

function idFor(element) {
  if (!fieldIds.has(element)) fieldIds.set(element, String(nextFieldId++));
  return fieldIds.get(element);
}

function controls() {
  return [...document.querySelectorAll('input, textarea, select, [role="combobox"], [aria-haspopup="listbox"], [contenteditable="true"]')].filter((el) => {
    if (el.disabled || el.type === "hidden" || el.type === "password") return false;
    if (el.type === "file") return true;
    return el.getClientRects().length > 0;
  });
}

function labelOf(el) {
  const direct = [...(el.labels || [])].map((node) => node.innerText).join(" ");
  const aria = el.getAttribute("aria-label") || "";
  const labelledBy = (el.getAttribute("aria-labelledby") || "").split(/\s+/)
    .map((id) => document.getElementById(id)?.innerText || "").join(" ");
  const parent = el.closest("fieldset")?.querySelector("legend")?.innerText || "";
  return [direct, aria, labelledBy, el.placeholder, parent, el.name, el.id,
    el.getAttribute("data-testid"), el.tagName === "BUTTON" ? el.innerText : ""]
    .find((value) => value?.trim())?.replace(/[_-]/g, " ").replace(/\s+/g, " ").trim() || "";
}

function classify(el) {
  const label = `${labelOf(el)} ${el.closest("fieldset")?.querySelector("legend")?.innerText || ""}`.toLowerCase();
  if (el.type === "file") {
    if (/cover\s*letter/.test(label)) return "cover";
    if (/resume|cv\b|curriculum vitae/.test(label)) return "resume";
    return "file_unknown";
  }
  if (/cover\s*letter/.test(label)) return "cover_text";
  if (/email/.test(label) || el.autocomplete === "email") return "email";
  if (/phone\s*(country|region|code)|dial(?:ling|ing)?\s*code/.test(label)) return "phone_country";
  if (/phone|mobile|telephone/.test(label) || el.autocomplete === "tel") return "phone";
  if (/first\s*name|given\s*name/.test(label) || el.autocomplete === "given-name") return "first_name";
  if (/last\s*name|family\s*name|surname/.test(label) || el.autocomplete === "family-name") return "last_name";
  if (/full\s*name|your\s*name|candidate\s*name/.test(label) || el.autocomplete === "name") return "full_name";
  if (/linkedin/.test(label)) return "linkedin";
  if (/preferred\s*name/.test(label)) return "preferred_name";
  if (/pronouns/.test(label)) return "pronouns";
  if (/github/.test(label)) return "github";
  if (/portfolio|personal website/.test(label)) return "portfolio";
  if (/zip|postal\s*code/.test(label)) return "postal_code";
  if (/current\s*city|city/.test(label)) return "city";
  if (/\b(state|province|region)\b/.test(label)) return "state";
  if (/country/.test(label)) return "country";
  if (/address/.test(label)) return "address";
  if (/location/.test(label)) return "location";
  if (/sponsor|visa/.test(label)) return "sponsorship";
  if (/work\s*authoriz|legally\s*(eligible|authorized)/.test(label)) return "work_authorization";
  if (/relocat/.test(label)) return "relocation";
  if (/available|availability|start date/.test(label)) return "availability";
  if (/salary|compensation/.test(label)) return "salary";
  if (/school|university|college/.test(label)) return "school";
  if (/degree/.test(label)) return "degree";
  if (/current\s*(employer|company)|most recent\s*(employer|company)/.test(label)) return "recent_company";
  if (/current\s*(job title|role|position)|most recent\s*(job title|role|position)/.test(label)) return "recent_role";
  if (/veteran/.test(label)) return "veteran";
  if (/disability/.test(label)) return "disability";
  if (/gender/.test(label)) return "gender";
  if (/ethnic|race/.test(label)) return "ethnicity";
  if (el.tagName === "TEXTAREA" || ((el.type === "text" || el.isContentEditable) &&
    /why |describe|tell us|explain|what |how /.test(label))) return "question";
  return "unknown";
}

function jobDetails() {
  let posting = null;
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const nodes = JSON.parse(script.textContent);
      const candidates = Array.isArray(nodes) ? nodes : [nodes];
      posting = candidates.flatMap((node) => node?.["@graph"] || [node])
        .find((node) => String(node?.["@type"] || "").includes("JobPosting"));
      if (posting) break;
    } catch { /* Invalid structured data should not prevent page detection. */ }
  }
  const title = posting?.title || document.querySelector("h1")?.textContent?.trim()
    || document.querySelector('meta[property="og:title"]')?.content || document.title;
  const host = location.hostname.replace(/^www\./, "");
  const pathParts = location.pathname.split("/").filter(Boolean);
  const greenhouseBoard = /(^|\.)greenhouse\.io$/.test(host)
    ? (pathParts[0] === "embed" ? new URL(location.href).searchParams.get("for") : pathParts[0]) : "";
  const boardName = greenhouseBoard && !/^(embed|jobs?|apply|application)$/i.test(greenhouseBoard)
    ? greenhouseBoard : "";
  const company = posting?.hiringOrganization?.name
    || document.querySelector('[data-testid="company-name"]')?.textContent?.trim()
    || document.querySelector('[class*="company-name"]')?.textContent?.trim()
    || document.querySelector('[data-automation-id="companyName"]')?.textContent?.trim()
    || (host.includes("myworkdayjobs.com") ? host.split(".")[0] : "")
    || (!/greenhouse|lever|ashbyhq|workday|smartrecruiters|icims|linkedin/.test(host)
      ? document.querySelector('meta[property="og:site_name"]')?.content : "")
    || boardName
    || ((host.includes("lever.co") || host.includes("ashbyhq.com")) &&
      !/^(embed|jobs?|apply|application)$/i.test(pathParts[0] || "") ? pathParts[0] : "");
  const descriptionElement = document.querySelector(
    '[class*="job-description"], [id*="job-description"], [data-testid*="job-description"], article'
  );
  const structuredDescription = posting?.description
    ? new DOMParser().parseFromString(posting.description, "text/html").body.textContent : "";
  const mainText = document.querySelector("main")?.innerText || document.body.innerText || "";
  const fallbackDescription = mainText.length >= 300 && /responsibilit|qualif|about the role|job description|what you.ll do/i.test(mainText)
    ? mainText : "";
  const description = (structuredDescription || descriptionElement?.innerText || fallbackDescription)
    .trim().slice(0, 15000);
  const locationText = posting?.jobLocation?.address?.addressLocality || "";
  return { url: location.href, title: String(title).trim().slice(0, 200),
    company: String(company || "").trim().slice(0, 200), description,
    location: String(locationText).slice(0, 200) };
}

function pageSnapshot() {
  const fields = controls().map((el) => ({ id: idFor(el), label: labelOf(el), kind: classify(el),
    type: el.type || el.tagName.toLowerCase(),
    filled: el.type === "radio" ? radioGroup(el).some((candidate) => candidate.checked) : isFilled(el),
    required: el.required || el.getAttribute("aria-required") === "true",
    maxLength: el.maxLength > 0 ? el.maxLength : null }));
  const relevant = fields.filter((field) => !["unknown", "file_unknown"].includes(field.kind));
  const isApplication = fields.length >= 2 && relevant.length >= 2 &&
    (Boolean(document.querySelector("form")) || relevant.length >= 3);
  return { job: jobDetails(), fields, isApplication,
    questions: fields.filter((field) => field.kind === "question" && !field.filled) };
}

function findField(id) {
  return controls().find((el) => idFor(el) === String(id));
}

function radioGroup(el) {
  return controls().filter((candidate) => candidate.type === "radio" &&
    candidate.form === el.form && (el.name ? candidate.name === el.name : candidate === el));
}

const US_STATES = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California",
  CO: "Colorado", CT: "Connecticut", DE: "Delaware", FL: "Florida", GA: "Georgia",
  HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa",
  KS: "Kansas", KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
  MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi", MO: "Missouri",
  MT: "Montana", NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey",
  NM: "New Mexico", NY: "New York", NC: "North Carolina", ND: "North Dakota", OH: "Ohio",
  OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont",
  VA: "Virginia", WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
  DC: "District of Columbia",
};

function answerTerms(value) {
  const word = normalize(value);
  const terms = new Set([word]);
  const aliases = {
    yes: ["true", "1", "y"], no: ["false", "0", "n"],
    us: ["usa", "united states", "united states of america"],
    uk: ["united kingdom", "great britain"],
  };
  for (const [canonical, list] of Object.entries(aliases)) {
    if ([canonical, ...list].includes(word)) for (const term of [canonical, ...list]) terms.add(term);
  }
  for (const [code, name] of Object.entries(US_STATES)) {
    if (word === normalize(code) || word === normalize(name)) {
      terms.add(normalize(code));
      terms.add(normalize(name));
      break;
    }
  }
  return [...terms].filter(Boolean);
}

function matchChoice(choices, answer) {
  const terms = answerTerms(answer);
  const available = choices.filter((choice) => !choice.disabled);
  const exact = available.filter((choice) => [choice.value, choice.label]
    .some((value) => terms.includes(normalize(value))));
  if (exact.length === 1) return exact[0];
  if (exact.length > 1) return exact.find((choice) => normalize(choice.value) === normalize(answer)) || exact[0];
  const phrases = terms.filter((term) => term.length >= 3);
  const partial = available.filter((choice) => phrases.some((term) => {
    const label = normalize(choice.label);
    return label === term || label.startsWith(`${term} `) || label.endsWith(` ${term}`)
      || label.includes(` ${term} `);
  }));
  return partial.length === 1 ? partial[0] : null;
}

function isFilled(el) {
  if (el.type === "checkbox" || el.type === "radio") return el.checked;
  if (el.type === "file") return Boolean(el.files?.length);
  if (el.tagName === "SELECT") {
    const selected = el.options[el.selectedIndex];
    return Boolean(selected?.value && !/^(select|choose|please)\b/i.test(selected.textContent.trim()));
  }
  if (el.isContentEditable) return Boolean(el.textContent?.trim());
  if (el.tagName === "BUTTON") return Boolean(el.textContent.trim()) &&
    !/^(select|choose|please)\b/i.test(el.textContent.trim());
  return Boolean(el.value);
}

function setValue(el, value) {
  let text = String(value).trim();
  if (!text || (el.maxLength > 0 && text.length > el.maxLength)) return false;
  if (el.tagName === "SELECT") {
    const choice = matchChoice([...el.options].map((option) => ({
      value: option.value, label: option.textContent, disabled: option.disabled, element: option,
    })), text);
    if (!choice || !choice.value) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(el, choice.value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return el.value === choice.value;
  }
  if (el.type === "radio") {
    const group = radioGroup(el);
    const choice = matchChoice(group.map((candidate) => ({ value: candidate.value,
      label: [...(candidate.labels || [])].map((label) => label.innerText).join(" "),
      disabled: candidate.disabled, element: candidate })), text);
    if (!choice) return false;
    choice.element.click();
    return choice.element.checked;
  }
  if (el.type === "checkbox") {
    const answer = normalize(text);
    if (!["yes", "true", "no", "false"].includes(answer)) return false;
    const desired = answer === "yes" || answer === "true";
    if (!desired && el.required) return false;
    if (el.checked !== desired) el.click();
    return el.checked === desired;
  }
  if (el.isContentEditable) {
    el.textContent = text;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return el.textContent === text;
  }
  if (el.type === "number") {
    if (!/^-?[\d,]+(?:\.\d+)?$/.test(text)) return false;
    text = text.replace(/,/g, "");
  }
  if (el.type === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;
  if (el.type === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text)) return false;
  if (el.type === "url" && !/^https?:\/\/\S+$/i.test(text)) return false;
  const prototype = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value").set.call(el, text);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return el.value === text;
}

async function setControl(el, value) {
  if (el.tagName === "SELECT" || (el.getAttribute("role") !== "combobox" &&
    el.getAttribute("aria-haspopup") !== "listbox")) {
    return setValue(el, value);
  }
  const before = el.value ?? el.textContent;
  el.click();
  await pause(80);
  let choices = [...document.querySelectorAll('[role="option"]')].filter((option) =>
    option.getClientRects().length > 0 && option.getAttribute("aria-disabled") !== "true"
  ).map((option) => ({ value: option.getAttribute("data-value") || option.textContent,
    label: option.textContent, element: option }));
  let choice = matchChoice(choices, value);
  if (!choice && el.tagName === "INPUT") {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, String(value));
    el.dispatchEvent(new Event("input", { bubbles: true }));
    await pause(150);
    choices = [...document.querySelectorAll('[role="option"]')].filter((option) =>
      option.getClientRects().length > 0 && option.getAttribute("aria-disabled") !== "true"
    ).map((option) => ({ value: option.getAttribute("data-value") || option.textContent,
      label: option.textContent, element: option }));
    choice = matchChoice(choices, value);
  }
  if (!choice) {
    if (el.tagName === "INPUT") {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, before);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    return false;
  }
  choice.element.click();
  return true;
}

function valuesFrom(profile) {
  const c = profile.contact || {};
  const x = profile.extra || {};
  const name = String(c.full_name || "").trim();
  const words = name.split(/\s+/);
  const recent = profile.resume?.experience?.[0] || {};
  const education = profile.resume?.education?.[0] || {};
  return {
    full_name: name, first_name: words[0] || "", last_name: words.slice(1).join(" "),
    preferred_name: x.preferred_name, pronouns: x.pronouns,
    email: c.email, phone: c.phone, linkedin: c.linkedin, github: c.github,
    portfolio: c.portfolio || x.website, location: c.location_city,
    address: x.address, city: x.city, state: x.state, postal_code: x.postal_code,
    country: x.country, phone_country: x.country, work_authorization: x.work_authorization,
    sponsorship: x.sponsorship, relocation: x.relocation, salary: x.salary, availability: x.availability,
    school: education.school, degree: education.degree,
    recent_company: recent.company, recent_role: recent.role,
    veteran: x.veteran, disability: x.disability, gender: x.gender, ethnicity: x.ethnicity,
  };
}

function displayLabel(el) {
  return (el.type === "radio" && el.closest("fieldset")?.querySelector("legend")?.innerText)
    || labelOf(el) || classify(el).replace(/_/g, " ");
}

function startFill(payload) {
  if (fillRun?.running) return { ok: false, error: "Autofill is already running on this page" };
  lastFill = payload;
  const panel = progressPanel().shadow;
  panel.getElementById("list").replaceChildren();
  overlay.items.clear();
  panel.getElementById("title").textContent = "Autofilling this page…";
  panel.getElementById("stop").textContent = "■";
  panel.getElementById("stop").title = "Stop autofill";
  panel.getElementById("again").disabled = true;
  panel.getElementById("bar").style.width = "0%";
  panel.getElementById("summary").textContent = "Review each field before submitting.";
  fillRun = { running: true, cancelled: false, stage: "Detecting fields", total: 0,
    detected: 0, added: 0, results: new Map() };
  void executeFill(fillRun, payload);
  return { ok: true, started: true };
}

async function executeFill(run, payload) {
  try {
    progressStage(run, "Detecting questions & input fields");
    const snapshot = pageSnapshot();
    run.detected = snapshot.fields.length;
    run.total = snapshot.fields.filter((field) => field.kind !== "unknown" || field.required).length;
    progressPanel().shadow.getElementById("count").textContent = `${run.detected} fields detected`;
    const armed = await backgroundMessage({ type: "ARM_APPLICATION", job: payload.job });
    if (!armed?.ok) progressPanel().shadow.getElementById("summary").textContent =
      "Submission tracking is unavailable. Review the form before submitting.";

    const values = valuesFrom(payload.profile);
    const bank = new Map();
    for (const answer of payload.answers || []) {
      const key = normalize(answer.prompt);
      if (key && !bank.has(key)) bank.set(key, answer.content);
    }
    const processed = new WeakSet();
    progressStage(run, "Matching your profile to available fields");
    for (let pass = 0; pass < 4 && !run.cancelled; pass++) {
      let discovered = 0;
      for (const el of controls()) {
        if (run.cancelled) break;
        if (processed.has(el)) continue;
        discovered++;
        processed.add(el);
        const kind = classify(el);
        if (kind === "unknown" || kind === "file_unknown" || el.type === "file") {
          if (el.required && el.type !== "file") progressItem(run, idFor(el), displayLabel(el), "review", "Check this field manually");
          continue;
        }
        if (el.type === "radio") {
          for (const sibling of radioGroup(el)) {
            processed.add(sibling);
          }
        }
        const key = idFor(el);
        const label = displayLabel(el);
        if (isFilled(el) || (el.type === "radio" && radioGroup(el).some((candidate) => candidate.checked))) {
          progressItem(run, key, label, "done", "Already completed");
          continue;
        }
        const answer = kind === "question" ? bank.get(normalize(labelOf(el))) : values[kind];
        if (!answer) {
          if (kind !== "question" && el.required) progressItem(run, key, label, "review", "No profile answer available");
          continue;
        }
        progressItem(run, key, label, "active", "Checking this input…");
        const matched = await setControl(el, answer);
        if (matched) {
          run.added++;
          progressItem(run, key, label, "done", el.tagName === "SELECT" ||
            el.type === "radio" || el.getAttribute("role") === "combobox"
            ? "Selected a matching option" : "Filled from your profile");
        } else progressItem(run, key, label, "review", "No safe matching option or value");
        await pause(70);
      }
      if (!discovered) break;
      const current = pageSnapshot().fields;
      run.total = Math.max(run.total, current.filter((field) => field.kind !== "unknown" || field.required).length);
    }

    if (!run.cancelled) progressStage(run, "Drafting unanswered questions");
    for (const question of pageSnapshot().questions.slice(0, 10)) {
      if (run.cancelled) break;
      if (!question.label || question.label.length < 3) continue;
      const key = question.id;
      progressItem(run, key, question.label, "active", "Generating an answer…");
      try {
        const generated = await backgroundMessage({ type: "GENERATE_ANSWER", question: {
          prompt: question.label, ...payload.job,
          word_limit: question.maxLength ? Math.max(20, Math.min(1000, Math.floor(question.maxLength / 6))) : null,
        } });
        if (run.cancelled) break;
        if (!generated?.ok) throw new Error(generated?.error || "Answer generation failed");
        if (question.maxLength && generated.content.length > question.maxLength) throw new Error("Draft exceeds the field limit");
        const el = findField(key);
        if (!el || !(await setControl(el, generated.content))) throw new Error("The field rejected the draft");
        run.added++;
        progressItem(run, key, question.label, "done", "Drafted answer added");
      } catch (error) { progressItem(run, key, question.label, "review", error.message); }
    }

    if (!run.cancelled) progressStage(run, "Attaching generated documents");
    for (const [kind, documentId] of [["resume", payload.resumeId], ["cover", payload.coverId]]) {
      if (run.cancelled) break;
      if (!documentId) continue;
      const target = fileTarget(kind);
      if (!target || isFilled(target)) continue;
      const key = idFor(target);
      const label = kind === "resume" ? "Resume" : "Cover letter";
      progressItem(run, key, label, "active", "Uploading generated document…");
      const result = await backgroundMessage({ type: "ATTACH_DOCUMENT", documentId, kind });
      if (run.cancelled) break;
      if (result?.ok) {
        run.added++;
        progressItem(run, key, label, "done", result.filename || "Attached");
      } else progressItem(run, key, label, "review", result?.error || "Attach this document manually");
    }
    progressFinish(run);
  } catch (error) {
    progressFinish(run, error.message || "Autofill failed");
  }
}

function normalize(text) {
  return String(text).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function fileTarget(kind) {
  const files = controls().filter((el) => el.type === "file");
  return files.find((el) => classify(el) === kind)
    || (kind === "resume" && files.length === 1 && classify(files[0]) === "file_unknown" ? files[0] : null);
}

function commitUpload() {
  if (!transfer) return { ok: false, error: "No document transfer" };
  const target = fileTarget(transfer.kind);
  if (!target) return { ok: false, error: `No ${transfer.kind} upload field found` };
  const extension = transfer.name.slice(transfer.name.lastIndexOf(".")).toLowerCase();
  const acceptedTypes = target.accept.toLowerCase().split(",").map((item) => item.trim()).filter(Boolean);
  if (acceptedTypes.length && !acceptedTypes.some((item) => item === extension || item === transfer.mime.toLowerCase())) {
    return { ok: false, error: `This site does not accept ${extension} in its ${transfer.kind} field` };
  }
  const length = transfer.parts.reduce((sum, part) => sum + part.length, 0);
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const part of transfer.parts) {
    bytes.set(part, offset);
    offset += part.length;
  }
  const file = new File([bytes], transfer.name, { type: transfer.mime });
  const dt = new DataTransfer();
  dt.items.add(file);
  target.files = dt.files;
  target.dispatchEvent(new Event("input", { bubbles: true }));
  target.dispatchEvent(new Event("change", { bubbles: true }));
  transfer = null;
  return { ok: true, filename: file.name };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  try {
    if (message.type === "GET_PAGE") sendResponse({ ok: true, ...pageSnapshot() });
    else if (message.type === "AUTOFILL") sendResponse(startFill(message));
    else if (message.type === "GET_PROGRESS") sendResponse({ ok: true, started: Boolean(fillRun), ...(fillRun?.final || {
      running: Boolean(fillRun?.running), stage: fillRun?.stage || "", filled: fillRun?.added || 0,
      review: [...(fillRun?.results?.values() || [])].filter((state) => state === "review" || state === "failed").length,
    }) });
    else if (message.type === "INSERT_ANSWER") {
      const field = findField(message.fieldId);
      sendResponse({ ok: Boolean(field && setValue(field, message.content)) });
    } else if (message.type === "UPLOAD_START") {
      transfer = { kind: message.kind, name: message.name, mime: message.mime, parts: [] };
      sendResponse({ ok: true });
    } else if (message.type === "UPLOAD_CHUNK") {
      if (!transfer) throw new Error("No document transfer");
      if (fillRun?.cancelled) throw new Error("Autofill stopped");
      transfer.parts.push(message.bytes);
      sendResponse({ ok: true });
    } else if (message.type === "UPLOAD_COMMIT") sendResponse(commitUpload());
  } catch (error) {
    transfer = null;
    sendResponse({ ok: false, error: String(error) });
  }
});

document.addEventListener("submit", () => {
  chrome.runtime.sendMessage({ type: "FORM_SUBMITTED" });
}, true);
document.addEventListener("click", (event) => {
  const button = event.target.closest?.("button, input[type='submit']");
  if (button && /^(submit|submit application|apply|send application)$/i.test(
    (button.innerText || button.value || "").trim()
  )) chrome.runtime.sendMessage({ type: "FORM_SUBMITTED" });
}, true);

let confirmationSent = false;
function checkConfirmation() {
  if (confirmationSent) return;
  const headings = [...document.querySelectorAll("h1, h2, [role='alert'], [role='status']")]
    .map((el) => el.textContent?.trim() || "").join(" ").toLowerCase();
  if (/application (has been |was )?(submitted|received)|thank you for (applying|your application)|successfully applied/.test(headings)) {
    confirmationSent = true;
    chrome.runtime.sendMessage({ type: "APPLICATION_CONFIRMED" }, (result) => {
      if (!result?.ok) confirmationSent = false;
    });
  }
}
setTimeout(checkConfirmation, 800);
new MutationObserver(checkConfirmation).observe(document.documentElement, { subtree: true, childList: true });
