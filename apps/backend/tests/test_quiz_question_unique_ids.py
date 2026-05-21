"""Regression: a quiz cannot define two questions with the same id.

The frontend lesson editor used ``questions.length + 1`` to mint new
question ids, so deleting then re-adding could reuse an existing id
and quietly create two questions sharing one id. At grade time the
grader keys answers by question id, so a collision means one question
silently absorbs the other's answer and the learner's score is wrong.

We tightened the frontend (use a fresh id), but also added a backend
``QuizLessonData`` validator so any client (mobile, Postman, a future
import script) cannot create the bad shape.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.course import QuizLessonData


def _q(qid: str, choice_answer: str = "a"):
    return {
        "id": qid,
        "prompt": f"Question {qid}",
        "kind": "single",
        "choices": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
        "answer_keys": [choice_answer],
    }


def test_unique_question_ids_accepted() -> None:
    quiz = QuizLessonData(questions=[_q("q1"), _q("q2"), _q("q3")])
    assert [q.id for q in quiz.questions] == ["q1", "q2", "q3"]


def test_duplicate_question_ids_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        QuizLessonData(questions=[_q("q1"), _q("q2"), _q("q1")])
    assert "unique" in str(exc.value).lower()


def test_two_duplicate_ids_rejected_even_when_answers_differ() -> None:
    # Same id, different answer keys — what made this dangerous: the
    # frontend would silently override one with the other.
    with pytest.raises(ValidationError):
        QuizLessonData(questions=[_q("q1", "a"), _q("q1", "b")])
