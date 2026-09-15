// Job Hunt extension, on Greenhouse, Lever and Ashby pages: asks whether
// this tab was opened to fill in an application, hands the answers to
// fill.js (which runs in the page's own world), and reports when the
// company's form accepts the application.

const JOB_ID = /(\d{5,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i;
const SUCCESS_TEXT = /thank you for (applying|your application|your interest)|thanks for applying|application (has been |was )?(successfully )?(submitted|received)/i;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function toPage(message) {
  window.postMessage({ jobHunt: "to-page", ...message }, location.origin);
}

async function ask(message) {
  try {
    return (await chrome.runtime.sendMessage(message)) || {};
  } catch {
    return {};
  }
}

function fillerReady() {
  return new Promise((resolve) => {
    const done = (ready) => {
      window.removeEventListener("message", listener);
      resolve(ready);
    };
    const listener = (event) => {
      if (event.source === window && event.data && event.data.jobHunt === "filler-ready") done(true);
    };
    window.addEventListener("message", listener);
    toPage({ type: "hello" });
    setTimeout(() => done(false), 5000);
  });
}

function onConfirmationPage() {
  return /\/(confirmation|thanks)\/?$/.test(location.pathname);
}

function looksSent() {
  if (onConfirmationPage()) return true;
  if (document.querySelector(".ashby-application-form-success-container")) return true;
  const form = document.querySelector("#application-form, #application_form, [data-field-path]");
  return !form && SUCCESS_TEXT.test(document.body ? document.body.innerText : "");
}

async function reportSent() {
  await ask({ type: "sent" });
  toPage({ type: "sent" });
}

// After the user presses Submit, watch for the form going away and a thank
// you message, or a move to the confirmation page (seen on the next load).
function watchForSubmit() {
  let watching = false;
  const start = async () => {
    if (watching) return;
    watching = true;
    await ask({ type: "submit-clicked" });
    for (let i = 0; i < 120; i++) {
      await sleep(1000);
      if (looksSent()) {
        await reportSent();
        return;
      }
    }
    watching = false;
  };
  document.addEventListener("submit", start, true);
  document.addEventListener(
    "click",
    (event) => {
      const button = event.target instanceof Element && event.target.closest("button, input[type=submit]");
      if (button && /submit/i.test(button.textContent || button.value || "")) start();
    },
    true,
  );
}

(async () => {
  let reply = await ask({ type: "form-page" });
  // The tab can load before the extension has finished saving the application.
  for (let i = 0; i < 8 && !reply.application; i++) {
    await sleep(500);
    reply = await ask({ type: "form-page" });
  }
  const { application, resume } = reply;
  if (!application) return;

  const jobId = (new URL(application.form_url).pathname.match(JOB_ID) || [])[0];
  if (!jobId || !location.pathname.includes(jobId)) return;
  if (!(await fillerReady())) return;

  if (reply.sent) {
    toPage({ type: "sent" });
    return;
  }
  if (reply.submitClicked && looksSent()) {
    await reportSent();
    return;
  }
  // The page only needs the questions and answers, not the report link.
  const { sent_url: _url, sent_token: _token, ...forPage } = application;
  toPage({ type: "fill", application: forPage, resume });
  watchForSubmit();
})();
