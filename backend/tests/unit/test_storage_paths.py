"""Stored resume references are paths now, or public URLs on older rows."""

import pytest

from app.services.storage import object_path

BASE = "https://frahcarfyrdmdqhsuvkq.supabase.co/storage/v1/object/public"


@pytest.mark.parametrize("stored, expected", [
    ("user-1/3f2a.pdf", "user-1/3f2a.pdf"),
    ("/user-1/3f2a.pdf", "user-1/3f2a.pdf"),
    (f"{BASE}/resumes/user-1/My%20Resume%20(2).pdf", "user-1/My Resume (2).pdf"),
    (f"{BASE}/resumes/user-1/cv.pdf?", "user-1/cv.pdf"),
    (f"{BASE}/resumes/user-1/tailored/tailored_9.pdf", "user-1/tailored/tailored_9.pdf"),
])
def test_object_path(stored, expected):
    assert object_path("resumes", stored) == expected


@pytest.mark.parametrize("stored", [
    f"{BASE}/other-bucket/user-1/cv.pdf",
    "https://example.com/storage/v1/object/sign/resumes/user-1/cv.pdf",
])
def test_object_path_rejects_other_locations(stored):
    with pytest.raises(ValueError):
        object_path("resumes", stored)
