const $ = (id) => document.getElementById(id);
const EXTRA = [
  ["address", "Street address"], ["city", "City"], ["state", "State / province"],
  ["postal_code", "Postal code"], ["country", "Country"],
  ["work_authorization", "Work authorization answer"], ["sponsorship", "Sponsorship answer"],
  ["relocation", "Willing to relocate"], ["salary", "Salary expectation"],
  ["availability", "Availability"], ["website", "Other website"],
  ["preferred_name", "Preferred name"], ["pronouns", "Pronouns"],
  ["veteran", "Veteran status (optional)"], ["disability", "Disability status (optional)"],
  ["gender", "Gender (optional)"], ["ethnicity", "Ethnicity (optional)"],
];
let appUrl = "";
let token = "";
let profile = null;
let answers = [];
let documents = [];
let page = null;
let tabId = null;
let pairingTimer = null;

function status(message) { $("status").textContent = message || ""; }

async function request(path, options = {}, authenticated = true) {
  const headers = { ...(options.headers || {}) };
  if (authenticated) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${appUrl}${path}`, { ...options, headers });
  const type = res.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await res.json() : null;
  if (!res.ok) throw new Error(data?.detail || `${res.status} ${res.statusText}`);
  return { data, response: res };
}

async function siteMessage(message) {
  if (tabId == null) throw new Error("Open a job application tab first");
  try {
    const result = await chrome.tabs.sendMessage(tabId, message);
    if (!result?.ok) throw new Error(result?.error || "This page cannot be filled");
    return result;
  } catch (error) {
    throw new Error(error.message || "Open a normal job application page");
  }
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  tabId = tab?.id ?? null;
  if (!tab?.url?.startsWith("http")) return;
  try { page = await siteMessage({ type: "GET_PAGE" }); }
  catch { page = null; }
  if (page) {
    $("company").value = page.job.company || "";
    $("title").value = page.job.title || "";
    for (const [kind, id] of [["resume", "resume-select"], ["cover", "cover-select"]]) {
      const match = documents.find((d) => d.kind === kind && d.label.toLowerCase().includes((page.job.company || "\u0000").toLowerCase())
        && d.label.toLowerCase().includes((page.job.title || "\u0000").toLowerCase()));
      if (match) $(id).value = match.id;
    }
    renderQuestions(page.questions);
    const tracked = (await chrome.storage.session.get(`tracked:${tabId}`))[`tracked:${tabId}`];
    if (tracked) $("fill-result").textContent = "Application tracked as applied.";
  }
}

function job() {
  if (!page) throw new Error("Open a job application page first");
  const company = $("company").value.trim();
  const title = $("title").value.trim();
  if (!company || !title) throw new Error("Enter the company and role first");
  return { ...page.job, company, title };
}

function renderDocuments() {
  for (const [kind, id] of [["resume", "resume-select"], ["cover", "cover-select"]]) {
    const select = $(id);
    select.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = `Choose ${kind === "resume" ? "resume" : "cover letter"}`;
    select.append(placeholder);
    for (const doc of documents.filter((entry) => entry.kind === kind)) {
      const option = document.createElement("option");
      option.value = doc.id;
      option.textContent = doc.label;
      select.append(option);
    }
    const uploaded = documents.find((entry) => entry.kind === kind && entry.id.startsWith("upload:"));
    if (uploaded) select.value = uploaded.id;
  }
}

function renderProfile() {
  const parent = $("extra-fields");
  parent.replaceChildren();
  for (const [key, labelText] of EXTRA) {
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement("input");
    input.dataset.key = key;
    input.value = profile.extra?.[key] || "";
    label.append(input);
    parent.append(label);
  }
}

async function generateDraft(prompt, question) {
  const { data } = await request("/api/extension/data/generate-answer", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, ...job(), word_limit: question.maxLength ? Math.max(20, Math.min(1000, Math.floor(question.maxLength / 6))) : null }),
  });
  return data.content;
}

function renderQuestions(questions, drafts = {}) {
  const parent = $("questions");
  parent.replaceChildren();
  if (!questions?.length) {
    parent.textContent = "No unanswered open questions detected.";
    return;
  }
  for (const question of questions) {
    const card = document.createElement("div");
    card.className = "question";
    const label = document.createElement("strong");
    label.textContent = question.label || "Application question";
    const promptInput = document.createElement("input");
    promptInput.value = question.label || "";
    promptInput.placeholder = "Type the question if it was not detected";
    const generate = document.createElement("button");
    generate.textContent = "Draft with AI";
    const editor = document.createElement("textarea");
    editor.placeholder = "Review the draft here before inserting";
    editor.value = drafts[question.id] || "";
    editor.hidden = !editor.value;
    const insert = document.createElement("button");
    insert.textContent = "Insert and save answer";
    insert.hidden = !editor.value;
    generate.onclick = async () => {
      try {
        if (promptInput.value.trim().length < 3) throw new Error("Enter the application question first");
        generate.disabled = true;
        status("Drafting an answer…");
        editor.value = await generateDraft(promptInput.value.trim(), question);
        editor.hidden = false;
        insert.hidden = false;
        status("");
      } catch (error) { status(error.message); }
      finally { generate.disabled = false; }
    };
    insert.onclick = async () => {
      try {
        if (!editor.value.trim()) throw new Error("Answer is empty");
        if (question.maxLength && editor.value.length > question.maxLength) throw new Error(`Answer exceeds ${question.maxLength} characters`);
        await siteMessage({ type: "INSERT_ANSWER", fieldId: question.id, content: editor.value.trim() });
        await request("/api/extension/data/answers", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: promptInput.value.trim(), content: editor.value.trim() }),
        });
        status("Answer inserted and saved.");
      } catch (error) { status(error.message); }
    };
    card.append(label, promptInput, generate, editor, insert);
    parent.append(card);
  }
}

async function loadWorkspace() {
  $("connect").hidden = true;
  $("workspace").hidden = false;
  const [p, a, d] = await Promise.all([
    request("/api/extension/data/profile"),
    request("/api/extension/data/answers"),
    request("/api/extension/data/documents"),
  ]);
  profile = p.data;
  answers = a.data;
  documents = d.data;
  $("account").textContent = profile.account;
  renderProfile();
  renderDocuments();
  await activeTab();
}

async function pollPairing() {
  const { deviceCode } = await chrome.storage.local.get("deviceCode");
  if (!deviceCode) return;
  try {
    const { data } = await request("/api/extension/pair/complete", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_code: deviceCode }),
    }, false);
    if (data.status === "connected") {
      token = data.token;
      await chrome.storage.local.set({ token });
      await chrome.storage.local.remove("deviceCode");
      clearInterval(pairingTimer);
      status("");
      await loadWorkspace();
    }
  } catch (error) {
    clearInterval(pairingTimer);
    await chrome.storage.local.remove("deviceCode");
    status(error.message);
  }
}

$("connect-button").onclick = async () => {
  try {
    appUrl = new URL($("app-url").value).origin;
    if (!/^https:\/\//.test(appUrl) && !/^http:\/\/localhost(?::\d+)?$/.test(appUrl)) throw new Error("Use HTTPS, or localhost for development");
    await chrome.storage.local.set({ appUrl });
    const { data } = await request("/api/extension/pair/start", { method: "POST" }, false);
    await chrome.storage.local.set({ deviceCode: data.device_code });
    $("pair-code").textContent = `Approve code ${data.user_code} in the opened tab, then return here.`;
    await chrome.tabs.create({ url: `${appUrl}/extension/connect?code=${data.user_code}` });
    pairingTimer = setInterval(pollPairing, 2000);
  } catch (error) { status(error.message); }
};

$("fill-button").onclick = async () => {
  try {
    status("");
    $("fill-button").disabled = true;
    const result = await siteMessage({ type: "AUTOFILL", profile, answers, job: job() });
    const drafts = {};
    const questionFailures = [];
    if ($("draft-questions").checked) {
      for (const question of result.questions.slice(0, 10)) {
        if (!question.label || question.label.length < 3) continue;
        try {
          status(`Drafting: ${question.label.slice(0, 50)}…`);
          const content = await generateDraft(question.label, question);
          drafts[question.id] = content;
          if (question.maxLength && content.length > question.maxLength) {
            questionFailures.push(`Answer for “${question.label}” is too long; edit it below.`);
            continue;
          }
          await siteMessage({ type: "INSERT_ANSWER", fieldId: question.id, content });
        } catch (error) { questionFailures.push(`${question.label}: ${error.message}`); }
      }
    }
    const attached = [];
    const failures = [];
    for (const kind of ["resume", "cover"]) {
      if (!$(kind === "resume" ? "resume-select" : "cover-select").value) continue;
      try { attached.push(await attach(kind, false)); }
      catch (error) { failures.push(`${kind}: ${error.message}`); }
    }
    $("fill-result").textContent = `Filled ${result.filled.length} saved fields, drafted ${Object.keys(drafts).length} answers, and attached ${attached.length} documents. Review the application before submitting. Check remaining fields. ${[...questionFailures, ...failures].join(" ")}`;
    renderQuestions(result.questions, drafts);
    status("");
  } catch (error) { status(error.message); }
  finally { $("fill-button").disabled = false; }
};

async function attach(kind, announce = true) {
  const id = $(kind === "resume" ? "resume-select" : "cover-select").value;
  if (!id) throw new Error(`Choose a ${kind === "resume" ? "resume" : "cover letter"}`);
  const { response } = await request(`/api/extension/data/documents/${encodeURIComponent(id)}`);
  const buffer = new Uint8Array(await response.arrayBuffer());
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
  const name = match ? decodeURIComponent(match[1].replace(/^"|"$/g, "")) : `${kind}.pdf`;
  await siteMessage({ type: "UPLOAD_START", kind, name, mime: response.headers.get("content-type") || "application/pdf" });
  for (let offset = 0; offset < buffer.length; offset += 128 * 1024) {
    await siteMessage({ type: "UPLOAD_CHUNK", bytes: Array.from(buffer.slice(offset, offset + 128 * 1024)) });
  }
  await siteMessage({ type: "UPLOAD_COMMIT" });
  if (announce) status(`${name} attached. Check that the application site accepted it.`);
  return name;
}
$("resume-upload").onclick = () => attach("resume").catch((error) => status(error.message));
$("cover-upload").onclick = () => attach("cover").catch((error) => status(error.message));

$("mark-applied").onclick = async () => {
  try {
    const { data } = await request("/api/extension/data/track", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...job(), submitted: true }),
    });
    status(`Tracked as applied (application #${data.id}).`);
  } catch (error) { status(error.message); }
};

$("save-profile").onclick = async () => {
  try {
    const extra = Object.fromEntries([...$("extra-fields").querySelectorAll("input")].map((input) => [input.dataset.key, input.value.trim()]));
    await request("/api/extension/data/profile", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ extra }),
    });
    profile.extra = extra;
    status("Application answers saved.");
  } catch (error) { status(error.message); }
};

$("save-documents").onclick = async () => {
  try {
    for (const [kind, id] of [["resume", "new-resume"], ["cover", "new-cover"]]) {
      const file = $(id).files?.[0];
      if (!file) continue;
      const form = new FormData();
      form.append("file", file);
      await request(`/api/extension/data/documents?kind=${kind}`, { method: "POST", body: form });
    }
    documents = (await request("/api/extension/data/documents")).data;
    renderDocuments();
    status("Documents uploaded.");
  } catch (error) { status(error.message); }
};

$("disconnect").onclick = async () => {
  try { await request("/api/extension/data/disconnect", { method: "POST" }); } catch {}
  await chrome.storage.local.remove(["token", "deviceCode"]);
  token = "";
  $("workspace").hidden = true;
  $("connect").hidden = false;
  status("Extension disconnected.");
};

for (const button of document.querySelectorAll("[data-tab]")) {
  button.onclick = () => {
    for (const other of document.querySelectorAll("[data-tab]")) other.classList.toggle("selected", other === button);
    for (const name of ["apply", "profile", "documents"]) $(`${name}-tab`).hidden = name !== button.dataset.tab;
  };
}

(async () => {
  const saved = await chrome.storage.local.get({ appUrl: "https://applination.sanchitarora.me", token: "", deviceCode: "" });
  appUrl = saved.appUrl.replace(/\/$/, "");
  token = saved.token;
  $("app-url").value = appUrl;
  if (!token) {
    $("connect").hidden = false;
    if (saved.deviceCode) pairingTimer = setInterval(pollPairing, 2000);
    return;
  }
  try { await loadWorkspace(); }
  catch (error) {
    status(error.message);
    if (/connected|401|expired/i.test(error.message)) {
      await chrome.storage.local.remove("token");
      token = "";
      $("workspace").hidden = true;
      $("connect").hidden = false;
    }
  }
})();
