import { describe, expect, it } from "vitest";
import { isCorrect, scoreQuiz, type QuizQuestion } from "@/lib/quiz";

const single: QuizQuestion = {
  id: "q1",
  prompt: "Pick A",
  kind: "single",
  choices: [
    { id: "a", text: "A" },
    { id: "b", text: "B" },
  ],
  answer_keys: ["a"],
};

const multi: QuizQuestion = {
  id: "q2",
  prompt: "Pick A and B",
  kind: "multiple",
  choices: [
    { id: "a", text: "A" },
    { id: "b", text: "B" },
    { id: "c", text: "C" },
  ],
  answer_keys: ["a", "b"],
};

const short: QuizQuestion = {
  id: "q3",
  prompt: "Capital of France?",
  kind: "short",
  answer_keys: ["Paris"],
};

describe("isCorrect", () => {
  it("grades single-choice", () => {
    expect(isCorrect(single, ["a"])).toBe(true);
    expect(isCorrect(single, ["b"])).toBe(false);
    expect(isCorrect(single, undefined)).toBe(false);
  });

  it("grades multiple-choice (order-independent, count-sensitive)", () => {
    expect(isCorrect(multi, ["b", "a"])).toBe(true);
    expect(isCorrect(multi, ["a"])).toBe(false);
    expect(isCorrect(multi, ["a", "b", "c"])).toBe(false);
  });

  it("grades short-answer case-insensitively, trimming whitespace", () => {
    expect(isCorrect(short, "Paris")).toBe(true);
    expect(isCorrect(short, "  paris  ")).toBe(true);
    expect(isCorrect(short, "London")).toBe(false);
    expect(isCorrect(short, ["Paris"])).toBe(false);
  });
});

describe("scoreQuiz", () => {
  it("returns a 0-100 percentage", () => {
    const all = scoreQuiz([single, multi, short], {
      q1: ["a"],
      q2: ["a", "b"],
      q3: "Paris",
    });
    expect(all).toBe(100);

    const half = scoreQuiz([single, multi], { q1: ["a"], q2: ["a"] });
    expect(half).toBe(50);

    const none = scoreQuiz([single], { q1: ["b"] });
    expect(none).toBe(0);
  });

  it("returns 0 for an empty quiz", () => {
    expect(scoreQuiz([], {})).toBe(0);
  });
});
