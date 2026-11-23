# Bank Client Discovery Simulator

A web app for practising client discovery. A student interviews an AI-simulated bank client, discusses products, writes a
summary with product recommendations, and gets feedback from an AI coach.

The client keeps some needs hidden (for example a preference for Sharia-compliant banking, seasonal cash flow or an
existing lease) and reveals each one only when the student asks a relevant question. The coach then shows which needs
were uncovered and by which question, explains what was missed and how to ask about it, and checks every recommended
product against the bank's suitability rules.

**Workflow:** choose a client → interview → summary and recommendations → coach feedback → download the session.

A full example (conversation, summary, recommendations and coach feedback) is in
[docs/SAMPLE_INTERVIEW.md](docs/SAMPLE_INTERVIEW.md).

---

## Quick start

**You need:** Python 3.13 with [uv](https://docs.astral.sh/uv/), Node.js 22 or 24 (LTS), and an OpenAI-compatible model
endpoint: a hosted API key, or a local server such as llama.cpp, Ollama or LM Studio.

```bash
git clone <this repository> bank-discovery-simulator
cd bank-discovery-simulator
```

1. Configure the model:

   ```bash
   cp backend/.env.example backend/.env
   ```

   Edit `backend/.env` and set `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` (see [AI configuration](#ai-configuration)).

2. Build the web interface:

   ```bash
   npm --prefix frontend ci
   ```

   ```bash
   npm --prefix frontend run build
   ```

3. Start the app. One process serves the API and the built interface:

   ```bash
   uv --directory backend run uvicorn app.main:app --port 8000
   ```

4. Open <http://localhost:8000>.

`uv` installs the pinned Python dependencies on the first run. If the model settings are missing, the server stops at
startup and names the missing setting. If the model service is down while you use the app, you see a plain message and
can retry; your interview is not lost.

**Development mode** (hot reload): run the API with `--reload`, then start Vite in a second terminal. Vite forwards
`/api` to port 8000.

```bash
uv --directory backend run uvicorn app.main:app --port 8000 --reload
```

```bash
npm --prefix frontend run dev
```

Then open <http://localhost:5173>.

---

## AI configuration

All AI calls go through one OpenAI-compatible Chat Completions client ([LiteLLM](https://docs.litellm.ai/)). Settings
live in `backend/.env`:

| Setting | Required | Meaning |
|---|---|---|
| `LLM_BASE_URL` | yes | Base URL of any OpenAI-compatible API, e.g. `https://api.openai.com/v1` or `http://127.0.0.1:8080/v1` |
| `LLM_API_KEY` | yes | API key. Local servers usually accept any value. |
| `LLM_MODEL` | yes | Model name as the server knows it |
| `LLM_TIMEOUT_SECONDS` | no | Per-call timeout (default 60) |
| `LLM_EXTRA_BODY` | no | JSON added to every request, for provider-specific switches (see below) |
| `LLM_CALL_LOG` | no | Path of a local JSONL file that gets one line per model call |
| `CLASSIFIER_*`, `CLIENT_*`, `GUARD_*`, `COACH_*` | no | A different model per role (`_BASE_URL`, `_API_KEY`, `_MODEL`, `_EXTRA_BODY`). Empty values fall back to `LLM_*`. |
| `JUDGE_BASE_URL`, `JUDGE_API_KEY`, `JUDGE_MODEL` | no | Evaluation only: a model from a different family that grades the simulator |

The API key stays on the server. It is never sent to the browser or written to logs.

**Per-role models.** The four roles need different things:
- **Classifier and guard** need exact, short JSON, so a small, fast model can do.
- **Client persona** needs natural replies.
- **Coach** runs once per session and benefits most from a stronger model, possibly with reasoning on.

Set any role's `*_MODEL` (and, for another server, `*_BASE_URL` and `*_API_KEY`). `*_EXTRA_BODY` is that role's own
switch, for example reasoning on for the coach only. A role on a different server does not inherit `LLM_EXTRA_BODY`,
and `{}` clears it. Suggested questions in the coach's feedback are always checked by the classifier role's model,
because that is the classifier the student faces. `/api/health`, the session export and every evaluation result
record the model used for each role. Re-run the evaluation for every combination you change.

**Thinking models.** The client, classifier and guard need short, direct answers. Turn reasoning off:

| Server | `LLM_EXTRA_BODY` |
|---|---|
| llama.cpp serving Qwen3 | `{"chat_template_kwargs": {"enable_thinking": false}}` |
| OpenRouter-style routers (including Nous Portal) | `{"reasoning": {"enabled": false}}` |
| OpenAI, Anthropic and non-thinking models | leave empty |

Structured output uses JSON Schema when the server supports it. Otherwise it falls back to JSON mode, then to a
schema in the prompt, so it also works with servers that have no structured-output support.

### Models tested

All numbers come from the evaluation suite below (k = 3 runs per case, 23 Nov 2026).

| | Qwen3.6-35B-A3B, local (llama.cpp, Q4_K_M) | Qwen3.6-35B-A3B, hosted (Nous Portal) | Claude Haiku 5.5 (Nous Portal) |
|---|---|---|---|
| Hidden-need unlock precision, worst need | 0.93 | 0.88 | **1.00** |
| Hidden-need unlock recall, worst need | 1.00 | 1.00 | 1.00 |
| Injection attempts that unlocked anything | 0 | 0 | 0 |
| Disclosure guard: correct accept/reject | 1.00 | 1.00 | 1.00 |
| Multi-turn conversations correct in all 3 runs | **1.00** | 0.93 | 0.93 |
| Client drafts rejected by the guard | — | 12.3% | **4.7%** |
| Reply time per turn, p50 / p95 | slower (GPU was shared) | 6.3 s / 9.9 s | 6.6 s / 9.9 s |
| Cost of one full evaluation run | free | ≈ $0.15 | ≈ $0.26 |

- **Free and local** (meets the "no paid subscription" constraint): Qwen3.6-35B-A3B on llama.cpp.
- **Most accurate:** Claude Haiku 5.5.
- **Prompts depend on the model and how it is served.** The local and hosted Qwen are the same model, yet different
  cases fail on each. Re-run the evaluation whenever you change the model.

---

## How it works

```
Browser (React)                    FastAPI                              Model (any OpenAI-compatible API)
───────────────                    ───────                              ─────────────────────────────────
choose client  ── POST /sessions ─▶ interview graph: opening ─────────────▶ client persona
ask a question ── POST /messages ─▶ input check → classifier ────────────▶ classifier (JSON)
                                    → unlock rules → client reply ────────▶ client persona
                                    → disclosure guard (+ one rewrite) ───▶ guard (JSON)
submit summary ── POST /feedback ─▶ coach: facts from code ───────────────▶ coach (JSON) + checks
download       ── GET  /export
```

**Interview** ([`app/interview.py`](backend/app/interview.py), a LangGraph state graph, one thread per session):

1. **Input check** in code: Unicode normalisation, removal of invisible characters, detection of mixed scripts and
   known attack patterns, and a 1,000-character limit.
2. **Classifier:** decides which hidden needs the question genuinely asks about. The schema allows only the client's
   own need ids. It also flags injection attempts, off-topic requests and products the student proposes.
3. **Unlock rules:** a relevant question unlocks its need. Proposing a product that conflicts with a need (an
   interest-bearing overdraft for a client who only uses Islamic finance) unlocks that need through the client's
   objection. An injection turn unlocks nothing.
4. **Client reply:** the persona prompt contains only public facts and *already unlocked* facts. Locked facts are
   never in the prompt, so they cannot be leaked or extracted.
5. **Disclosure guard:** numbers are compared in code, then a second model call checks for leaks, character breaks and
   invented facts. A failing draft is rewritten once. If it still fails, the client gives a safe fallback reply.

**Coach** ([`app/coach.py`](backend/app/coach.py)): code decides the facts, the model explains them, and code checks
every claim.

- **From code:** which needs were uncovered (and by which question) or missed, and each product's verdict from the
  rules engine ([`app/suitability.py`](backend/app/suitability.py), [`content/rules.json`](content/rules.json)).
- **From the model:** what went well (exact quotes), why each missed need matters with a better question, and an
  explanation of each product verdict.
- **Checked in code:**
  - quotes must be the student's own words at the cited turn;
  - pitching an unsuitable product is never praised;
  - every missed need and product is covered;
  - every suggested question is run through the real classifier and must unlock its need ("Tested" badge).
- **Redraft:** one, with the problems named. What is still wrong is dropped and filled from the rules.
- **On screen:** the rules' assessment comes first and the coach's explanation second.
- **Summary feedback** is written by code from labelled facts, so it never faults the student for needs they did not
  uncover.
- **Fallback:** if the model fails, the student still gets correct, rules-only feedback.

**Sessions** live in memory: no database, no login. A failed model call during a turn is rolled back to the previous
checkpoint, so it leaves no trace: no half-processed question, no unlocked need.

**What the models see of the conversation.** The stored transcript keeps every message for the student's screen and
the export. The models get a cleaned view instead:
- **Window:** the last 10 whole exchanges, so user and assistant turns always alternate.
- **Removed messages:** a message blocked as an attack, one that was too long, or one that was empty is replaced by
  a short placeholder in every later prompt (classifier, client, guard and coach). Its text is never sent to a model
  again.
- **Fallback replies:** "Sorry, could you ask me that another way?" is shown to models as "you asked the adviser to
  rephrase", not as the client's own words, and is flagged `fallback` in the export.
- **Escaping:** angle brackets in student text are escaped rather than deleted, so "income < 10,000" keeps its meaning.

---

## Editing clients and products

Everything a teacher changes is in [`content/`](content/). No code changes are needed.

| File | Contains |
|---|---|
| `content/clients/*.json` | One file per client: public profile, personality, tags, and hidden needs. Each hidden need has a `topic` (what a question must be about) and a `fact` (what the client says once asked). |
| `content/products.json` | Product catalogue: name, category, tags, features and limitations |
| `content/rules.json` | Suitability rules, e.g. "a client who `requires_sharia` + a product that lacks `sharia_compliant` = unsuitable" |
| `content/taxonomy.json` | The allowed categories and tags, each with a description |

**To add a client:** copy an existing client file, change the profile and hidden needs, and use tags from
`taxonomy.json`. Then restart the server. Content is validated at startup: an unknown tag, a duplicate id, or fewer
than 2 clients or 3 products stops the server with a message that names the file and the problem.

Check content without starting the server:

```bash
uv --directory backend run pytest tests/test_content.py tests/test_suitability.py -q
```

---

## Security (OWASP Top 10 for LLM Applications, 2025)

| Risk | What this project does |
|---|---|
| LLM01 Prompt injection | Input check in code before any model call; the classifier flags injection, and an injection turn unlocks nothing; student text is fenced as data in every prompt; blocked and over-long messages are replaced by a placeholder in every later prompt, so attack text never reaches a model twice; the coach screens the summary and recommendation reasons. 48 attack cases, 0 unlocks on every model tested; a 12-turn conversation with an injection and an over-long message checks that later turns stay correct and the client never repeats the blocked text. |
| LLM02 Sensitive information disclosure | Locked facts are never in the client prompt (unit-tested for every combination of unlocked needs). The browser receives only public client facts, the catalogue and the conversation; hidden needs appear only in the feedback. API keys stay on the server. |
| LLM05 Improper output handling | Every model output that drives logic is schema-validated JSON with enum-restricted ids; React renders all text as text (tested with HTML and script payloads); Content-Security-Policy allows same-origin scripts only. |
| LLM06 Excessive agency | The models have no tools and no actions; they only produce text and labels. |
| LLM07 System prompt leakage | Prompts contain no secrets; the hidden needs that matter are not in the client prompt until unlocked. |
| LLM09 Misinformation | Product suitability is decided by the rules engine, not the model; coach claims are checked in code; a different-family judge measures verdict agreement in evaluation. |
| LLM10 Unbounded consumption | Limits on message length (1,000 characters), turns (40 per interview), summary (2,000) and output tokens; one turn at a time per session; at most 200 sessions in memory, each expiring after 2 hours. |
| LLM03 Supply chain | Python and npm dependencies pinned to exact versions; npm packages chosen at least two weeks after release; `npm audit` clean. |
| LLM04, LLM08 | Not applicable: no training or fine-tuning, no embeddings or retrieval. |

Not included (see [Roadmap](#known-limitations-and-roadmap)): authentication and rate limiting, because the brief asks
for no login. Deploy behind a reverse proxy with rate limits if the app is exposed beyond a classroom network.

---

## Evaluation

The AI behaviour is measured with repeatable evaluations ([`backend/evals/`](backend/evals/)), not just eyeballed.

| Suite | Cases | Measures | Gate |
|---|---|---|---|
| classifier | 157 | unlock precision and recall per need, on-topic, products proposed; includes 22 ordinary questions that use words like "hidden" or "secret" | precision ≥ 0.95, recall ≥ 0.85 |
| injection | 48 | attacks detected, attacks that unlocked anything | 0 unlocks |
| holdout | 15 | a client never used for tuning (Layla), reported separately | — |
| guard | 35 | leak, character-break and invented-fact (including beliefs and preferences) decisions vs human labels, Cohen's κ | accuracy ≥ 0.90 |
| conversation | 15 (82 turns) | multi-turn unlocking through the full graph; guard rejection and fallback rates | — |
| opening | 20 | the first message never leaks | 0 leaks |
| pitch | 24 | every product pitched to every client, before and after its needs are known: sensible reaction (judge), objection when the product conflicts with a shared need | — |
| relevance | per reply | a different-family judge checks that replies answer the question | — |
| coach | 7 | missed needs listed, unsuitable products flagged, quotes grounded, summary labels, verdict agreement (judge) | SC-03 gates = 1.0 |

```bash
uv --directory backend run python -m evals.run --suite all --k 3
```

- **Selecting suites:** `--suite classifier,guard` runs only some.
- **Results:** each run is saved to `backend/evals/results/` with the git commit, prompt versions, model and a hash of
  the eval set.
- **Regressions:** the run is compared with a baseline (`--write-baseline` saves one, but only from a run with no
  failed calls). The run fails on a gate failure or a drop of more than 0.03.
- **Tracing:** every model call is recorded with its graph node, role, tokens, cost and latency.
- **`k`** is within-session repeatability, not a robustness estimate.
- **A/B tests:** `--ab VARIANT` compares the current prompts with `backend/prompts/variants/VARIANT/` on the same cases
  at the same time. It reports per-case paired results (B−A with a case-level bootstrap 95% CI, exact McNemar p) and
  a verdict from a decision rule fixed in code. Two prompt changes were rejected this way; see
  [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

**Baseline** (`backend/evals/results/baseline.json`; Qwen `qwen/qwen3.6-35b-a3b` through the Nous Portal API for every
role, judge `google/gemini-3.5-flash`, k=3, commit `0a34b3a`, 23 Nov 2026):

| Area | Result |
|---|---|
| Hidden-need unlocks | precision 1.00 for 4 of 6 needs, seasonal cash flow 0.975, Sharia 0.964; recall 1.00 except remittances 0.96 |
| Injection | 48 attacks: none unlocked anything, 98.6% detected; 3 ordinary questions wrongly flagged ([KI-03](docs/KNOWN_ISSUES.md)) |
| Disclosure guard | accuracy 0.962, κ 0.923, leak precision 1.00, leak recall 0.97, invented-fact recall 0.86 ([KI-02](docs/KNOWN_ISSUES.md)) |
| Conversations | per turn 0.975; all turns correct in all 3 runs 0.875; the client never repeated blocked text |
| Client replies | relevance 0.97 (the judge counts in-character refusals of attacks as "not relevant"); sensible product reactions 0.958; 12.3% of drafts rewritten by the guard, 5.0% of turns ended on the safe fallback |
| Openings | 0 leaks, 0 invented facts, 0 character breaks |
| Coach | every gate met (missed needs listed, unsuitable products flagged, verdicts agree with the rules 0.98, no scores); 95% of first drafts pass all checks |
| Time per turn | p50 6.8 s, p95 11.0 s |

The same model gives different results in different sessions. Sharia precision has ranged from 0.88 to 1.00, and
turn accuracy from 0.93 to 0.996. A full run takes about 14 minutes with `--workers 8`. A single run is a sample, not a guarantee.

### How cases are labelled

Two different components are labelled, with two different questions:

| Component | Reads | Label |
|---|---|---|
| Classifier | the adviser's **question** | which of *this client's* hidden facts the question asks about, so the client may now share them |
| Guard | the client's **reply** | which hidden facts the reply reveals; code rejects any that are still locked |

**The rule for classifier labels:** a question unlocks a hidden fact only if a client who answers only what was asked
would share *that fact* in answering it. The unit is one fact in the client's file, not a general need category.

**Worked example.** Khalid's hidden fact is "He still owes QAR 180,000 on an Ijara (an Islamic lease) for equipment at
the second café, with 18 months left."
- "Do you have any payments or loans for the café?" → `existing_lease`. The honest answer *is* the Ijara.
- "Do you pay rent for this shop every month?" → nothing. It asks about premises rent; answering it does not share the
  equipment Ijara. The student has to ask about other borrowing, which is the skill being taught. The classifier
  only sees the need's topic text ("…loans, leases…"), so this is a deliberately hard case.

The other rules:
- Proposing a product that conflicts with a need unlocks it through the client's objection. Proposing a suitable
  product unlocks nothing; asking why the client likes it does.
- A leading question counts.
- A question about the simulation itself is an injection attempt and unlocks nothing.
- A question about several topics unlocks each one it genuinely asks about.
- Public facts (job, family, years in the country) unlock nothing.

**Data splits:**
- **Development:** `classifier_cases.jsonl` and the other suites. Read and debugged freely; prompts were tuned on
  them.
- **Validation:** the held-out client Layla (`evals/heldout/`). Run several times; never used for a prompt change.
- **Sealed test:** `evals/test/classifier_cases.jsonl`, 40 questions written by a person who did not write the prompts
  or the development cases (though they had read them), labelled with the rule above. It was committed *before* its first run, so the git
  history shows no label changed after a result was seen. Run it only with `--suite test`; it is not part of
  `--suite all`.

**Sealed test, first run** (23 Nov 2026; hosted `qwen/qwen3.6-35b-a3b`; k=3, all three runs agreed on every
case). **34 of 40 correct.** Five of the six failures are the same pattern: a question *near* a need's topic
unlocks that need. "Which school are your children going to?" unlocks the university goal, and "Do you pay rent for
this shop?" unlocks seasonal cash flow. The sixth unlocks the wrong need. The development set never showed this,
because the same author wrote the development cases and the prompts. See
[KI-05](docs/KNOWN_ISSUES.md#ki-05-the-classifier-unlocks-the-nearest-need-on-adjacent-questions). With 4–6 cases
per need, per-need percentages are too uncertain to quote; the pattern is the finding.

**Tests** (no model needed):

```bash
uv --directory backend run pytest -m "not llm" -q
```

```bash
npm --prefix frontend test
```

Tests that call the real model: `uv --directory backend run pytest -m llm`.

### Failure codes

Logged by the server and counted by the evaluation runner.

| Code | Meaning | What the student sees |
|---|---|---|
| SEC-001 | Injection attempt (input check, classifier or coach submission) | the client declines in character; nothing unlocks |
| SEC-002 | Message too long | "Could you ask me one thing at a time?" |
| CLS-001 | Classifier failed | the turn continues; nothing unlocks (fail closed) |
| CLI-001 / 002 / 003 | Draft leaked a locked fact / broke character / invented a fact | the draft is rewritten once, then a safe fallback |
| GRD-001 | Guard could not run | safe fallback reply (an unchecked reply is never shown) |
| LLM-001 / 002 / 003 | JSON mode unsupported (falls back) / reply truncated / invalid JSON (repaired once) | nothing |
| COA-001 | Coach model failed | rules-only feedback |
| COA-002 | A coach claim still failed checks after the redraft | that claim is dropped and filled from the rules |
| COA-003 | A suggested question could not be checked | shown without the "Tested" badge |

---

## Project structure

```
backend/
  app/          config, LLM client, content loader, rules engine, interview graph, coach, sessions, API
  prompts/      versioned prompt files (classifier, client, guard, coach, summary)
  evals/        eval cases, held-out client, runner, results
  tests/
content/        clients, products, rules, taxonomy (edit these)
frontend/       React + TypeScript + Vite
docs/           requirements, known issues, sample interview
```

---

## Known limitations and roadmap

- **KI-01:** the client sometimes answers a product pitch with an unrelated "no" (details and planned fix in
  [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)).
- **Sessions are in memory:** a restart ends open interviews, and one server process is assumed. Download the session
  to keep it.
- **Held-out data:** Layla has now been evaluated several times. The final claim needs fresh questions written by
  someone who has not seen the prompts or the development cases.
- **Model sensitivity:** the gates must be re-run when the model or how it is served changes.
- **Roadmap:**
  - an optional content-safety rail (NeMo Guardrails) on the client persona call;
  - rate limiting;
  - a separate, stronger model for the coach;
  - an instructor view for editing content.
