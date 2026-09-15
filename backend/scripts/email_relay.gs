/**
 * Job Hunt email relay: sends the app's emails with this Gmail account.
 *
 * Railway blocks SMTP, so the backend POSTs each email here over HTTPS.
 * Setup, once, in the Gmail account the emails should come from:
 *   1. script.google.com → New project → paste this file.
 *   2. Replace SECRET below with a long random string.
 *   3. Deploy → New deployment → Web app. Execute as: Me.
 *      Who has access: Anyone. Authorize when asked.
 *   4. On the Railway backend set EMAIL_PROVIDER=apps_script,
 *      EMAIL_RELAY_URL=<the web app URL> and EMAIL_RELAY_SECRET=<the same string>.
 * Consumer Gmail sends to at most 100 recipients a day.
 */
const SECRET = "REPLACE_WITH_A_LONG_RANDOM_STRING";

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply({ ok: false, error: "bad request" });
  }
  if (!body || body.secret !== SECRET || SECRET === "REPLACE_WITH_A_LONG_RANDOM_STRING") {
    return reply({ ok: false, error: "unauthorized" });
  }
  if (!body.to || !body.subject) {
    return reply({ ok: false, error: "missing to or subject" });
  }
  MailApp.sendEmail({ to: body.to, subject: body.subject, htmlBody: body.html, body: body.text || "", name: "Job Hunt" });
  return reply({ ok: true, remaining_today: MailApp.getRemainingDailyQuota() });
}

function reply(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}
