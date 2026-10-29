"""blocks_to_text: the plain-text projection of a Tiptap lesson doc used for embeddings (L62)."""

from __future__ import annotations

import json

import pytest

from app.services.lesson_text import blocks_to_text


def _t(text: str) -> dict:
    return {"type": "text", "text": text}


def _p(*texts: str) -> dict:
    return {"type": "paragraph", "content": [_t(x) for x in texts]}


def test_drafted_lesson_shape_keeps_every_block() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [_t("Why indexes matter")]},
            _p("A B-tree lets ", "Postgres skip rows."),
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [_p("Seq scan")]},
                    {"type": "listItem", "content": [_p("Index scan")]},
                ],
            },
            {
                "type": "orderedList",
                "attrs": {"start": 3},
                "content": [
                    {"type": "listItem", "content": [_p("Run EXPLAIN")]},
                ],
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "sql"},
                "content": [_t("SELECT 1;\nSELECT 2;")],
            },
            {"type": "blockquote", "content": [_p("Measure first.")]},
            {"type": "image", "attrs": {"src": "https://x/y.png", "alt": "Query plan"}},
            {"type": "horizontalRule"},
        ],
    }
    assert blocks_to_text(doc) == (
        "## Why indexes matter\n\n"
        "A B-tree lets Postgres skip rows.\n\n"
        "- Seq scan\n- Index scan\n\n"
        "3. Run EXPLAIN\n\n"
        "SELECT 1;\nSELECT 2;\n\n"
        "> Measure first.\n\n"
        "Query plan"
    )


def test_marks_are_dropped_and_hard_breaks_become_newlines() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "bold", "marks": [{"type": "bold"}]},
                    {"type": "hardBreak"},
                    {
                        "type": "text",
                        "text": "link",
                        "marks": [{"type": "link", "attrs": {"href": "https://x"}}],
                    },
                ],
            }
        ],
    }
    assert blocks_to_text(doc) == "bold\nlink"


def test_unknown_blocks_keep_their_children() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "callout", "attrs": {"tone": "tip"}, "content": [_p("Inside a callout")]}
        ],
    }
    assert blocks_to_text(doc) == "Inside a callout"


def test_json_string_doc_is_accepted() -> None:
    assert (
        blocks_to_text(json.dumps({"type": "doc", "content": [_p("From a string")]}))
        == "From a string"
    )


@pytest.mark.parametrize(
    "doc",
    [
        None,
        "",
        "not json",
        42,
        [],
        {"type": "doc"},
        {"type": "doc", "content": "oops"},
        {
            "type": "doc",
            "content": [
                None,
                3,
                "x",
                {"type": "paragraph", "content": [{"type": "text", "text": None}]},
            ],
        },
        {"type": "doc", "content": [{"type": "heading", "attrs": {"level": "big"}, "content": []}]},
    ],
)
def test_malformed_or_empty_input_returns_empty_string(doc: object) -> None:
    assert blocks_to_text(doc) == ""


def test_heading_level_is_clamped_and_defaults_to_two() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 9}, "content": [_t("Deep")]},
            {"type": "heading", "content": [_t("No attrs")]},
            {"type": "heading", "attrs": {"level": "x"}, "content": [_t("Bad level")]},
        ],
    }
    assert blocks_to_text(doc) == "###### Deep\n\n## No attrs\n\n## Bad level"


# Shapes an LLM can store (only the root is validated), found in review.


def test_text_split_across_inline_wrappers_keeps_its_spaces() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    _t("See the"),
                    {"type": "link", "content": [_t(" official docs ")]},
                    _t("for more."),
                ],
            }
        ],
    }
    assert blocks_to_text(doc) == "See the official docs for more."


def test_blocks_misplaced_inside_a_paragraph_get_their_own_line() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    _p("End of first."),
                    _p("Start of second."),
                    {
                        "type": "bulletList",
                        "content": [{"type": "listItem", "content": [_p("one")]}],
                    },
                    _t("Look:"),
                    {"type": "image", "attrs": {"alt": "Plan diagram"}},
                ],
            }
        ],
    }
    words = blocks_to_text(doc).split()
    assert words == [
        "End",
        "of",
        "first.",
        "Start",
        "of",
        "second.",
        "-",
        "one",
        "Look:",
        "Plan",
        "diagram",
    ]


def test_code_block_keeps_nested_code_and_hard_breaks() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "codeBlock", "content": [{"type": "paragraph", "content": [_t("print(1)")]}]},
            {"type": "codeBlock", "content": [_t("a"), {"type": "hardBreak"}, _t("b")]},
        ],
    }
    assert blocks_to_text(doc) == "print(1)\n\na\nb"


def test_marks_split_inside_a_list_item_do_not_split_the_word() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            _t("data"),
                            {"type": "text", "text": "base", "marks": [{"type": "bold"}]},
                            _t("."),
                        ],
                    }
                ],
            }
        ],
    }
    assert blocks_to_text(doc) == "- database."


def test_deeply_nested_doc_falls_back_to_flat_text() -> None:
    node: dict = _p("deep words")
    for _ in range(3000):
        node = {"type": "blockquote", "content": [node]}
    assert blocks_to_text({"type": "doc", "content": [node]}) == "deep words"


def test_out_of_range_numbers_fall_back_to_defaults() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": float("inf")}, "content": [_t("Big")]},
            {
                "type": "orderedList",
                "attrs": {"start": float("inf")},
                "content": [{"type": "listItem", "content": [_p("x")]}],
            },
        ],
    }
    assert blocks_to_text(doc) == "## Big\n\n1. x"


def test_json_bomb_string_returns_empty() -> None:
    assert blocks_to_text("[" * 100000) == ""


def test_non_string_node_types_are_treated_as_unknown() -> None:
    # An LLM can put any JSON in "type"; a list or dict there must not raise
    # (it would abort the whole course's indexing) or drop the text around it.
    doc = {
        "type": "doc",
        "content": [
            _p("Before."),
            {"type": [], "content": [_p("Inside a list-typed node.")]},
            {"type": {"x": 1}, "text": "ignored"},
            {
                "type": "paragraph",
                "content": [
                    _t("Inline "),
                    {"type": ["link"], "content": [_t("wrapped")]},
                    _t(" after."),
                ],
            },
            {"type": "codeBlock", "content": [{"type": [], "content": [_t("code()")]}]},
        ],
    }
    assert blocks_to_text(doc).split() == [
        "Before.",
        "Inside",
        "a",
        "list-typed",
        "node.",
        "Inline",
        "wrapped",
        "after.",
        "code()",
    ]
