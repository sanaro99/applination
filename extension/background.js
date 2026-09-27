const PENDING_TTL_MS = 10 * 60 * 1000;
// Content scripts do not need the account credential stored by the popup.
chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });

async function settings() {
  return chrome.storage.local.get({ appUrl: "https://applination.sanchitarora.me", token: "" });
}

async function extensionRequest(path, options = {}) {
  const { appUrl, token } = await settings();
  if (!token) throw new Error("Connect Applination before filling this page");
  const response = await fetch(`${appUrl}${path}`, {
    ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Applination request failed (${response.status})`);
  }
  return response;
}

async function attachDocument(tabId, documentId, kind) {
  if (!/^app:\d+:(resume|cover)$/.test(documentId) || !documentId.endsWith(`:${kind}`)) {
    throw new Error("Invalid generated document");
  }
  const response = await extensionRequest(`/api/extension/data/documents/${encodeURIComponent(documentId)}`);
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
  const name = match ? decodeURIComponent(match[1].replace(/^"|"$/g, "")) : `${kind}.pdf`;
  const buffer = new Uint8Array(await response.arrayBuffer());
  const send = async (message) => {
    const result = await chrome.tabs.sendMessage(tabId, message);
    if (!result?.ok) throw new Error(result?.error || "The page rejected the upload");
    return result;
  };
  await send({ type: "UPLOAD_START", kind, name, mime: response.headers.get("content-type") || "application/pdf" });
  for (let offset = 0; offset < buffer.length; offset += 128 * 1024) {
    await send({ type: "UPLOAD_CHUNK", bytes: Array.from(buffer.slice(offset, offset + 128 * 1024)) });
  }
  await send({ type: "UPLOAD_COMMIT" });
  return name;
}

async function track(job) {
  const { appUrl, token } = await settings();
  if (!token) return false;
  const response = await fetch(`${appUrl}/api/extension/data/track`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ ...job, submitted: true }),
  });
  if (!response.ok) throw new Error(`Tracking failed (${response.status})`);
  return response.json();
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    const tabId = sender.tab?.id;
    if (tabId == null) return { ok: false };
    if (message.type === "GENERATE_ANSWER") {
      const response = await extensionRequest("/api/extension/data/generate-answer", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(message.question),
      });
      const data = await response.json();
      return { ok: true, content: data.content };
    }
    if (message.type === "ATTACH_DOCUMENT") {
      return { ok: true, filename: await attachDocument(tabId, message.documentId, message.kind) };
    }
    if (message.type === "ARM_APPLICATION") {
      await chrome.storage.session.set({ [`armed:${tabId}`]: { job: message.job, at: Date.now() } });
      return { ok: true };
    }
    if (message.type === "FORM_SUBMITTED") {
      const key = `armed:${tabId}`;
      const armed = (await chrome.storage.session.get(key))[key];
      if (!armed || Date.now() - armed.at > PENDING_TTL_MS) return { ok: false };
      await chrome.storage.session.set({ [`pending:${tabId}`]: armed });
      return { ok: true };
    }
    if (message.type === "APPLICATION_CONFIRMED") {
      const key = `pending:${tabId}`;
      const pending = (await chrome.storage.session.get(key))[key];
      if (!pending || Date.now() - pending.at > PENDING_TTL_MS) return { ok: false };
      const tracked = await track(pending.job);
      await chrome.storage.session.remove([key, `armed:${tabId}`]);
      await chrome.storage.session.set({ [`tracked:${tabId}`]: tracked });
      return { ok: true, tracked };
    }
    return { ok: false };
  })().then(sendResponse, (error) => sendResponse({ ok: false, error: String(error) }));
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove([`armed:${tabId}`, `pending:${tabId}`, `tracked:${tabId}`, `generation:${tabId}`]);
});
