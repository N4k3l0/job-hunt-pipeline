// Job Hunt extension, on the Job Hunt app: lets the app page know the
// extension is installed and pass it an approved application to fill in.
//
// The page posts { jobHunt: "to-extension", requestId, type, ... } and gets
// { jobHunt: "from-extension", requestId, ... } back.

const ALLOWED = new Set(["ping", "fill-form"]);

function toPage(message) {
  window.postMessage({ jobHunt: "from-extension", ...message }, location.origin);
}

window.addEventListener("message", async (event) => {
  if (event.source !== window || event.origin !== location.origin) return;
  const data = event.data;
  if (!data || data.jobHunt !== "to-extension" || !ALLOWED.has(data.type)) return;
  let reply;
  try {
    reply = await chrome.runtime.sendMessage({ type: data.type, application: data.application });
  } catch (error) {
    reply = { error: String((error && error.message) || error) };
  }
  toPage({ requestId: data.requestId, ...(reply || {}) });
});

toPage({ type: "hello", version: chrome.runtime.getManifest().version });
