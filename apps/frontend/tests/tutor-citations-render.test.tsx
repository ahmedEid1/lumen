import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { renderTutorBody } from "@/lib/tutor/citations";
import type { TutorCitation } from "@/lib/api/endpoints";

// QA-iter1 follow-up: lock the wire-format `[L:<lesson_id>]` parser so
// a future refactor can't quietly start shipping the raw token text
// through to end users again (saw it on prod 2026-05-28 before this
// helper landed).

const cite = (id: string, title: string): TutorCitation => ({
  lesson_id: id,
  lesson_title: title,
  chunk_excerpt: `excerpt for ${id}`,
});

function R(content: string, citations: TutorCitation[] = []) {
  return render(<div>{renderTutorBody(content, citations)}</div>);
}

describe("renderTutorBody", () => {
  it("returns plain content unchanged when there are no citation tokens", () => {
    R("Hello world.");
    expect(screen.getByText("Hello world.")).toBeInTheDocument();
  });

  it("replaces a known citation token with a numbered superscript anchor", () => {
    R(
      "RAG is useful [L:lsn_abc123].",
      [cite("lsn_abc123", "Why RAG")],
    );
    const sup = screen.getByTestId("tutor-inline-citation-1");
    expect(sup).toBeInTheDocument();
    const link = sup.querySelector("a");
    expect(link).toHaveAttribute("href", "#tutor-cite-1");
    expect(link).toHaveAccessibleName(/Why RAG/);
    // The raw wire token must NOT be in the rendered output.
    expect(screen.queryByText(/\[L:lsn_abc123\]/)).toBeNull();
  });

  it("numbers each citation by its position in the citations array", () => {
    R(
      "Foo [L:a]. Bar [L:b]. Baz [L:a].",
      [cite("a", "First"), cite("b", "Second")],
    );
    // Two references to lesson a → both render as [1].
    expect(screen.getAllByTestId("tutor-inline-citation-1")).toHaveLength(2);
    expect(screen.getAllByTestId("tutor-inline-citation-2")).toHaveLength(1);
  });

  it("drops tokens whose lesson_id isn't in the citations list", () => {
    const { container } = R(
      "Body text [L:unknown_id] continues.",
      [cite("lsn_abc123", "Other")],
    );
    expect(screen.queryByText(/\[L:/)).toBeNull();
    // The surrounding text survives, joined together across the dropped token.
    expect(container.textContent ?? "").toContain("Body text  continues.");
  });

  it("drops every token when citations is empty (streaming case)", () => {
    R("Streamed text [L:lsn_abc] before the citations list lands.", []);
    expect(screen.queryByText(/\[L:/)).toBeNull();
  });

  it("preserves surrounding punctuation around the citation token", () => {
    const { container } = R("Sentence [L:a].", [cite("a", "Source")]);
    // The trailing "." after the token must still render after the [1].
    expect(container.textContent ?? "").toBe("Sentence [1].");
  });
});
