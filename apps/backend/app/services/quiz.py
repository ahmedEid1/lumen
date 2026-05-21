"""Pure quiz grading.

Server-side source of truth for quiz scoring. Mirrors ``frontend/src/lib/quiz.ts``
but is authoritative — clients can shortcut for instant feedback, but the
canonical score is what this module computes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class QuestionResult:
    question_id: str
    correct: bool
    answer_keys: list[str]
    given: list[str] | str | None


@dataclass(slots=True)
class GradeResult:
    score: int                       # 0-100
    pass_score: int
    passed: bool
    correct_count: int
    total: int
    results: list[QuestionResult] = field(default_factory=list)


def _is_correct(question: dict[str, Any], given: Any, answer_keys: list[str]) -> bool:
    kind = question.get("kind")
    if kind == "short":
        if not isinstance(given, str):
            return False
        norm = given.strip().lower()
        return any(norm == a.lower() for a in answer_keys)
    if not isinstance(given, list):
        return False
    given_list = [str(x) for x in given]
    if len(given_list) != len(answer_keys):
        return False
    return all(g in answer_keys for g in given_list)


def grade(lesson_data: dict[str, Any], answers: dict[str, Any]) -> GradeResult:
    questions: list[dict[str, Any]] = list(lesson_data.get("questions") or [])
    pass_score = int(lesson_data.get("pass_score") or 60)
    total = len(questions)
    results: list[QuestionResult] = []
    correct_count = 0
    for q in questions:
        qid = str(q.get("id", ""))
        given = answers.get(qid)
        answer_keys = list(q.get("answer_keys") or [])
        correct = _is_correct(q, given, answer_keys)
        if correct:
            correct_count += 1
        results.append(
            QuestionResult(
                question_id=qid,
                correct=correct,
                answer_keys=answer_keys,
                given=given if isinstance(given, (str, list)) else None,
            )
        )
    score = round((correct_count / total) * 100) if total else 0
    return GradeResult(
        score=score,
        pass_score=pass_score,
        passed=score >= pass_score,
        correct_count=correct_count,
        total=total,
        results=results,
    )
