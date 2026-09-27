const PENDING_TTL_MS = 10 * 60 * 1000;
// Content scripts do not need the account credential stored by the popup.
chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });

async function settings() {
  return chrome.storage.local.get({ appUrl: "https://applination.sanchitarora.me", token: "" });
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
