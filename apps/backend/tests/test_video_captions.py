"""Captions support for video lessons (WebVTT).

``VideoLessonData`` carries ``captions_url``, ``captions_label``,
and ``captions_lang`` for accessibility — every video should be
captionable. The upload allow-list also includes ``text/vtt`` so
an instructor can presign the upload through the normal flow
rather than hosting the VTT externally.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.course import VideoLessonData
from app.services.uploads import ALLOWED_PER_KIND


def test_video_lesson_accepts_captions_url() -> None:
    v = VideoLessonData(
        type="video",
        url="https://cdn.test/lesson.mp4",
        captions_url="https://cdn.test/lesson.en.vtt",
        captions_label="English",
        captions_lang="en",
    )
    assert v.captions_url is not None
    assert v.captions_label == "English"
    assert v.captions_lang == "en"


def test_video_lesson_captions_optional() -> None:
    """No captions = field omitted, no error."""
    v = VideoLessonData(type="video", url="https://cdn.test/lesson.mp4")
    assert v.captions_url is None
    # Defaults should be sensible even when omitted so the player can
    # render the <track label> attribute without a null-check.
    assert v.captions_label == "English"
    assert v.captions_lang == "en"


def test_captions_url_length_capped() -> None:
    """500-char URL cap matches the video url field — bound the
    payload size, prevent abuse via huge data URLs."""
    with pytest.raises(ValidationError):
        VideoLessonData(
            type="video",
            url="https://cdn.test/lesson.mp4",
            captions_url="x" * 501,
        )


def test_lesson_upload_kind_allows_vtt() -> None:
    """Instructors must be able to presign a VTT through the normal
    upload flow. text/vtt is the IANA-registered type."""
    assert "text/vtt" in ALLOWED_PER_KIND["lesson"]
