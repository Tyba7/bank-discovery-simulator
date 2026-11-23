# Known issues

Issues found during testing that are not yet fixed. Each one names the evidence, the likely cause and what was tried.

## KI-01 Client misreads a product pitch

**Severity:** quality (not correctness or safety: nothing is leaked and no rule is broken).

**First seen:** live API run on 23 Nov 2026, hosted `qwen/qwen3.6-35b-a3b`, client `maria_santos`:

| | |
|---|---|
| Adviser | The Education Savings Plan protects what you pay in. Would that suit you? |
| Client | I am not sure what you mean by "protects what you pay in," as I do not have any other accounts or insurance. Is this just a regular savings account? |

**Measured since** with the `pitch` eval suite: every product pitched to every client, before and after all needs
are known, judged by a model from a different family (`google/gemini-3.5-flash`).

- **The unrelated "no other accounts" reply** did not appear again: 0 times in 238 pitches.
- **The current failure** is a different one: once Khalid has said he only uses Sharia-compliant products, he
  sometimes rejects a *compliant* product as interest-based. Global Transfer Account: 4 of 5 runs. Murabaha: 1 of 5.
  The client never sees product details, so it guesses from the product name.
- **Overall:** pitch reactions judged sensible 0.958 (119 pitches, k=5); the client objects whenever a pitched product
  conflicts with a need it has shared (1.000).

**Tried and rejected, variant `ki01`** (`backend/prompts/variants/ki01/`).

What it changed:
- narrower "say no" rule;
- the client never takes on beliefs or preferences;
- the client sees the proposed product's features.

The paired A/B against the current prompts (same cases, same time, k=5;
`evals/results/2026-11-23T130350+0000-ab.json`):

| Metric | Current | ki01 | Discordant runs | p (McNemar) |
|---|---|---|---|---|
| Pitch reaction sensible | 0.958 | 0.958 | 5 vs 5 | 1.00 |
| Objects when a pitch conflicts with a shared need | 1.000 | 0.800 | 8 vs 0 | 0.008 |
| Pitch replies without the fallback | 1.000 | 0.958 | 5 vs 0 | 0.06 |
| Conversations with every turn correct | 0.947 | 0.893 | 5 vs 1 | 0.22 |

Why it was worse:
- **Hidden limitation.** The overdraft's interest rate is a *limitation*, so the client only asked whether it
  charges interest instead of objecting.
- **Features tempt the client.** Text like "transfers to the Philippines" pulled the client towards locked needs,
  which ended in the guard's fallback reply or in an invented fact.

**Next idea, not built (`ki02`):** give the client only the product facts that relate to needs it has *already
shared*. These would be derived from the rules engine and tags, for example "this overdraft charges interest" once
Sharia is known. Facts matching locked needs would stay out. This applies the same context minimisation as the client
prompt.

## KI-02 The guard misses some invented preferences and facts

**Severity:** quality. The client can add a detail that is not in its profile.

**Evidence:**
- Guard case `g-31`: "I prefer not to be locked into a fixed amount every month" is an invented preference. Guard v4
  misses it in both of 2 runs.
- In the `ki01` arm of the A/B, Khalid said "I do send money to my family back home". He has no such need, and the
  guard let it through.

Guard v4 catches invented religion and beliefs (`g-30`): invented-fact recall rose from 0.64 to 0.86.

**Next step:** more labelled cases of invented preferences and facts; then measure a stronger or different-family
guard model with per-role model settings.
