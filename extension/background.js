// Job Hunt extension: the service worker.
//
// The app page hands over an approved application ("fill-form"). This opens
// the company's form in a new tab and remembers the application for that
// tab, so the form page can ask for it ("form-page") and report when the
// form was sent ("submit-clicked", "sent").

const FORM_HOSTS = [
  "job-boards.greenhouse.io",
  "job-boards.eu.greenhouse.io",
  "boards.greenhouse.io",
  "boards.eu.greenhouse.io",
  "jobs.lever.co",
  "jobs.eu.lever.co",
  "jobs.ashbyhq.com",
];
const APP_ORIGINS = ["https://jobhuntpipeline.vercel.app", "http://localhost:3000"];
const MAX_RESUME_BYTES = 8 * 1024 * 1024;

const tabKey = (tabId) => `tab:${tabId}`;

async function getEntry(tabId) {
  const key = tabKey(tabId);
  return (await chrome.storage.session.get(key))[key] || null;
}

async function saveEntry(tabId, entry) {
  try {
    await chrome.storage.session.set({ [tabKey(tabId)]: entry });
  } catch {
    // Too big to keep with the resume attached: keep the answers.
    await chrome.storage.session.set({ [tabKey(tabId)]: { ...entry, resume: null, coverLetter: null } });
  }
}

function isFormUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && FORM_HOSTS.includes(parsed.hostname);
  } catch {
    return false;
  }
}

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

async function downloadFile(resume) {
  if (!resume || !resume.url) return null;
  try {
    const response = await fetch(resume.url);
    if (!response.ok) return null;
    const buffer = await response.arrayBuffer();
    if (buffer.byteLength > MAX_RESUME_BYTES) return null;
    return { name: resume.filename, type: resume.content_type, base64: toBase64(buffer) };
  } catch {
    return null;
  }
}

async function openForm(application, sender) {
  const origin = sender.origin || (sender.url && new URL(sender.url).origin);
  if (!APP_ORIGINS.includes(origin)) throw new Error("Not the Job Hunt app");
  if (!application || !isFormUrl(application.form_url) || !Array.isArray(application.fields)) {
    throw new Error("This application can't be filled in");
  }
  // Fetch the files first: their links only work for a few minutes.
  const [resume, coverLetter] = await Promise.all([
    downloadFile(application.resume),
    downloadFile(application.cover_letter),
  ]);
  const tab = await chrome.tabs.create({
    url: application.form_url,
    index: sender.tab ? sender.tab.index + 1 : undefined,
    openerTabId: sender.tab ? sender.tab.id : undefined,
  });
  await saveEntry(tab.id, { application, resume, coverLetter, submitClicked: false, sent: false });
  return { ok: true };
}

async function reportSent(tabId) {
  const entry = await getEntry(tabId);
  if (!entry) return { ok: false };
  if (!entry.sent) {
    entry.sent = true;
    await saveEntry(tabId, entry);
    const { sent_url: url, sent_token: token } = entry.application;
    if (url) {
      try {
        await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
      } catch {
        // The user can still press "I sent it" in the app.
      }
    }
  }
  return { ok: true };
}

async function handle(message, sender) {
  const tabId = sender.tab && sender.tab.id;
  switch (message && message.type) {
    case "ping":
      return { ok: true, version: chrome.runtime.getManifest().version };
    case "fill-form":
      return openForm(message.application, sender);
    case "form-page": {
      const entry = tabId !== undefined ? await getEntry(tabId) : null;
      if (!entry) return {};
      return {
        application: entry.application,
        resume: entry.resume,
        coverLetter: entry.coverLetter,
        sent: entry.sent,
        submitClicked: entry.submitClicked,
      };
    }
    case "submit-clicked": {
      const entry = await getEntry(tabId);
      if (entry && !entry.submitClicked) await saveEntry(tabId, { ...entry, submitClicked: true });
      return { ok: true };
    }
    case "sent":
      return reportSent(tabId);
    default:
      return { error: "Unknown message" };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handle(message, sender).then(sendResponse, (error) => sendResponse({ error: String(error.message || error) }));
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(tabKey(tabId));
});
