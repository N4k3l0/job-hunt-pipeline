import pytest
from pydantic import ValidationError

from app.api.v1.invite_requests import InviteRequestCreate


def test_email_is_normalized():
    body = InviteRequestCreate(email="  Someone@Example.COM ", source="hero")
    assert body.email == "someone@example.com"


@pytest.mark.parametrize("email", ["", "not-an-email", "a@", "@b.com"])
def test_invalid_emails_rejected(email):
    with pytest.raises(ValidationError):
        InviteRequestCreate(email=email)
