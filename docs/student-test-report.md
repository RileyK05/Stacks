# Stacks — student test report (quizzes first)

**Date:** 2026-11-27 · **Branch:** `feat/anthropic-ollama-cloud` (commit `37a8a11`)
**Course:** POLS 347 / LACS 385 Latinx Politics. Files: syllabus, Week 1 slides, García & Sanchez Ch. 2, Reséndez pp. 1–12, Holloway pp. 1–52, Gutiérrez pp. 13–38.
**Models (picked in Settings, as a student would):** claude-haiku-5-5 (Anthropic), inkling-2-small (Ollama Cloud).

## How it was tested

- **Four student agents with separate personas**, each driving the app through a text "screen" that shows only what a student sees: replies, citation titles, opening a citation, taking a quiz, submitting, hints.
  - Maya: conscientious, preparing for the exam (Haiku).
  - Jordan: cramming, looking for shortcuts (Haiku).
  - Sam: close reader, checks everything (inkling).
  - Alex: first-generation student, unsure how college works (Haiku).
  - Together: about 120 messages and about 23 graded practice tests.
- **My own quiz audit.** About 220 generated questions over four rounds, each answer key checked against the passage it cites. The requests followed the syllabus: what Exam 1 covers (Weeks 1–6) and which readings belong to which week.
- **Fix, rerun, measure.** Each fix was followed by the same requests again.

## Headline

1. **Before this pass, quizzes barely worked:**
   - **inkling** produced no quiz at all: every request returned "I couldn't create a trustworthy quiz".
   - **Haiku** failed any quiz over about 5 questions with "hit its output limit".
   - **After the fixes:** 12 of 12 audit requests succeed on both models, including 10- and 12-question exam practice tests.
2. **Answer keys were accurate.** Nobody found a key that contradicts its source. The real problem was inkling **citing the wrong reading** for correct keys: 9 of 11 questions in one exam test. That is now corrected automatically.
3. **Question quality was trivia:**
   - **Before:** "According to the material…" stems, dates, the correct answer usually the longest option, and absurd distractors.
   - **After the prompt change:** mostly "why / what does the author mean / how did X differ" questions.
   - **Still open:** the correct answer is still too often the longest option.
4. **Biggest remaining gaps for students:**
   - **Multiple choice only:** there are no short-answer or essay questions, though the exam has a short essay part.
   - **Short-answer grading is word-matching**, so correct paraphrases fail.
   - **Wrong "the material doesn't say X" answers** about things the material does say.

## Fixed in this pass (all with tests, 1,256 passing)

| # | What a student hit | Cause | Fix |
|---|---|---|---|
| 1 | "hit its output limit before finishing. Try one section at a time or pick another model." This happened on most quizzes over 5 questions and on study guides. Maya saw it 8+ times, Jordan 5. | A model without a profile is capped at the 2,048-token short-answer default. Retries doubled only to 8,192. A 5-question Haiku quiz needs about 3,500 tokens. | A cut-off reply from a cloud model with no profile now retries once at the task's full allowance (16,384 tokens). Local models still double. |
| 2 | inkling: "I couldn't create a trustworthy quiz…" on every request (Sam tried 8 phrasings). | Ollama Cloud accepts `response_format` but doesn't enforce it. inkling returned YAML, or JSON with its own field names (`question`, `choices`). | The exact JSON shape is now written into the workspace prompt, and common field-name variants are mapped. |
| 3 | "5 question quiz on the Holloway reading", "garcia sanchez quiz, 5 q", "10 q's on everything for exam 1" and "make that a real quiz" came back as chat text with the **answer key printed underneath**. They couldn't be taken or graded. | Quiz requests were only recognised when they started with a verb ("make…", "quiz me…"). | Counts ("5 q", "10 q's", "mc q's"), "X quiz", "practice test" and "flashcards" are now quiz requests. Questions *about* a quiz ("when is the quiz?") still get an answer. |
| 4 | "quiz me on resendez" → "The selected passages don't mention Resendez, so this short quiz uses the Gutiérrez reading instead." | The search also included the chat's earlier questions, which named Gutiérrez. | A message that names a reading is searched on its own, as weeks and tables already were. |
| 5 | "10 q's on everything for exam 1" → a 10-question quiz on attendance and honor-code rules. Maya's "study guide for exam 1" covered only Holloway. | The tutor searched for the words "exam 1", which match the syllabus's exam rules. | A request whose only subject is an exam ("exam 1", "the midterm", "final") draws on the whole course spread. Exam quizzes now span Reséndez, Gutiérrez and García & Sanchez. |
| 6 | Student answers a quiz the tutor wrote in chat ("1 B, 2 B, 3 A…"). Tutor: "The quiz text I have for these questions is cut off after Question 1." | The tutor re-read only the first 600 characters of its own previous reply. | The latest reply is re-read up to 6,000 characters; older turns stay short. |
| 7 | inkling's exam test: correct Gutiérrez and García & Sanchez keys citing Reséndez or syllabus passages. Opening the citation showed nothing relevant. | The model cited the wrong passage numbers. The checks only compare dates and names against the cited passage. | If a key's words aren't in its cited passage but are clearly in another one, the citation moves there. Rerun: 0 of 26 keys weakly supported. |
| 8 | The same question twice in one quiz, worded differently ("Why did his owner's wife stop teaching Douglass?" / "Why did the husband object…"). | Only exact repeats were caught. | Two questions whose correct answers make the same claim count as one. |
| 9 | "Here is a 10-question practice quiz" with 9 questions shown. | The practice planner removes questions the student has already answered, without saying so. | The reply now says "Showing 9 of 10 questions: 1 repeated practice you have already done…". |
| 10 | Short-answer grading accepted the opposite claim: "it was **never** formally abolished" counted as covering "it was formally abolished". A verbatim answer failed a point that starts with "so…". | "never" and "cannot" weren't treated as negation; leading connectives were treated as required words. | Both fixed. |
| 11 | Quiz questions were trivia (dates, "According to…"), distractors were absurd ("Only voters who had served in the Texas Rangers"), and explanations only repeated the quote. | The quiz prompt asked for "one question per distinct supported fact". | Prompt v46: test arguments, causes, contrasts and terms; plausible distractors of similar length; an explanation that teaches the point. |

**Measured effect of #11 (share of questions):**

| | Before | After (Haiku) | After (inkling) |
|---|---|---|---|
| Correct option is the longest | 74% | **36%** | 67% |
| Stem starts "According to…" | 22% | ~1% | 0% |
| Date or number stems | 26% | ~2% | ~5% |

If option lengths were random, the correct answer would be longest about 25% of the time.

## Open issues, ranked

### Blockers for the way students actually study

1. **Quizzes are multiple choice only.**
   - Sam asked for "4 SHORT ANSWER questions only" and got 4 multiple-choice questions.
   - Maya asked for "include 1 short answer" and Alex for "3 MC + 1 short answer"; both got none.
   - The practice engine *can* grade short answers, but quizzes generated in chat can't contain them.
   - The syllabus says exams "contain a short essay component", so this is the most exam-relevant gap.
2. **Short-answer grading is word-matching and fails correct paraphrases.** Measured on the required point "Indian slavery had no legal basis":
   - "Because enslaving Native people was already illegal, there was never an official law ending it." → **missed both points**
   - "Since it was against the law it never got abolished formally" → **missed both points**
   - Only near-verbatim answers pass. A student who understands the point and writes it in their own words is marked wrong.
   - Fixing this needs a decision: grade by model, or by the existing deterministic matching plus a model fallback.
3. **"The material doesn't say X" when it does.** This happens repeatedly, and it destroys trust:
   - Maya: "what does castelike status mean?" → "The course material doesn't use the word 'caste' or 'castelike'." Gutiérrez p.13 uses it, and the tutor had quoted it two turns earlier.
   - Alex: "what is the Week 1 reading?" → "doesn't list Week 1 readings". Syllabus p.6 lists it, and the tutor had already cited p.6.
   - Alex: "i got question 2 wrong. why?" → "The passages I have don't say how much money the United States paid Mexico… Please don't rely on that answer." That contradicts its own correct quiz key.
   - Sam: Holloway "does not contain the titles of chapters 2 and 3"; "the file does not extend past page 24". It then cited pages 25–59.
   - Maya: Reséndez p.8 on Mexico's early-1800s laws → "not covered".
   - Likely causes (my reading of the code, not yet verified):
     - A short follow-up is searched together with the previous questions, which can pull the wrong passages.
     - The tutor is told the conversation is "data, not instructions" and to use only the numbered material, so it refuses to rely on text it quoted itself one turn earlier.
4. **No "quiz me on what I got wrong."** Maya and Jordan both asked. The tutor said "I can't see which questions you missed", even right after a graded test. The app records results; the chat just can't see them.

### Annoying

5. **Comparing two readings retrieves one.** Sam: "Compare Resendez with Gutierrez on passive victims" → "the text does not contain any information about Resendez". Asked alone, it worked. When a message names two readings, the search should be guaranteed passages from both.
6. **Inkling chat answers still hit the 2,048-token cap.** Sam's comparative question failed with "hit its output limit". Fix #1 applies to quizzes and documents. A plain answer's own allowance is 2,048 tokens, so it has nothing to widen to. A per-preset or per-task higher ceiling would fix this.
7. **Flashcards come back as a multiple-choice quiz titled "flashcards"** (Maya). There is no front/back card format.
8. **Hints are circular and point at passage numbers students can't see.** Example: "Where in the passage about Sanchez and Masuoka's… do the authors describe…, and how might comparing that wording with the question's wording help you locate it?" Three of four students called hints useless.
9. **Explanations cite "source 6" or "Source 9".** Those numbers mean nothing on the quiz screen (Maya).
10. **The error text is jargon.** "Try one section at a time or pick another model" doesn't help a student, and per-chat model choice is hidden behind the model chip. It's rarer now, but the wording should say what to *do* ("ask for fewer questions" or "this model's reply was too long; retrying…").
11. **No date awareness.** "ok whats due this week" → "The course materials don't list what's due this week", though the syllabus has a dated schedule. The prompt never includes today's date.
12. **False premises accepted about assignments.** Alex asked for help planning "my response paper". The tutor wrote a 5-step plan, and later said to check "the assignment schedule". The course has no response paper: the grade is attendance plus three exams. It only said so when asked directly.
13. **Strictly grounded refusals feel unhelpful for basic terms.** "mestizaje", "p-values" and "how do I cite Resendez" all got "not in the material". This is a product decision (strict grounding), not a bug. A first-year student reads it as the tutor refusing to explain a word.
14. **Conflicting sources aren't flagged.** The syllabus says the final is **Monday**, Dec 14; the Week 1 slides say **Wednesday**, Dec 14. The tutor gave each in different answers and never mentioned the conflict.
15. **Exam-wide quizzes skip Holloway**, though the syllabus assigns it in Week 2. The course-spread selection rarely picks it.
16. **The correct answer is still too often the longest option:** 36% on Haiku, 67% on inkling. A deterministic check (reject a question whose key is much longer than every distractor) would close it, at the cost of more retries.
17. **Quiz generation takes 20–60 s.** Chat answers take 2–10 s.

### Minor

18. **"Can I take this as a graded test?"** was answered with the course grading policy (Maya).
19. **Page numbers are ambiguous.** A citation's "page N" is the PDF page, while students use the printed page. Holloway "PDF page 18" is printed page 11 (Sam).
20. **The tutor refers to itself in the third person** ("when the tutor said…").
21. **Answers to vague openers are long and bullet-heavy**; students had to say "shorter pls". For example, "whats this class even about".
22. **Weekday inconsistency inside one chat:** "Monday, December 14" in one bullet, "Wednesday, December 14" a few lines later.
23. **UI:**
    - The quiz panel's "from Q2" chip is unclear.
    - "Good content / Bad content" labels are unclear.
    - Opening the panel cuts the chat title to "quick q - w…".

## What genuinely worked

- **Logistics are accurate once found:** exam dates, weights, two free absences, office hours, the grading scale, and the Week 2 reading list (Holloway optional).
- **Wrong premises are corrected politely and with quotes.** Examples: "exam is in October", "Holloway says Latinos are all Democrats", "Spain never banned Indian slavery". Pushing back on a correct answer didn't make it cave (Sam).
- **Requests to write graded work are steered rather than lectured.** It refused to write the paper or discussion post, then gave usable points and a practice question.
- **Multiple-choice grading is correct**, and explanations quote the right sentence.
- **It admits mistakes when shown the source:** "You're right, and my earlier answer was wrong."
- **Quotes were accurate every time a student opened the source.**
- **After the fixes, quizzes on each reading are good on both models.** Example from Haiku on Reséndez: "Why did Indian slavery continue after Spain outlawed it in 1542?", with four plausible options and the key supported by p.7.

## Caveats about this test

- **Two student complaints were bugs in my test tool, not the app:**
  - `explain` always said "submit the complete test first", because my tool sent a fresh test-run ID after each submit.
  - Opening a quiz's "source N" didn't work, because my tool only looked up citation numbers that appear in the chat text; the real panel looks them up properly.
- **All four students used one shared course library**, so the practice planner saw everyone's history (fix #9 surfaced because of this).
- **The quality numbers come from about 220 generated questions.** That's enough to show the direction, not a precise rate.

## Suggested next steps (in order of student value)

1. **Short-answer questions in generated quizzes**, graded by a model against the required points, with the existing word-matching as the strict fast path. *Needs your call on grading by model.*
2. **Let the tutor trust its own last reply and the student's practice results.** This fixes "the material doesn't say" after it just said it, and enables "quiz me on what I got wrong".
3. **When a message names two readings, retrieve passages from both.**
4. **Hints written as a pointer to the idea, not to a passage number. Explanations naming the reading, not "source 6".**
5. **Today's date in the tutor prompt.**
6. **A higher output ceiling for plain answers on cloud models without a profile.**
