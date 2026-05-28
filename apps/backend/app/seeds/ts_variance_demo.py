"""TypeScript Generics & Variance — demo course content.

The fourth seeded demo course, authored for L20.5 of the post-redesign
roadmap. Designed around the canonical demo question that the screencap
will record live:

    "I keep getting `Type 'string' is not assignable to type 'T'` —
     here's my function, why?"

The lessons are deliberately citation-rich and chunk-aligned so the RAG
tutor can ground its answer in 2-3 specific lesson IDs from this course
when that question fires. Each lesson stays ≤220 words to keep
embeddings tight.

Apply this bundle from :func:`app.seeds.demo.run` after the base
demo bundle's subjects/tags/instructor have been ensured. It does not
duplicate user creation — the demo learner is enrolled into this
course by the parent demo seed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    Module,
    Subject,
    Tag,
)
from app.models.user import User


def _text(body_markdown: str) -> dict[str, Any]:
    return {"type": "text", "body_markdown": body_markdown}


def _quiz(question: str, choices: list[tuple[str, str]], answer_id: str) -> dict[str, Any]:
    return {
        "type": "quiz",
        "pass_score": 60,
        "questions": [
            {
                "id": "q1",
                "prompt": question,
                "kind": "single",
                "choices": [{"id": cid, "text": text} for cid, text in choices],
                "answer_keys": [answer_id],
            }
        ],
    }


TS_VARIANCE_MODULES: list[dict[str, Any]] = [
    # ---------------------------------------------------------------- #
    # Module 1 — Generics 101                                         #
    # ---------------------------------------------------------------- #
    {
        "title": "Generics 101",
        "description": "Type parameters, constraints, and why generics exist at all.",
        "lessons": [
            {
                "title": "Why generics exist",
                "type": LessonType.text,
                "data": _text(
                    "Without generics you write the same function twice — once "
                    "for `string`, once for `number`, once for `User`. Each copy "
                    "is identical except for the type. Generics let you write "
                    "the function *once* with a placeholder type:\n\n"
                    "```ts\n"
                    "function identity<T>(value: T): T {\n"
                    "  return value;\n"
                    "}\n"
                    "```\n\n"
                    "The compiler infers `T` at the call site: "
                    "`identity('hi')` resolves `T = string` and the return "
                    "type is `string`, not the looser `any`.\n\n"
                    "The cost is one extra letter (`<T>`) and a mental shift: "
                    "you're now writing about *the shape of a relationship "
                    "between types*, not about a specific type."
                ),
            },
            {
                "title": "Constraints with `extends`",
                "type": LessonType.text,
                "data": _text(
                    "Sometimes `T` can't be *any* type — you need it to have a "
                    "`length` property, or extend a base shape. `T extends U` "
                    "narrows what callers may pass:\n\n"
                    "```ts\n"
                    "function shortest<T extends { length: number }>(items: T[]): T {\n"
                    "  return items.reduce((a, b) => (a.length <= b.length ? a : b));\n"
                    "}\n"
                    "shortest(['a', 'bb', 'ccc']);          // ok — string has .length\n"
                    "shortest([{}, {}]);                    // error — {} has no .length\n"
                    "```\n\n"
                    "Constraints are how generics stop being *unsafe wildcards* "
                    "and become *typed templates*. The compiler can prove the "
                    "body of `shortest` only does things that any `T` actually "
                    "supports.\n\n"
                    "A common mistake: forgetting the constraint and reaching "
                    "for a property on `T` that isn't guaranteed to exist."
                ),
            },
            {
                "title": "Quick check: Generics 101",
                "type": LessonType.quiz,
                "data": _quiz(
                    "Why use `T extends { length: number }` instead of just `T`?",
                    [
                        ("a", "It's faster at runtime"),
                        ("b", "It guarantees the function body's access to `.length` is type-safe"),
                        ("c", "TypeScript requires every generic to have a constraint"),
                        ("d", "It changes what JavaScript runs"),
                    ],
                    "b",
                ),
            },
        ],
    },
    # ---------------------------------------------------------------- #
    # Module 2 — Variance (the canonical demo target)                 #
    # ---------------------------------------------------------------- #
    {
        "title": "Variance — covariant, contravariant, invariant",
        "description": (
            "The thing that explains why `Type 'string' is not assignable "
            "to type 'T'` keeps happening to you."
        ),
        "lessons": [
            {
                "title": "What variance means",
                "type": LessonType.text,
                "data": _text(
                    "Variance is about how a relationship between two types "
                    "(e.g. `Dog` is a subtype of `Animal`) carries — or "
                    "doesn't — into a more complex type built from them.\n\n"
                    "Three flavours:\n\n"
                    "- **Covariant** — the relationship carries forwards. "
                    "  `Dog[]` is a subtype of `Animal[]` because if you *read* "
                    "  from an `Animal[]` you'd still accept a `Dog`. Return "
                    "  positions are covariant.\n"
                    "- **Contravariant** — the relationship flips. A "
                    "  `(a: Animal) => void` can be used where a "
                    "  `(d: Dog) => void` is expected, because anything that "
                    "  accepts every Animal certainly accepts every Dog. "
                    "  Function parameters are contravariant.\n"
                    "- **Invariant** — the relationship doesn't carry at all. "
                    "  `Dog[]` is not a subtype of `Animal[]` if the array "
                    "  is mutable (you could write an `Animal` into it that "
                    "  isn't a `Dog`).\n\n"
                    "TypeScript is **bivariant** for function parameters by "
                    "default (a deliberate looseness for legacy reasons); turn "
                    "on `--strictFunctionTypes` to get true contravariance."
                ),
            },
            {
                "title": "The canonical error: `Type 'string' is not assignable to type 'T'`",
                "type": LessonType.text,
                "data": _text(
                    "This is the most-Googled TypeScript error. The shape:\n\n"
                    "```ts\n"
                    "function setLabel<T>(value: T): T {\n"
                    "  return 'label: ' + value;\n"
                    "  //     ^^^^^^^^^^^^^^^^^ Type 'string' is not\n"
                    "  //                       assignable to type 'T'\n"
                    "}\n"
                    "```\n\n"
                    "Why? `T` is a type the **caller** picks, not the function "
                    "body. The caller might call `setLabel<number>(42)` "
                    "expecting a `number` back. Returning `string` from inside "
                    "the body violates the contract for those callers — so "
                    "`string` is not assignable to `T` *in general*.\n\n"
                    "Three fixes, in order of how much you should reach for them:\n\n"
                    "1. **The function isn't actually generic.** If you always "
                    "   return a string, drop `<T>` and return `string`.\n"
                    "2. **You meant: 'accept any input, return a stringified "
                    "   version'.** Don't use the same `T` for input and output:\n"
                    "   ```ts\n   function setLabel<T>(value: T): string {\n     return 'label: ' + String(value);\n   }\n   ```\n"
                    "3. **You genuinely need T in, T out.** Then the body must "
                    "   produce a `T` — and `'label: ' + value` produces a "
                    "   `string`, which isn't always `T`. Rethink the contract."
                ),
            },
            {
                "title": "Quick check: variance",
                "type": LessonType.quiz,
                "data": _quiz(
                    "Why does `Type 'string' is not assignable to type 'T'` happen?",
                    [
                        (
                            "a",
                            "The caller picks T, so the body can't unilaterally narrow it to string",
                        ),
                        ("b", "TypeScript doesn't support string concatenation"),
                        ("c", "Generics must always be `extends string`"),
                        ("d", "Strict mode forbids returning literals"),
                    ],
                    "a",
                ),
            },
        ],
    },
    # ---------------------------------------------------------------- #
    # Module 3 — Conditional + mapped types                           #
    # ---------------------------------------------------------------- #
    {
        "title": "Conditional and mapped types",
        "description": "Type-level control flow and transformations.",
        "lessons": [
            {
                "title": "Conditional types: `T extends U ? X : Y`",
                "type": LessonType.text,
                "data": _text(
                    "Conditional types are an `if/else` at the type level:\n\n"
                    "```ts\n"
                    "type IsString<T> = T extends string ? 'yes' : 'no';\n"
                    "type A = IsString<'hi'>;   // 'yes'\n"
                    "type B = IsString<42>;     // 'no'\n"
                    "```\n\n"
                    "Two superpowers come along for the ride:\n\n"
                    "- **`infer`** — capture a type from within the condition:\n"
                    "  ```ts\n  type Return<F> = F extends (...a: any[]) => infer R ? R : never;\n  ```\n"
                    "- **Distribution** — when `T` is a union, the conditional "
                    "  distributes over each branch. `IsString<'a' | 42>` "
                    "  becomes `IsString<'a'> | IsString<42>` = `'yes' | 'no'`. "
                    "  Wrap in `[T]` to opt out (`[T] extends [U] ? ...`).\n\n"
                    "Half of the built-in utility types (`Exclude`, `Extract`, "
                    "`ReturnType`, `Parameters`) are one-line conditionals."
                ),
            },
            {
                "title": "Mapped types: keyof, Pick, Omit, Partial",
                "type": LessonType.text,
                "data": _text(
                    "Mapped types build a new object type by iterating over the "
                    "keys of an existing one:\n\n"
                    "```ts\n"
                    "type Partial<T> = { [K in keyof T]?: T[K] };\n"
                    "type Readonly<T> = { readonly [K in keyof T]: T[K] };\n"
                    "type Pick<T, K extends keyof T> = { [P in K]: T[P] };\n"
                    "```\n\n"
                    "Two key building blocks:\n\n"
                    "- `keyof T` is the union of keys of `T`. For "
                    "  `{a: 1, b: 2}` it's `'a' | 'b'`.\n"
                    "- `T[K]` indexes into `T` — `{a: 1}['a']` is the type `1`.\n\n"
                    "Combined, you can express transformations like 'make every "
                    "field of `User` optional', 'drop the `password_hash` field', "
                    "'lift each field into a `Promise<...>`'. The standard "
                    "library's utility types are mostly mapped types."
                ),
            },
        ],
    },
    # ---------------------------------------------------------------- #
    # Module 4 — Template literals + capstone                         #
    # ---------------------------------------------------------------- #
    {
        "title": "Template literal types and capstone",
        "description": "Put generics, variance, and mapped types to work.",
        "lessons": [
            {
                "title": "Template literal types",
                "type": LessonType.text,
                "data": _text(
                    "Template literal types let you do string manipulation at "
                    "the type level:\n\n"
                    "```ts\n"
                    "type Greeting = `hello, ${string}`;\n"
                    "type Verb = 'get' | 'post';\n"
                    "type Path = `/api/v1/${string}`;\n"
                    "type Endpoint = `${Uppercase<Verb>} ${Path}`;\n"
                    "// → 'GET /api/v1/${string}' | 'POST /api/v1/${string}'\n"
                    "```\n\n"
                    "Combined with `infer`, you can parse strings *at the type "
                    "level*:\n\n"
                    "```ts\n"
                    "type Param<S> = S extends `:${infer P}` ? P : never;\n"
                    "type X = Param<':userId'>;   // 'userId'\n"
                    "```\n\n"
                    "Route-typing libraries (e.g. `@ts-rest`, `tRPC`'s path "
                    "shapes) lean on this heavily to give you autocomplete "
                    "over URL segments. Powerful, occasionally slow on huge "
                    "unions — watch your editor responsiveness."
                ),
            },
            {
                "title": "Capstone: a type-safe API client",
                "type": LessonType.text,
                "data": _text(
                    "Putting it together — a tiny type-safe API client:\n\n"
                    "```ts\n"
                    "type Routes = {\n"
                    "  '/users': { get: { response: User[] } };\n"
                    "  '/users/:id': { get: { response: User }; delete: { response: void } };\n"
                    "};\n\n"
                    "async function api<\n"
                    "  P extends keyof Routes,\n"
                    "  M extends keyof Routes[P]\n"
                    ">(path: P, method: M): Promise<Routes[P][M]['response']> {\n"
                    "  // …fetch + JSON parse…\n"
                    "}\n\n"
                    "const users = await api('/users', 'get');\n"
                    "//    ^^^^^ inferred as User[]\n"
                    "```\n\n"
                    "Notice what's doing the work:\n\n"
                    "- `P extends keyof Routes` — constrained generic (Module 1).\n"
                    "- `M extends keyof Routes[P]` — generic depending on another "
                    "  generic. The compiler tracks the relationship.\n"
                    "- `Routes[P][M]['response']` — indexed access (Module 3).\n\n"
                    "Variance lives in the `Promise<...>` return: it's a covariant "
                    "position, so wider response types in `Routes` flow outwards "
                    "to callers correctly. Generics + indexed access give the "
                    "caller full autocomplete on `path`, `method`, and the "
                    "inferred return type."
                ),
            },
        ],
    },
]


async def apply(
    db,
    *,
    instructor: User,
    programming: Subject,
    tags: dict[str, Tag],
) -> Course:
    """Upsert the TS Generics/Variance course. Idempotent on re-run.

    Uses the same _build_course shape as the rest of the demo bundle.
    Inlined here (instead of importing from demo.py) so this module is
    self-contained and importable from tests without circular imports.
    """
    slug = "typescript-variance"
    existing = await db.execute(select(Course).where(Course.slug == slug))
    course = existing.scalar_one_or_none()
    if course is not None:
        return course

    course = Course(
        owner_id=instructor.id,
        subject_id=programming.id,
        title="TypeScript Generics & Variance",
        slug=slug,
        overview=(
            "The deep cut on generics, variance, and conditional types. "
            "Designed to pair with Lumen's AI tutor — paste a confusing "
            "`Type 'string' is not assignable to type 'T'` and watch the "
            "tutor cite back to the specific lesson that explains it."
        ),
        learning_outcomes=[
            "Read and write generic functions with confidence",
            "Reason about why `Type 'X' is not assignable to type 'T'` happens",
            "Use conditional + mapped types to build utility types from scratch",
            "Pick the right type-level tool for a real-world API client",
        ],
        difficulty=Difficulty.intermediate,
        status=CourseStatus.published,
        published_at=datetime.now(UTC),
        is_featured=True,
    )
    course.tags = [
        tags["typescript"],
        tags["demo"],
    ]
    db.add(course)
    await db.flush()

    for m_idx, mod_spec in enumerate(TS_VARIANCE_MODULES):
        module = Module(
            course_id=course.id,
            title=mod_spec["title"],
            description=mod_spec.get("description", ""),
            order=m_idx,
        )
        db.add(module)
        await db.flush()
        for l_idx, lesson_spec in enumerate(mod_spec["lessons"]):
            db.add(
                Lesson(
                    module_id=module.id,
                    title=lesson_spec["title"],
                    type=lesson_spec["type"],
                    order=l_idx,
                    data=lesson_spec["data"],
                    # QA-iter2: see demo.py — first lesson of first
                    # module is_preview=True so the free-preview link
                    # actually surfaces in the catalog → course detail
                    # → preview flow for anonymous visitors.
                    is_preview=(m_idx == 0 and l_idx == 0),
                )
            )
        await db.flush()

    return course
