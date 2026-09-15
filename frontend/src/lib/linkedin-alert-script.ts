/**
 * The Google Apps Script a user runs in the Gmail account that receives
 * their LinkedIn job alerts. It sends new alert emails to the backend
 * (POST /api/v1/job-alerts/linkedin) with the user's alert key.
 *
 * The backend reads the jobs out of each email (services/job_alerts), so
 * changes to LinkedIn's layout are fixed there, not in every user's copy
 * of this script. Links lose their query strings, which carry LinkedIn's
 * tracking and one-time sign-in codes, except `trk`: it names each job's
 * place in the email.
 */
export function buildLinkedInAlertScript(apiBase: string, key: string): string {
  const url = `${apiBase.replace(/\/$/, "")}/api/v1/job-alerts/linkedin`;
  return `/**
 * Job Hunt: jobs from your LinkedIn job alerts, on your dashboard.
 *
 * Every hour this reads new emails from jobalerts-noreply@linkedin.com in
 * this Gmail account and sends them to Job Hunt, which adds their jobs to
 * your dashboard. No other email is read. Links are sent without
 * LinkedIn's tracking and sign-in codes.
 *
 * To start: pick "setUp" in the menu next to Run above, then press Run.
 * To stop: delete this project, or remove the key on your Job Hunt profile.
 */
const JOB_HUNT_URL = ${JSON.stringify(url)};
const JOB_HUNT_KEY = ${JSON.stringify(key)};
const ALERT_SENDER = "jobalerts-noreply@linkedin.com";

function setUp() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === "syncLinkedInAlerts") ScriptApp.deleteTrigger(trigger);
  });
  ScriptApp.newTrigger("syncLinkedInAlerts").timeBased().everyHours(1).create();
  syncLinkedInAlerts();
}

function syncLinkedInAlerts() {
  const properties = PropertiesService.getUserProperties();
  const sent = JSON.parse(properties.getProperty("sentMessageIds") || "[]");
  const pending = [];
  GmailApp.search("from:" + ALERT_SENDER + " newer_than:7d", 0, 100).forEach(function (thread) {
    thread.getMessages().forEach(function (message) {
      if (message.getFrom().indexOf(ALERT_SENDER) === -1) return;
      if (sent.indexOf(message.getId()) !== -1) return;
      pending.push(message);
    });
  });
  if (!pending.length) {
    console.log("No new LinkedIn job alert emails.");
    return;
  }
  for (let i = 0; i < pending.length; i += 10) {
    const batch = pending.slice(i, i + 10);
    const response = UrlFetchApp.fetch(JOB_HUNT_URL, {
      method: "post",
      contentType: "application/json",
      headers: { Authorization: "Bearer " + JOB_HUNT_KEY },
      payload: JSON.stringify({
        messages: batch.map(function (message) {
          return {
            message_id: message.getId(),
            received_at: message.getDate().toISOString(),
            html: withoutLinkCodes(message.getBody()),
          };
        }),
      }),
      muteHttpExceptions: true,
    });
    if (response.getResponseCode() !== 200) {
      console.error("Job Hunt answered " + response.getResponseCode() + ": " + response.getContentText().slice(0, 300));
      return;
    }
    batch.forEach(function (message) { sent.push(message.getId()); });
    properties.setProperty("sentMessageIds", JSON.stringify(sent.slice(-300)));
    console.log("Sent " + batch.length + " alert emails: " + response.getContentText());
  }
}

function withoutLinkCodes(html) {
  return html.replace(/(https?:\\/\\/[^"'\\s<>?]+)\\?([^"'\\s<>]*)/g, function (match, base, query) {
    const trk = query.split(/&(?:amp;)?/).filter(function (part) { return part.indexOf("trk=") === 0; })[0];
    return trk ? base + "?" + trk : base;
  });
}
`;
}
