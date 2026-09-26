---
name: typesafe
description: Ricky's judgment layer (TypeSafe / Jev) — fast, calibrated second opinions with a confidence number attached. Use BEFORE delivering anything (document, report, deck copy, email draft, article, research summary) to review it against a rubric; when making or recommending a decision between options; when fact-checking claims or numbers against a source; when ranking sources, leads, ideas, or search results during research; and when triaging or classifying a pile of items. Triggers on "review this", "is this good enough", "check this", "fact-check", "verify", "which option", "should we", "decide", "rank these", "which is most relevant", "score this", "QA this", "double-check", "how confident are you", or any time Ricky is about to send a deliverable and hasn't had it checked.
---

# TypeSafe — Ricky's judgment layer

Jev is a small, fast model that does one thing: it reads what you give it and returns
**typed answers with probabilities** — a yes/no probability, one pick from a list, or a
graded score. It does not write, explain, or browse. You do the thinking and the writing;
Jev gives you an independent, calibrated check on it in about a second, for a fraction of
a cent.

Use it so that what you hand Jason is *checked*, not just *written*.

## When to reach for it

| You're about to… | Run | What you get |
|---|---|---|
| Send a document, report, article, or email draft | `review` | Pass / revise / check, a 0–100 score, blockers, and what to fix first |
| State facts or numbers that came from a source | `check` | Each claim: supported / contradicted / not addressed |
| Recommend or pick between options | `decide` | The pick plus how split the decision was |
| Choose which sources, leads, or ideas matter | `rank` | Candidates ordered by relevance |
| Judge something none of the above covers | `ask` | Raw answers to questions you write |

**Skip it** for casual chat replies, anything code can compute exactly (math, dates,
lookups, string matches), and anything needing fresh facts Jev hasn't been given — it
only knows what is in the state you send.

## Commands

Run from `.claude/scripts`. Every command takes `--state "text"`, `--state-file path`
(`.json` files are parsed as structured state), or text piped on stdin. Add `--json` for
full probabilities.

```bash
cd .claude/scripts

# Is it set up?
uv run python -m integrations.typesafe_api status

# REVIEW a deliverable before it ships
uv run python -m integrations.typesafe_api rubrics
uv run python -m integrations.typesafe_api review --state-file /tmp/draft.md \
    --rubric deliverable --brief "What Jason actually asked for, in his words"

# CHECK claims against the source they came from
uv run python -m integrations.typesafe_api check --state-file /tmp/source.md \
    --claim "Organic clicks rose 31% month over month" \
    --claim "The contract auto-renews in March"
#   With exact quotes (caught in code if the quote isn't in the source at all):
#   --claims-file claims.json   →  [{"claim": "...", "quote": "..."}, "plain claim"]

# DECIDE between options
uv run python -m integrations.typesafe_api decide --state-file /tmp/context.md \
    --question "Which fix will move this profile's map-pack ranking most?" \
    --option "reviews=Get more reviews" --option "categories=Fix categories" \
    --option "photos=Add recent photos" --allow-none

# RANK research candidates
uv run python -m integrations.typesafe_api rank \
    --query "what local SEO agencies charge per month" \
    --candidates-file /tmp/sources.json       # {"id": "text or summary", ...}

# ASK your own questions (several at once, one request)
uv run python -m integrations.typesafe_api ask --state-file /tmp/thread.json \
    --questions-file /tmp/questions.json
```

From Python: `from integrations.typesafe_api import ask, decide, check, review, rank`.

## Rubrics

Rubrics live in `rubrics/*.json` next to this file.

| Rubric | For | Put in `--brief` |
|---|---|---|
| `deliverable` | Any document, report, briefing, write-up | What was asked for |
| `email-reply` | A drafted email reply | The email being answered |
| `seo-article` | SEO/AEO article or service page | Target query + business + city |
| `research-brief` | Research summary or analysis | The research question |

Always pass `--brief`. Without it, the questions about whether the work does what was
asked are skipped and the score only reflects general quality.

A rubric has two parts, and they behave differently on purpose:

- **Dimensions** — graded scores combined by weight. A strength can offset a weakness.
- **Blockers** — yes/no conditions (placeholder text, self-contradiction, cut-off
  ending…). Any one that fires fails the review regardless of the score.

To add a rubric, copy one and edit it. Each score level must describe a concrete
situation that makes sense on its own — "Next steps are vague, such as 'look into'", not
"poor".

## Reading the results

- **`pass`** — ship it.
- **`revise`** — a blocker fired or the score is under the pass mark. Fix the
  lowest-scoring, highest-weight dimensions first; the `to improve →` line says what the
  next level up looks like. Then **re-run the review** on the revised draft.
- **`check`** — a blocker came back unsure. Read that part of the draft yourself.
- **⚠ uncertain** — the model was split. Treat it as "look closer", not as an answer.
  A yes/no probability near 0.5 means *genuinely unsure*, not "medium".
- **Confidence** is how concentrated the model's probability was, not proof it is right.
  When several options are all reasonable, low confidence is expected and fine.

Two revision passes is the limit. If it still fails, deliver it with a plain note of
what's weak rather than looping.

## How to use it well

1. **It is a second opinion, not the boss.** If a verdict looks wrong against what you
   can see in the draft, say so and go with your reading. Never tell Jason something is
   "verified" because Jev said so — say what was checked and against what.
2. **Give it the evidence.** `check` can only confirm claims against the source text you
   pass in. "Not addressed" usually means you sent the wrong section, not that the claim
   is false.
3. **One narrow question each.** "Is this good?" is useless. "Does the reply promise a
   deadline that the original email did not mention?" is answerable.
4. **Ask everything in one request.** Questions about the same state run in parallel and
   cost almost nothing extra. Ask the speculative ones too and ignore what doesn't apply.
5. **Always allow "none".** Use `--allow-none` on `decide` when it's possible no option
   fits; otherwise Jev must pick from a bad list.
6. **Let code do code's job.** Exact matches, arithmetic, and date math don't need a
   model. `check` already verifies quotes verbatim before asking anything.
7. **Mention it briefly, when it matters.** In the reply, one line is enough: "Reviewed
   against the deliverable rubric: 88/100, no blockers." Don't paste raw output unless
   Jason asks.

## Writing your own questions (`ask`)

```json
{
  "needs_reply": {
    "type": "noul",
    "instructions": "Is the sender of `email.body` waiting on a response from the recipient?"
  },
  "topic": {
    "type": "choice",
    "instructions": "What is `email.body` mainly about?",
    "criteria": {
      "billing": "Invoices, payments, refunds",
      "delivery": "Status or quality of work being delivered",
      "new_work": "A request for new work or a quote",
      "other": "None of the above"
    }
  },
  "urgency": {
    "type": "score",
    "instructions": "How soon does `email.body` need a response?",
    "criteria": [
      "No response needed",
      "Any time this week is fine",
      "Expects a response today",
      "Something is broken or blocked right now"
    ]
  }
}
```

- `noul` → probability of yes. Use one per label when several can be true at once.
- `choice` → one of 2–255 options. Include a no-match option.
- `score` → position along 2–10 ordered levels.
- Reference parts of structured state in backticks: `` `email.body` ``.
- Question ids are for you; Jev never sees them. Put the full meaning in `instructions`.

## Limits

- Text only, English best. About 32k tokens of state per request — for longer material,
  send the relevant section or judge it in parts.
- State is sent to TypeSafe's API. Never include passwords, API keys, or card numbers.
- If `status` says not configured, carry on without it and do the check yourself.

API details change — the live docs are the source of truth:
https://docs.typesafe.ai/llms.txt
