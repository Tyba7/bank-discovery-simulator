# Known issues

Issues found during testing that are not yet fixed. Each one names the evidence, the likely cause and the planned fix.

## KI-01 Client answers a product pitch with an unrelated "no"

**Severity:** quality (not correctness or safety: nothing is leaked and no rule is broken).

**Seen:** live API run on 23 Nov 2026, hosted `qwen/qwen3.6-35b-a3b`, client `maria_santos`, education goal and
remittances already uncovered.

| | |
|---|---|
| Adviser | The Education Savings Plan protects what you pay in. Would that suit you? |
| Client | I am not sure what you mean by "protects what you pay in," as I do not have any other accounts or insurance. Is this just a regular savings account? |

A real client would react to the product in light of what they have shared (here: saving for university), for
example "That sounds useful for my children's university. How does it work?"

**Likely cause:** the client prompt (`backend/prompts/client.md`) says to answer "no" when asked about other loans,
insurance or accounts. The model applies that rule to a product proposal. The client also never sees the proposed
product's features, so it cannot react to them.

**Planned fix:**
1. Eval first: a pitch-reaction suite, every product pitched to every client, judged by a different-family model
   for a sensible reaction (interest, hesitation, objection or a question about the product), with no unrelated
   denials. Measure the current prompt as the baseline.
2. Narrow the "say no" rule to direct questions about existing loans, insurance or accounts.
3. When the classifier reports `products_proposed`, add the product's public name, features and limitations to the
   client's turn note. This is catalogue information, so nothing hidden is exposed.
4. Re-run the pitch-reaction suite and the conversation, guard and opening suites for regressions.
