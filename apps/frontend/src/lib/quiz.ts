/* Pure quiz grading — shared by the player and tests. */

export type QuizQuestionKind = "single" | "multiple" | "short";

export interface QuizQuestion {
  id: string;
  prompt: string;
  kind: QuizQuestionKind;
  choices?: { id: string; text: string }[];
  answer_keys: string[];
}

export type QuizAnswer = string | string[] | undefined;

export function isCorrect(question: QuizQuestion, given: QuizAnswer): boolean {
  if (question.kind === "short") {
    if (typeof given !== "string") return false;
    const norm = given.trim().toLowerCase();
    return question.answer_keys.map((a) => a.toLowerCase()).includes(norm);
  }
  const arr = Array.isArray(given) ? given : [];
  if (arr.length !== question.answer_keys.length) return false;
  return arr.every((a) => question.answer_keys.includes(a));
}

export function scoreQuiz(
  questions: QuizQuestion[],
  answers: Record<string, QuizAnswer>,
): number {
  if (questions.length === 0) return 0;
  const correct = questions.filter((q) => isCorrect(q, answers[q.id])).length;
  return Math.round((correct / questions.length) * 100);
}
