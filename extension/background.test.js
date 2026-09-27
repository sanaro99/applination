const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("tracks only after an armed submission is confirmed", async () => {
  const local = { appUrl: "https://applination.example", token: "test-token" };
  const session = {};
  const requests = [];
  let listener;
  const storage = (values) => ({
    setAccessLevel: async () => {},
    get: async (keys) => {
      if (typeof keys === "string") return { [keys]: values[keys] };
      if (Array.isArray(keys)) return Object.fromEntries(keys.map((key) => [key, values[key]]));
      return { ...keys, ...values };
    },
    set: async (entries) => Object.assign(values, entries),
    remove: async (keys) => { for (const key of Array.isArray(keys) ? keys : [keys]) delete values[key]; },
  });
  const chrome = {
    storage: { local: storage(local), session: storage(session) },
    runtime: { onMessage: { addListener: (fn) => { listener = fn; } } },
    tabs: { onRemoved: { addListener: () => {} } },
  };
  const fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => ({ id: 12, status: "applied" }) };
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "background.js"), "utf8"),
    { chrome, fetch, Date, Error });
  const send = (message) => new Promise((resolve) => listener(message, { tab: { id: 7 } }, resolve));
  assert.equal((await send({ type: "FORM_SUBMITTED" })).ok, false);
  assert.equal(requests.length, 0);
  const job = { url: "https://boards.example/jobs/123", company: "Acme", title: "Engineer" };
  assert.equal((await send({ type: "ARM_APPLICATION", job })).ok, true);
  assert.equal((await send({ type: "FORM_SUBMITTED" })).ok, true);
  assert.equal(requests.length, 0);
  assert.equal((await send({ type: "APPLICATION_CONFIRMED" })).ok, true);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.headers.Authorization, "Bearer test-token");
  assert.equal(JSON.parse(requests[0].options.body).submitted, true);
  assert.equal((await send({ type: "APPLICATION_CONFIRMED" })).ok, false);
  assert.equal(requests.length, 1);
});

test("drafts answers and streams generated documents through the trusted background", async () => {
  const local = { appUrl: "https://applination.example", token: "test-token" };
  const requests = [];
  const pageMessages = [];
  let listener;
  const chrome = {
    storage: {
      local: {
        setAccessLevel: async () => {},
        get: async () => local,
      },
    },
    runtime: { onMessage: { addListener: (fn) => { listener = fn; } } },
    tabs: {
      sendMessage: async (tabId, message) => {
        pageMessages.push({ tabId, message });
        return { ok: true };
      },
      onRemoved: { addListener: () => {} },
    },
  };
  const fetch = async (url, options) => {
    requests.push({ url, options });
    if (url.endsWith("/generate-answer")) return {
      ok: true, json: async () => ({ content: "A specific answer" }),
    };
    return {
      ok: true,
      headers: { get: (key) => ({
        "content-disposition": 'attachment; filename="tailored.pdf"',
        "content-type": "application/pdf",
      })[key] },
      arrayBuffer: async () => Uint8Array.from([37, 80, 68, 70]).buffer,
    };
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "background.js"), "utf8"),
    { chrome, fetch, Date, Error });
  const send = (message) => new Promise((resolve) => listener(message, { tab: { id: 7 } }, resolve));
  const answer = await send({ type: "GENERATE_ANSWER", question: { prompt: "Why this role?" } });
  assert.equal(answer.content, "A specific answer");
  assert.equal(requests[0].options.headers.Authorization, "Bearer test-token");
  assert.equal(JSON.parse(requests[0].options.body).prompt, "Why this role?");

  const attached = await send({ type: "ATTACH_DOCUMENT", documentId: "app:12:resume", kind: "resume" });
  assert.equal(attached.filename, "tailored.pdf");
  assert.equal(requests[1].options.headers.Authorization, "Bearer test-token");
  assert.deepEqual(pageMessages.map(({ message }) => message.type),
    ["UPLOAD_START", "UPLOAD_CHUNK", "UPLOAD_COMMIT"]);
  assert.deepEqual(Array.from(pageMessages[1].message.bytes), [37, 80, 68, 70]);
  assert.ok(pageMessages.every(({ tabId }) => tabId === 7));

  const invalid = await send({ type: "ATTACH_DOCUMENT", documentId: "app:12:cover", kind: "resume" });
  assert.equal(invalid.ok, false);
  assert.equal(requests.length, 2);
});
