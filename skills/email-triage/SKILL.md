---
name: email-triage
description: End-of-day email reply workflow. Ricky drafts replies to emails Jason missed or can answer, pings Jason, and sends ONLY after Jason explicitly approves each draft. Use when Jason says "send that reply", "send the X one", "send all", "edit the reply to Y", or asks about the end-of-day email drafts.
---

# Email triage — draft, propose, send-on-approval

## THE ONE RULE (never break it)
**Never send an email on Jason's behalf without his explicit approval of that specific draft.**
No autonomous sends. No "I'll just send this." If you're unsure which draft Jason means, ASK.
When in doubt, don't send. This is outward-facing and hard to reverse.

## How it works
1. The scheduled `eod_email.py` job (6pm daily) scans Jason's inbox, drafts replies to emails
   that look like they await his response, saves them as **Gmail drafts**, records them in
   `.claude/data/state/pending-replies.json`, and texts Jason a numbered list. **It never sends.**
2. Jason reviews (in the text or his Gmail Drafts) and replies with an approval.

## When Jason approves a send
Approvals look like: "send 1", "send all", "send the Mike one", "yes send it", "go ahead on 2 & 3".

1. Read `.claude/data/state/pending-replies.json` — each entry has `n`, `draft_id`, `account`, `to`, `subject`, `why`.
2. Match Jason's words to the entry/entries. If ambiguous, ask which one — never guess and send.
3. For each approved draft, send it:
   ```bash
   cd .claude/scripts && uv run python ../skills/direct-integrations/scripts/query.py \
     gmail send-draft <draft_id> --account <account>
   ```
4. Confirm to Jason ("Sent your reply to Mike ✓") and remove the sent entry from `pending-replies.json`.

## If Jason says "edit" / "change it"
Revise the draft per his note, update the Gmail draft (create a new draft with the corrected body,
threaded on the same email; delete/replace the old one), re-show it, and wait for approval again.
Still no send until he approves.

## Ad-hoc
Jason may also ask you to draft a reply to a specific email any time — same rule: draft it, show
it, send only on his explicit go-ahead. Match his voice: direct, warm-professional, concise; sign "Jason".
