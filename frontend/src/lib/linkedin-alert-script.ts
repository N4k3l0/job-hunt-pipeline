/**
 * The Google Apps Script a user runs in the Gmail account that receives
 * their LinkedIn job alerts. It sends new alert emails to the backend
 * (POST /api/v1/job-alerts/linkedin) with the user's alert key.
 *
 * Run by an admin, that Gmail also becomes the shared inbox other users
 * forward their alerts to (backend services/job_alerts/forwarding.py): the
 * script sends the addresses each email was delivered to, and Gmail's
 * forwarding confirmation emails, so the backend can tell whose they are.
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
 * Job Hunt: jobs from LinkedIn job alerts, on the dashboard.
 *
 * Every 10 minutes this reads new emails from jobalerts-noreply@linkedin.com
 * in this Gmail account and sends them to Job Hunt, which adds their jobs to
 * the dashboard. It also sends Gmail's forwarding confirmation emails, so
 * people who forward their alerts here can see their code in Job Hunt. No
 * other email is read. Links are sent without LinkedIn's tracking and
 * sign-in codes.
 *
 * To start: pick "setUp" in the menu next to Run above, then press Run.
 * To stop: delete this project, or remove the key on your Job Hunt profile.
 */
const JOB_HUNT_URL = ${JSON.stringify(url)};
const JOB_HUNT_KEY = ${JSON.stringify(key)};
const ALERT_SENDER = "jobalerts-noreply@linkedin.com";
const FORWARDING_SENDER = "forwarding-noreply@google.com";

function setUp() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === "syncLinkedInAlerts") ScriptApp.deleteTrigger(trigger);
  });
  ScriptApp.newTrigger("syncLinkedInAlerts").timeBased().everyMinutes(10).create();
  syncLinkedInAlerts();
}

function syncLinkedInAlerts() {
  const properties = PropertiesService.getUserProperties();
  const sent = JSON.parse(properties.getProperty("sentMessageIds") || "[]");
  const pending = [];
  function collect(query, sender, kind) {
    GmailApp.search(query, 0, 100).forEach(function (thread) {
      thread.getMessages().forEach(function (message) {
        if (message.getFrom().indexOf(sender) === -1) return;
        if (sent.indexOf(message.getId()) !== -1) return;
        pending.push({ message: message, kind: kind });
      });
    });
  }
  collect("from:" + ALERT_SENDER + " newer_than:7d", ALERT_SENDER, "alert");
  collect("from:" + FORWARDING_SENDER + " newer_than:3d", FORWARDING_SENDER, "confirmation");
  if (!pending.length) {
    console.log("No new LinkedIn job alert emails.");
    return;
  }
  const inbox = Session.getEffectiveUser().getEmail();
  for (let i = 0; i < pending.length; i += 10) {
    const batch = pending.slice(i, i + 10);
    const response = UrlFetchApp.fetch(JOB_HUNT_URL, {
      method: "post",
      contentType: "application/json",
      headers: { Authorization: "Bearer " + JOB_HUNT_KEY },
      payload: JSON.stringify({
        inbox: inbox,
        messages: batch.map(function (item) {
          const message = item.message;
          const entry = {
            message_id: message.getId(),
            received_at: message.getDate().toISOString(),
            kind: item.kind,
            recipients: recipientsOf(message),
          };
          if (item.kind === "alert") {
            entry.html = withoutLinkCodes(message.getBody());
          } else {
            entry.subject = message.getSubject();
            entry.text = message.getPlainBody().slice(0, 5000);
          }
          return entry;
        }),
      }),
      muteHttpExceptions: true,
    });
    if (response.getResponseCode() !== 200) {
      console.error("Job Hunt answered " + response.getResponseCode() + ": " + response.getContentText().slice(0, 300));
      return;
    }
    batch.forEach(function (item) { sent.push(item.message.getId()); });
    properties.setProperty("sentMessageIds", JSON.stringify(sent.slice(-300)));
    console.log("Sent " + batch.length + " emails: " + response.getContentText());
  }
}

// The addresses Gmail delivered the email to. For an alert someone
// forwarded here, one of them has their code after a plus.
function recipientsOf(message) {
  const head = message.getRawContent().replace(/\\r/g, "").split("\\n\\n")[0].replace(/\\n[ \\t]+/g, " ");
  return head.split("\\n").filter(function (line) {
    return /^(delivered-to|x-forwarded-to|x-forwarded-for|to):/i.test(line);
  }).map(function (line) { return line.slice(0, 300); }).slice(0, 10);
}

function withoutLinkCodes(html) {
  return html.replace(/(https?:\\/\\/[^"'\\s<>?]+)\\?([^"'\\s<>]*)/g, function (match, base, query) {
    const trk = query.split(/&(?:amp;)?/).filter(function (part) { return part.indexOf("trk=") === 0; })[0];
    return trk ? base + "?" + trk : base;
  });
}
`;
}
