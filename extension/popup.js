const $ = (id) => document.getElementById(id);
let appUrl = "";
let token = "";
let profile = null;
let answers = [];
let page = null;
let tabId = null;
let generation = null;
let resumeFile = null;
let previewUrl = null;
let pollTimer = null;
let pairingTimer = null;
let fillTimer = null;

function status(message) {
  $("status").textContent = message || "";
  $("status").hidden = !message;
}

async function request(path, options = {}, authenticated = true) {
  const headers = { ...(options.headers || {}) };
  if (authenticated) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${appUrl}${path}`, { ...options, headers });
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status})`);
  return { data, response };
}

async function siteMessage(message) {
  if (tabId == null) throw new Error("Open a job application tab first");
  try {
    const result = await chrome.tabs.sendMessage(tabId, message);
    if (!result?.ok) throw new Error(result?.error || "This page could not be filled");
    return result;
  } catch (error) {
    throw new Error(error.message || "Open a normal job application page");
  }
}

function job() {
  if (!page?.isApplication) throw new Error("Open a job application first");
  return page.job;
}

function contextReady() {
  const current = page?.job;
  return Boolean(current?.company?.trim() && current?.title?.trim() && current?.description?.trim());
}

function generationState(label, detail, tone = "") {
  $("generation-state").textContent = label;
  $("generation-state").className = `state ${tone}`;
  $("generation-detail").textContent = detail;
}

function renderPage() {
  const detected = Boolean(page?.isApplication);
  $("no-page").hidden = detected;
  $("job-card").hidden = !detected;
  $("resume-card").hidden = !detected;
  $("apply-card").hidden = !detected;
  if (!detected) return;
  $("job-title").textContent = page.job.title || "Application form";
  $("job-company").textContent = page.job.company || new URL(page.job.url).hostname;
  $("field-count").textContent = page.fields.length;
  $("required-count").textContent = page.fields.filter((field) => field.required).length;
  $("question-count").textContent = page.questions.length;
  const missing = [!page.job.company && "company", !page.job.title && "role", !page.job.description && "job description"].filter(Boolean);
  $("context-warning").hidden = !missing.length;
  $("context-warning").textContent = missing.length
    ? `This page does not expose the ${missing.join(", ")}. Resume generation needs those job details.` : "";
  $("fill-button").disabled = !page.job.company || !page.job.title;
  if (!contextReady()) generationState("Needs details", "Open a page that shows the job description and application form.", "error");
  else if (!generation) generationState("Not started", "Click Autofill application to tailor your resume.");
}

async function scanPage() {
  clearTimeout(pollTimer);
  clearTimeout(fillTimer);
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  generation = null;
  resumeFile = null;
  $("preview-wrap").hidden = true;
  $("resume-actions").hidden = true;
  $("mark-applied").hidden = true;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  tabId = tab?.id ?? null;
  page = null;
  if (tab?.url?.startsWith("http")) {
    try { page = await siteMessage({ type: "GET_PAGE" }); } catch { /* Unsupported tab. */ }
  }
  renderPage();
  if (!page?.isApplication) return;
  const key = `generation:${tabId}`;
  const saved = (await chrome.storage.session.get(key))[key];
  generation = saved?.url === page.job.url ? saved : null;
  if (generation) await pollGeneration();
}

async function startGeneration() {
  if (!contextReady()) return;
  try {
    generationState("Generating", "Tailoring your resume from this job description and your profile…");
    const { data } = await request("/api/extension/data/generate-resume", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(job()),
    });
    generation = { runId: data.run_id, url: page.job.url, fillPending: true };
    await chrome.storage.session.set({ [`generation:${tabId}`]: generation });
    await pollGeneration();
  } catch (error) {
    generationState("Unavailable", error.message, "error");
    status(error.message);
  }
}

async function pollGeneration() {
  if (!generation) return;
  clearTimeout(pollTimer);
  try {
    const { data } = await request(`/api/extension/data/generate-resume/${generation.runId}`);
    if (data.status === "error" || data.error) {
      generation.runFailed = true;
      await chrome.storage.session.set({ [`generation:${tabId}`]: generation });
      throw new Error(data.error || "Resume generation failed");
    }
    if (data.status !== "done") {
      generationState("Generating", "You can close this popup. Your resume will appear when you reopen it.");
      pollTimer = setTimeout(pollGeneration, 2500);
      return;
    }
    generation.applicationId = data.application_id;
    generation.resumeId = data.resume_id;
    generation.coverId = data.cover_id;
    await chrome.storage.session.set({ [`generation:${tabId}`]: generation });
    await loadResume();
    if (generation.fillPending) {
      generation.fillPending = false;
      await chrome.storage.session.set({ [`generation:${tabId}`]: generation });
      await fillForm();
    } else await pollFillProgress();
  } catch (error) {
    clearTimeout(pollTimer);
    generationState("Unavailable", error.message, "error");
    status(error.message);
  }
}

async function documentFile(id) {
  const { response } = await request(`/api/extension/data/documents/${encodeURIComponent(id)}`);
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
  const name = match ? decodeURIComponent(match[1].replace(/^"|"$/g, "")) : "resume.pdf";
  return { blob, name, mime: response.headers.get("content-type") || blob.type };
}

async function loadResume() {
  if (!generation?.resumeId) throw new Error("The generated resume is unavailable");
  resumeFile = await documentFile(generation.resumeId);
  generationState("Ready", "Your tailored resume is ready. Review the form before submitting.", "ready");
  $("resume-actions").hidden = false;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(resumeFile.blob);
  const pdf = resumeFile.mime.includes("pdf") || resumeFile.name.toLowerCase().endsWith(".pdf");
  $("preview-wrap").hidden = !pdf;
  $("mark-applied").hidden = false;
  if (pdf) $("resume-preview").src = previewUrl;
}

async function pollFillProgress() {
  clearTimeout(fillTimer);
  fillTimer = null;
  const progress = await siteMessage({ type: "GET_PROGRESS" });
  if (!progress.started) return;
  if (progress.running) {
    $("fill-button").disabled = true;
    $("fill-button").textContent = "Filling application…";
    $("fill-result").textContent = `${progress.stage || "Filling fields"} — ${progress.filled} filled so far. Follow progress on the application page.`;
    fillTimer = setTimeout(() => pollFillProgress().catch((error) => status(error.message)), 700);
    return;
  }
  $("fill-button").disabled = false;
  $("fill-button").innerHTML = 'Autofill application <span aria-hidden="true">→</span>';
  page = await siteMessage({ type: "GET_PAGE" });
  const remaining = page.fields.filter((field) => field.required && !field.filled).length;
  $("fill-result").textContent = progress.cancelled
    ? "Autofill stopped. Review the fields that were filled."
    : `${progress.filled} fields filled; ${remaining} required fields still need review. Review the form before submitting.${progress.error ? ` ${progress.error}` : ""}`;
  renderPage();
}

async function loadWorkspace() {
  $("connect").hidden = true;
  $("workspace").hidden = false;
  const [profileResult, answerResult] = await Promise.all([
    request("/api/extension/data/profile"), request("/api/extension/data/answers"),
  ]);
  profile = profileResult.data;
  answers = answerResult.data;
  $("account").textContent = profile.account;
  await scanPage();
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
    if (!/^https:\/\//.test(appUrl) && !/^http:\/\/localhost(?::\d+)?$/.test(appUrl)) {
      throw new Error("Use HTTPS, or localhost for development");
    }
    await chrome.storage.local.set({ appUrl });
    const { data } = await request("/api/extension/pair/start", { method: "POST" }, false);
    await chrome.storage.local.set({ deviceCode: data.device_code });
    $("pair-code").textContent = `Approve code ${data.user_code} in the opened tab, then return here.`;
    await chrome.tabs.create({ url: `${appUrl}/extension/connect?code=${data.user_code}` });
    pairingTimer = setInterval(pollPairing, 2000);
  } catch (error) { status(error.message); }
};

$("refresh-page").onclick = () => scanPage().catch((error) => status(error.message));
$("fill-button").onclick = async () => {
  try {
    const current = await siteMessage({ type: "GET_PAGE" });
    if (current.job.url !== page?.job.url) {
      await scanPage();
      throw new Error("The application page changed. Review the detected job and click Autofill again.");
    }
    page = current;
  } catch (error) { status(error.message); return; }
  if (!contextReady()) { status("The job description is needed to tailor a resume."); return; }
  if (!generation?.resumeId) {
    if (generation?.runId && !generation.runFailed) {
      generation.fillPending = true;
      await chrome.storage.session.set({ [`generation:${tabId}`]: generation });
      await pollGeneration();
    } else await startGeneration();
    return;
  }
  await fillForm();
};

async function fillForm() {
  try {
    status("");
    $("fill-button").disabled = true;
    $("fill-button").textContent = "Filling application…";
    $("fill-result").textContent = "Starting the progress panel on the application page…";
    const refreshed = await siteMessage({ type: "GET_PAGE" });
    if (refreshed.job.url !== page.job.url) throw new Error("The application page changed. Scan it again first.");
    page = refreshed;
    await siteMessage({ type: "AUTOFILL", profile, answers,
      job: { ...job(), application_id: generation?.applicationId || null },
      resumeId: generation?.resumeId || null, coverId: generation?.coverId || null });
    await pollFillProgress();
  } catch (error) { status(error.message); }
  finally { if (!fillTimer) $("fill-button").disabled = false; }
}

$("download-resume").onclick = () => {
  if (!resumeFile || !previewUrl) return;
  const link = document.createElement("a");
  link.href = previewUrl;
  link.download = resumeFile.name;
  link.click();
};
$("open-application").onclick = () => {
  if (generation?.applicationId) chrome.tabs.create({ url: `${appUrl}/applications/${generation.applicationId}` });
};
$("edit-profile").onclick = () => chrome.tabs.create({ url: `${appUrl}/application-profile` });
$("mark-applied").onclick = async () => {
  try {
    const { data } = await request("/api/extension/data/track", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...job(), application_id: generation?.applicationId || null, submitted: true }),
    });
    $("fill-result").textContent = `Tracked as applied (application #${data.id}).`;
  } catch (error) { status(error.message); }
};
$("disconnect").onclick = async () => {
  try { await request("/api/extension/data/disconnect", { method: "POST" }); } catch { /* Clear local credential regardless. */ }
  await chrome.storage.local.remove(["token", "deviceCode"]);
  token = "";
  $("workspace").hidden = true;
  $("connect").hidden = false;
  status("Extension disconnected.");
};

window.addEventListener("unload", () => {
  clearTimeout(pollTimer);
  clearTimeout(fillTimer);
  clearInterval(pairingTimer);
  if (previewUrl) URL.revokeObjectURL(previewUrl);
});

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
