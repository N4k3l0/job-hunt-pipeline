"""Reading whose forwarded alert an email is, and Gmail's forwarding code."""

from app.services.job_alerts.forwarding import codes_in, new_code, personal_address, read_confirmation


def test_personal_address_is_the_inbox_with_the_code_after_a_plus():
    assert personal_address("Alerts.Inbox@gmail.com", "k7f3q2xa") == "alerts.inbox+k7f3q2xa@gmail.com"
    assert personal_address("inbox+old@gmail.com", "k7f3q2xa") == "inbox+k7f3q2xa@gmail.com"


def test_codes_come_from_the_addresses_it_was_delivered_to():
    recipients = [
        "Delivered-To: inbox+k7f3q2xa@gmail.com",
        "X-Forwarded-For: someone@gmail.com inbox+k7f3q2xa@gmail.com",
        "To: someone@gmail.com",
    ]
    assert codes_in(recipients) == ["k7f3q2xa"]
    assert codes_in(["Delivered-To: inbox@gmail.com"]) == []


def test_new_codes_have_no_look_alike_characters():
    code = new_code()
    assert len(code) == 8 and not set(code) & set("01ilo")


def test_gmail_forwarding_confirmation_is_read():
    subject = "(#482913765) Gmail Forwarding Confirmation - Receive Mail from Someone.Else@gmail.com"
    text = (
        "someone.else@gmail.com has requested to automatically forward mail to your email address "
        "inbox+k7f3q2xa@gmail.com.\nConfirmation code: 482913765\n\nTo allow someone.else@gmail.com..."
    )
    assert read_confirmation(subject, text) == {"code": "482913765", "from": "someone.else@gmail.com"}
    # The body alone is enough.
    assert read_confirmation("Gmail Forwarding Confirmation", text)["code"] == "482913765"
    assert read_confirmation("Your weekly digest", "Nothing to see") is None
