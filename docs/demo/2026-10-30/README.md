# Lumen: live-site archive, 2026-10-30

Lumen's production site, https://lumen.ahmedhobeishy.tech, was captured on 2026-10-30 between about 08:30 and 09:10 UTC, the day it was taken down. Lumen is an AI e-learning platform. A multi-agent builder turns a one-sentence goal into a course, and a course-scoped RAG tutor answers questions with lesson citations.

How it was captured:

- Headless Chromium through Playwright 1.60.
- Desktop shots are 1440x900. Mobile shots are 390x844 at 2x pixel density, so the files are 780x1688.
- Each page was given time to load fully and for animations to finish. The site has no cookie banner. The onboarding tour for signed-in users was dismissed.
- The site was shown in its default dark theme.
- Every signed-in capture used the site's public demo entry (`/demo`), which signs in to the shared demo account. That account's email and password are printed on the sign-in page itself. No other credentials were used.
- Everything shown is live behaviour: real tutor answers and a real course build.

## Screenshots (`screenshots/`)

| File | What it shows | URL |
|---|---|---|
| `01-home-above-the-fold.png` | Home page hero, "Take a path. Become it.", with the animated example tutor run in its finished state: question, retriever step, answer and citation chip. | https://lumen.ahmedhobeishy.tech/ |
| `02-home-full-page.png` | Full home page: hero, "Why Lumen" cards, the featured-course grid (6 courses) and the closing call to action. | https://lumen.ahmedhobeishy.tech/ |
| `03-catalog.png` | Course catalogue with subject, difficulty and tag filters and 8 results (full page). | https://lumen.ahmedhobeishy.tech/courses |
| `04-course-detail-featured.png` | Course page for the featured course "Building Reliable LLM Agents in Python": outcomes, the 4-module / 16-lesson syllabus and the enrol card. Signed-out view, full page. | https://lumen.ahmedhobeishy.tech/courses/building-reliable-llm-agents-in-python |
| `05-lesson-page-featured.png` | One lesson of that course, "Architectural patterns for bounded agent loops", from its free-preview lesson page (full page). | https://lumen.ahmedhobeishy.tech/courses/building-reliable-llm-agents-in-python/preview/1VgB6YnYwVPycuhx0uBRf |
| `06-demo-sign-in.png` | The public demo entry. `/demo` redirects to a sign-in page with the published demo credentials already filled in. | https://lumen.ahmedhobeishy.tech/demo |
| `07-demo-landing-typescript-tutor.png` | Where the demo lands after sign-in: the TypeScript Generics & Variance course with the tutor open and the canned demo question pre-filled in the input box. The thread above it, with a "What variance means" citation chip, was restored from an earlier visitor's session on the shared demo account (02:10). It is not a question asked during this capture. | https://lumen.ahmedhobeishy.tech/learn/typescript-variance?tutor=open&q=…&lesson=canonical-error |
| `08-dashboard-signed-in.png` | Signed-in dashboard ("Welcome back, Demo"): the "Create a course to learn" entry, 9 in-progress courses and 1 completed course with an Open Badge and a certificate. Several entries come from other visitors to the shared demo account (full page). | https://lumen.ahmedhobeishy.tech/dashboard |
| `09-tutor-answer-with-citation.png` | The live tutor inside the featured course. Question: "How should an agent handle a tool call that times out?" The streamed answer arrived in about 6 s and ends with an inline [1] marker and a citation chip pointing to the lesson "Fail-safe fallback strategies and timeout handling". | https://lumen.ahmedhobeishy.tech/learn/building-reliable-llm-agents-in-python |
| `10-tutor-follow-up.png` | Follow-up in the same thread: "and how many times should it retry?" The tutor keeps the context: it recommends 2–3 retries with back-off, then falling back. This answer's citation came out as a raw `【L:…】` token instead of a chip (see the notes below). | same as 09 |
| `11-tutor-cited-lesson.png` | The cited lesson, "Fail-safe fallback strategies and timeout handling", open in the course, with the tutor answer and its citation chip still showing beside it. Taken from the video run. | same as 09 |
| `12-builder-goal-interview.png` | Course builder, step 1. The goal "Teach me how to evaluate a RAG system's retrieval quality" goes in, Lumen asks clarifying questions, then confirms ("Got it!"). The "Your brief so far" summary is filling in below. | https://lumen.ahmedhobeishy.tech/learn/define |
| `13-builder-brief-review.png` | Brief review step: level Intermediate, 4 hours, 2 sessions a week, one outcome, and an estimate of "about 2 modules · 6 lessons". This time the interviewer left the Goal field empty. | same as 12 |
| `14-builder-progress.png` | Build in progress: "Building your course", with the build-progress panel. | same as 12 |
| `15-builder-course-ready.png` | Build finished after about 75 s: "Built 2 modules and 10 lessons. Your private course is ready to study." The Outliner step is expanded here, and its detail box is empty. | same as 12 |
| `16-builder-finished-course.png` | The generated course, "Hands-On Evaluation of RAG Retrieval Quality with Python", open on its first lesson, "Designing a Small, Labeled Retrieval Test Set". | https://lumen.ahmedhobeishy.tech/learn/hands-on-evaluation-of-rag-retrieval-quality-with-python |
| `17-eval.png` | Public eval page ("How the tutor scores. Receipts only."): how to read the numbers, a worked example, promoted runs (tutor Δ +1.21 against a no-retrieval baseline) and the adversarial-probe status (full page). | https://lumen.ahmedhobeishy.tech/eval |
| `18-case-study.png` | Case study "How I built an agentic tutor on a real LLM budget": origin, architecture diagram, anatomy of one turn, prompt iterations, rejected tools and lessons (full page). | https://lumen.ahmedhobeishy.tech/case-study |
| `19-mobile-home.png` | Mobile home page hero (390x844). | https://lumen.ahmedhobeishy.tech/ |
| `20-mobile-tutor-answer.png` | Mobile tutor bottom sheet answering "How do I stop an agent loop from running forever?". It shows inline [1] and [2] markers and two citation chips: "Managing state and termination conditions to avoid runaway loops" and "Architectural patterns for bounded agent loops". | https://lumen.ahmedhobeishy.tech/learn/building-reliable-llm-agents-in-python |

## Video (`video/lumen-walkthrough.mp4`)

H.264 MP4, 1440x900, 25 fps, CRF 28. Length 2:40 (160.4 s), size 6.8 MB. One continuous Playwright recording of the main story, with no cuts inside the story itself:

| Time | What happens |
|---|---|
| 0:00 | Home page (already signed in to the demo account). The hero example run plays, then the page scrolls to the featured courses. |
| 0:15 | Opens "Building Reliable LLM Agents in Python" and scrolls the syllabus. |
| 0:27 | "Start learning" opens the lesson view. |
| 0:30 | Opens the tutor and types "How should an agent handle a tool call that times out?". The answer streams in at about 0:39–0:44. |
| 0:46 | Scrolls through the full answer, ending at the [1] citation chip. |
| 0:58 | Clicks the inline [1] citation, points at the chip, then opens the cited lesson "Fail-safe fallback strategies and timeout handling" from the course outline. |
| 1:15 | Dashboard, then "Create a course to learn". |
| 1:20 | Types the goal "Teach me how to evaluate a RAG system's retrieval quality". Lumen asks clarifying questions and gets two answers (the first is typed, the second is the same text pasted in). |
| 1:49 | Brief review, then "Build my course". |
| 1:56 | Build progress. The Outliner step is expanded. |
| 2:03–2:11 | **The build wait is shown at 8× speed** (66 s of real time), with an on-screen caption saying so. |
| 2:11 | "Your course is ready", then "Start learning" opens the generated course, which is scrolled. |
| 2:25 | The `/eval` page, scrolled through the eval cards. |

Notes on the recording:

- The demo sign-in that came before the story (about 2 s) was trimmed from the start.
- The only edit inside the story is the 8× speed-up of the build wait.
- A small round cursor marker was overlaid so viewers can follow the clicks. Headless Chromium does not draw a cursor, and the marker is not part of the site.

## What did not work, or behaved unexpectedly (recorded as observed)

1. **Citation chip links 404.** Each tutor citation chip links to `/courses/lessons/<lessonId>` and opens it in a new tab. That URL returned "404 Page not found" on the live site. The video therefore clicks the inline [1] citation marker, which links within the page to the chip, and opens the cited lesson from the course outline. The video does not show the chip's own link.
2. **Citation rendering is inconsistent.** Sometimes the model writes the citation as a raw `【L:<lessonId>】` token. The UI then shows that token as text and draws no chip. This happened on the follow-up answer in `10` and on one of the exploratory runs of the first question. It matches the citation-label bug that `/eval` itself describes. Tutor answers also show raw Markdown (`**bold**`, pipe tables), because the panel renders plain text.
3. **Rate limit on the tutor (Groq free tier).** The first mobile tutor question failed with "Couldn't send that. Try again. (tutor.runtime: RateLimitError)". It was retried once about 75 s later and succeeded (`20`).
4. **Builder trace is minimal, and there is no separate trace or replay page.** For learner builds, the build-progress panel shows a single "Outliner" step for the whole build. Expanding it shows an empty detail box (`15`, and in the video). The app's trace API for that course likewise returns one `outliner` step whose payload is only `{phase: building}`. No per-agent steps were visible anywhere in the UI, so this panel is the only trace view captured.
5. **Builder interview quirks.**
   - The first `goal/start` call returned HTTP 502 once ("Something went wrong"). A retry 30 s later worked.
   - The interviewer usually asks the generic "Could you tell me a bit more about your goal?" twice before it converges.
   - In one exploratory run with short answers it never converged within its 6-turn limit.
   - In the recorded run the brief's Goal field came back empty, while level, time, sessions and outcome were filled (`13`).
   - Builds took about 75–92 s and both succeeded on the first try.
6. **Mobile tutor header.** On mobile, the "STREAMING" label overlaps the sheet's close button (`20`).

## Side effects on the shared public demo account

These are normal demo-account actions: no admin actions and no account, password or key changes.

- The demo account was enrolled in "Building Reliable LLM Agents in Python", so it now shows 1 student. The tutor needs an enrolment.
- Several tutor conversations were created in that course.
- Two private learner courses were built:
  - "Evaluating Retrieval Quality in RAG Systems with Python" (exploratory run)
  - "Hands-On Evaluation of RAG Retrieval Quality with Python" (the build shown in the video and in screenshots 12–16)
- A few unfinished goal-interview briefs were left behind.
