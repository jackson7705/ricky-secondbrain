---
name: ship-code
description: DRAFT — pending Jason's review. Ships code changes as a branch + pull request, never a direct push to main. Use when Jason says "ship this", "fix X in <repo>", "open a PR for", "patch <repo>", or when a code change needs to land in a repo other than a throwaway. Covers repo selection, branching, the verification gate, secret scanning, PR creation, and what Ricky is not allowed to do.
---

# ship-code

> **STATUS: DRAFT — not yet approved for autonomous use.** Written 2026-09-12.
> Open questions for Jason are at the bottom. Until he signs off, run this flow
> only when he asks for it explicitly in the same message.

Turns "fix the thing in google-ads-platform" into a reviewed pull request with a
link Jason can open on his phone. Ricky writes and verifies; **a human merges.**

## Core Rule

**Branch and PR. Never push to `main`/`master`. Never merge. Never force-push.**

`gh` is authenticated as **`jackson7705`** with `repo` + `workflow` scopes — that
is real write access to every Locafy repo. The only thing standing between a bad
change and production is this rule. It is not negotiable, and "Jason said just
push it" gets a confirmation question, not a push.

## Before Anything Else — Is This Allowed?

| Situation | Action |
|---|---|
| Repo is in the allowlist below | Proceed |
| Repo is not in the allowlist | Ask Jason first, naming the repo |
| Change touches `.github/workflows/`, deploy config, or secrets | Say so **explicitly** in the PR body and in the chat reply. Never slip a CI change into an unrelated PR |
| Change touches production data, migrations, or a live customer site | Stop. Ask. Do not open a PR that could be merged without Jason understanding the blast radius |
| Repo is `jackson7705/ricky-secondbrain` | **Public repo.** Secret scan is mandatory before every commit (see below) |

### Repo allowlist (starting set)

- `jackson7705/ricky-secondbrain` — Ricky itself (**public**)
- `jackson7705/jason-second-brain-vault` — memory vault (private; prefer the
  normal git-sync path, not PRs, for daily-log content)
- `Locafy/google-ads-platform`
- `Locafy/locafy-website`
- `Locafy/locafy-marketing`
- `Locafy/triton`
- `~/Projects/mission-control` — local only, no remote configured yet

Anything else: ask.

## Workspace

Repos live in `~/Projects/<repo-name>`. If the repo isn't there:

```bash
gh repo clone Locafy/<repo> ~/Projects/<repo>
```

**Known limitation (2026-09-12):** the chat engine pins `cwd` to
`~/SecondBrain` (`chat/engine.py:386`). Work outside that tree runs through
`Bash` with absolute paths. If `Edit`/`Write` is refused on a path outside
`~/SecondBrain`, that's the cause — say so plainly rather than working around it
by piping heredocs into files. The repo-workspace fix is a separate change.

## The Flow

### 1. Orient
```bash
cd ~/Projects/<repo>
git status && git branch --show-current
git log --oneline -10          # learn this repo's commit message style
```
Read enough surrounding code to match its idiom. Check for `CLAUDE.md`,
`CONTRIBUTING.md`, or a `README` build section — repo instructions win over
anything here.

### 2. Establish a green baseline — **before** changing anything
Run the repo's test/build command and record the result. If it's already broken,
you need to know that now, not after your diff is on top of it.

| Repo type | Baseline command |
|---|---|
| Python (`pyproject.toml`, `uv.lock`) | `uv run pytest` |
| Next.js / TypeScript | `npm ci && npm run build && npx tsc --noEmit` |
| Neither / no tests | Say so explicitly. "This repo has no test suite" is a finding Jason should hear, not a gap to paper over |

### 3. Branch
```bash
git checkout main   # or master — check which this repo uses
git pull
git checkout -b <type>/<short-description>
```
`<type>` is `fix`, `feat`, `chore`, or `docs`.

### 4. Implement
Delegate the actual build when the work fits a specialist — **Backend Engineer**
for Python/integrations, **Frontend Engineer** for Next.js/Tailwind, **Debugger**
when it's a failure with no known cause. Keep the diff scoped to what was asked.
Unrelated cleanup goes in its own PR or not at all.

### 5. Verify — the gate
**Run it. Paste the real output.** Not a summary, not "tests pass" — the actual
terminal output including counts and exit status.

A change is not shippable until:
- [ ] The test/build command ran and its output is pasted
- [ ] For a bug fix: the new test **failed before the fix** and passes after —
      state both, via **Test Engineer**
- [ ] Anything you could not verify is named explicitly in the PR body

If there's no test suite, the gate becomes: run the actual code path end to end
with real input and paste that output. "It looks right" is not verification.

### 6. Review before pushing
Dispatch **Code Reviewer** on the diff (`git diff main...HEAD`). Fix anything it
marks CONFIRMED. Note anything PLAUSIBLE in the PR body rather than silently
dismissing it.

### 7. Secret scan — every time, mandatory
```bash
git diff --cached | grep -nEi '(api[_-]?key|secret|token|password|bearer |sk-|ghp_|gho_|-----BEGIN)'
git status --porcelain | grep -E '\.env|credentials|token\.json|\.pem$'
```
Any hit stops the commit. `ricky-secondbrain` is a **public** repo — a token
committed there is a token that must be rotated, not deleted.

### 8. Commit
Match the repo's existing style (`git log --oneline -10`). This vault and
`ricky-secondbrain` use conventional commits:

```
fix: BlueBubbles watchdog never detected an outage

<why it was broken, not a restatement of the diff>
```

Commits Ricky authors carry a trailer so they're auditable later:

```
Assisted-by: Ricky (Second Brain)
```

### 9. Push and open the PR
```bash
git push -u origin <branch>
gh pr create --title "<same as commit subject>" --body "$(cat <<'EOF'
## What
<one paragraph>

## Why
<the problem, and how it showed up>

## Verification
<pasted command output — the real thing>

## Not verified
<anything untested, or "nothing">

## Risk
<blast radius if this is wrong; call out CI/deploy/secrets changes here>
EOF
)"
```

Never pass `--merge`, and never follow up with `gh pr merge`.

### 10. Report back
Reply in chat with: one-line summary, what was verified, anything left unverified,
and **the PR URL**. The URL is the deliverable — same rule as Drive links for
documents. A local branch name Jason can't open from his phone is not a result.

## Anti-Patterns

- Saying "done" without pasted command output — the exact failure mode this
  skill exists to prevent
- Pushing to `main` because the change "is small"
- Rolling unrelated fixes into one PR
- Weakening or skipping a test to get green
- Opening a PR with an empty or generic body ("Updates code")
- Committing `.env`, `google_token.json`, or anything matching the secret scan
- Silently working around a refused `Edit` outside `~/SecondBrain` instead of
  reporting the limitation

## Identity — `jackson7705`, no bot account

**Decided 2026-09-12.** Everything ships under Jason's own GitHub account
(`jackson7705`) across both the personal repos and the `Locafy` org. No separate
machine account, no bot identity.

That means a Ricky-authored PR is indistinguishable from a Jason-authored one at
the GitHub level, so **the commit trailer is the entire audit trail**:

```
Assisted-by: Ricky (Second Brain)
```

It is not decoration — it's the only way to answer "did a human write this?"
after the fact. Every commit Ricky authors carries it, no exceptions. Finding
what Ricky touched is then just:

```bash
git log --grep="Assisted-by: Ricky" --oneline
```

Two consequences worth holding onto:
- **Reviews matter more, not less.** Nothing about the author field signals
  "machine-written, look closer" — the Code Reviewer pass in step 6 and Jason's
  merge are the only gates.
- **Never remove or weaken the trailer** to make a diff look cleaner.

## Hard Stops — ask Jason, don't decide

- Merging anything
- Force-pushing, rewriting history, deleting branches you didn't create
- Changing CI workflows, deploy configs, or DNS
- Rotating or regenerating any credential
- Any change to a live customer site
- Any repo outside the allowlist

---

## Open questions for Jason (resolve before this skill goes live)

1. **Allowlist** — the starting set above is my guess from your `gh repo list`.
   Which repos should Ricky actually be able to touch? `unify-api`, `locafy-crm`,
   and `governance` are deliberately excluded as too load-bearing.
2. **Autonomy** — should Ricky open PRs unprompted (e.g. heartbeat notices a
   broken job and fixes it), or only when you ask in the moment? Draft assumes
   the latter.
3. ~~**Identity**~~ — **RESOLVED 2026-09-12: stay on `jackson7705`.** No separate
   machine account. See *Identity* above.
4. **Reviewer** — auto-request a human reviewer on Locafy repos, or leave PRs
   unassigned for you to route?
5. **`mission-control`** — no remote configured and it's on `master`. Push it to
   GitHub, or keep it local-only and out of this flow?
