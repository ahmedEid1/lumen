"""Quiz schema validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.course import QuizLessonData, QuizQuestion


def test_quiz_single_choice_valid() -> None:
    q = QuizQuestion(
        id="q1",
        prompt="Pick a",
        kind="single",
        choices=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
        answer_keys=["a"],
    )
    assert q.answer_keys == ["a"]


def test_quiz_single_choice_requires_exactly_one_answer() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion(
            id="q1",
            prompt="Pick a",
            kind="single",
            choices=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
            answer_keys=["a", "b"],
        )


def test_quiz_short_answer_disallows_choices() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion(
            id="q1", prompt="?", kind="short", choices=[{"id": "x", "text": "X"}], answer_keys=[]
        )


def test_quiz_requires_at_least_one_question() -> None:
    with pytest.raises(ValidationError):
        QuizLessonData(questions=[])  # type: ignore[arg-type]
