// This script has no account credential. It only reads the current form and
// fills fields after the user invokes the extension.
const fieldIds = new WeakMap();
let nextFieldId = 1;
let transfer = null;

function idFor(element) {
  if (!fieldIds.has(element)) fieldIds.set(element, String(nextFieldId++));
  return fieldIds.get(element);
}

function controls() {
  return [...document.querySelectorAll("input, textarea, select")].filter((el) => {
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
  return [direct, aria, labelledBy, el.placeholder, parent, el.name, el.id]
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
  if (el.tagName === "TEXTAREA" || (el.type === "text" && /why |describe|tell us|explain|what |how /.test(label))) return "question";
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
  const company = posting?.hiringOrganization?.name
    || document.querySelector('[data-testid="company-name"]')?.textContent?.trim()
    || document.querySelector('[class*="company-name"]')?.textContent?.trim()
    || document.querySelector('[data-automation-id="companyName"]')?.textContent?.trim()
    || (host.includes("myworkdayjobs.com") ? host.split(".")[0] : "")
    || (!/greenhouse|lever|ashbyhq|workday|smartrecruiters|icims|linkedin/.test(host)
      ? document.querySelector('meta[property="og:site_name"]')?.content : "")
    || (host.includes("greenhouse.io") || host.includes("lever.co") || host.includes("ashbyhq.com")
      ? location.pathname.split("/").filter(Boolean)[0] : "");
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
    filled: el.type === "checkbox" || el.type === "radio" ? el.checked : Boolean(el.value),
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

function setValue(el, value) {
  if (el.maxLength > 0 && String(value).length > el.maxLength) return false;
  let accepted = true;
  if (el.tagName === "SELECT") {
    const wanted = String(value).trim().toLowerCase();
    const option = [...el.options].find((o) => o.value.toLowerCase() === wanted || o.textContent.trim().toLowerCase() === wanted);
    if (!option) return false;
    el.value = option.value;
  } else if (el.type === "checkbox" || el.type === "radio") {
    const answer = String(value).trim().toLowerCase();
    const choice = (el.value === "on" ? labelOf(el) : el.value || labelOf(el)).trim().toLowerCase();
    if (!["yes", "no", "true", "false"].includes(answer)) return false;
    if (el.type === "radio") {
      if (choice !== answer) return false;
      el.checked = true;
    } else {
      el.checked = answer === "yes" || answer === "true";
    }
  } else {
    const prototype = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(el, String(value));
    accepted = el.value === String(value);
  }
  if (!accepted) return false;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return el.tagName === "SELECT" || el.type === "checkbox" || el.type === "radio" || el.value === String(value);
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
    country: x.country, work_authorization: x.work_authorization,
    sponsorship: x.sponsorship, relocation: x.relocation, salary: x.salary, availability: x.availability,
    school: education.school, degree: education.degree,
    recent_company: recent.company, recent_role: recent.role,
    veteran: x.veteran, disability: x.disability, gender: x.gender, ethnicity: x.ethnicity,
  };
}

function autofill(profile, answers) {
  const values = valuesFrom(profile);
  const bank = new Map();
  for (const answer of answers || []) {
    const key = normalize(answer.prompt);
    if (key && !bank.has(key)) bank.set(key, answer.content);
  }
  const filled = [];
  const skipped = [];
  for (const el of controls()) {
    const selected = el.tagName === "SELECT" ? el.options[el.selectedIndex] : null;
    const placeholder = selected && el.selectedIndex === 0 && /select|choose|please|^\s*$/.test(selected.textContent.toLowerCase());
    const chosen = el.type === "checkbox" || el.type === "radio" ? el.checked : (el.value && !placeholder);
    if (el.type === "file" || chosen) continue;
    const kind = classify(el);
    const answer = kind === "question" ? bank.get(normalize(labelOf(el))) : values[kind];
    if (answer && setValue(el, answer)) filled.push(labelOf(el) || kind);
    else if (kind !== "unknown") skipped.push(labelOf(el) || kind);
  }
  return { filled, skipped, questions: pageSnapshot().questions };
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
    else if (message.type === "AUTOFILL") {
      const result = autofill(message.profile, message.answers);
      chrome.runtime.sendMessage({ type: "ARM_APPLICATION", job: message.job }, (armed) => {
        sendResponse(armed?.ok ? { ok: true, ...result } : { ok: false, error: "Could not enable application tracking" });
      });
      return true;
    } else if (message.type === "INSERT_ANSWER") {
      const field = findField(message.fieldId);
      sendResponse({ ok: Boolean(field && setValue(field, message.content)) });
    } else if (message.type === "UPLOAD_START") {
      transfer = { kind: message.kind, name: message.name, mime: message.mime, parts: [] };
      sendResponse({ ok: true });
    } else if (message.type === "UPLOAD_CHUNK") {
      if (!transfer) throw new Error("No document transfer");
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
