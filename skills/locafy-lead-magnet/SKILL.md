---
name: locafy-lead-magnet
description: Turn a link or pasted content Jason texts (a claude.ai artifact, Google Doc, GitHub repo, web page, or raw notes) into an email-gated lead magnet page on locafy.com, then text back screenshots and a pull request link. Use when Jason says "make a lead magnet from this", "gate this on the site", "put this on locafy.com behind an email", "turn this into a lead magnet", or texts a content link with words like lead magnet, opt-in, giveaway, gated or freebie.
---

# locafy-lead-magnet

Jason texts a link and gets back a PR link plus screenshots, then taps Merge in
the GitHub app. Merging `main` on `Locafy/locafy-website` **is** the production
deploy, which is why Ricky stops at the PR (the `ship-code` rules apply in
full: branch + PR, never push to or merge `main`).

The reference implementation is **`src/app/jev-seo-playbook/`**. It was built
from a claude.ai artifact on 2026-09-27 and is the exact shape to copy. The
repo rule is in `AGENTS.md` under "Video lead magnets". Read both before you
write anything.

## 1. Get the source content

Jason's message holds a link or the content itself. Work down this list until
you have the **full** text, not a summary:

| Source | How |
|---|---|
| `claude.ai/.../artifact/...` | Use the `Artifact` tool with `action: read` if you have it (the artifacts belong to Jason's account). Otherwise render the link headless: artifacts shared "anyone with the link" load in a real browser (`agent-browser` or puppeteer). Do **not** use a plain `curl`/WebFetch, which returns an empty "Claude Artifact" shell |
| Google Doc / Drive | Drive integration (`direct-integrations`) |
| GitHub repo | `gh repo view` + README and docs; `gh repo clone` to a temp dir if you need more |
| Any other URL | MCP Scraper `extract_url` |
| Pasted text / voice note | Use as-is |

If all of these fail, text Jason one line asking him to paste the text or
share the doc. Never write the page from a guess at what the link contains.

## 2. Decide the page: don't ask unless it's truly ambiguous

- **Slug**: short, keyword-led, kebab-case (`jev-seo-playbook`, `ai-seo-checklist`).
  Check that `src/app/<slug>` doesn't exist yet.
- **Title / meta**: title ≤ 60 chars, description ≤ 160 chars, both carrying the main keyword.
- **What's gated**: everything of value. The anonymous page is the hero + `EmailGate` only.
- Keep Jason's substance and numbers verbatim. Port the content into the site's
  own components (`Section`, `Badge`, `Button`, `CopyButton`, `SectionDivider`).
  **Never** iframe or paste the source HTML: the page has to look like locafy.com.
- If the source is thin (a few bullets), still build it, but say so in the reply
  and suggest what would make it worth an email.

## 3. Build it: five touch points, no more

In `~/Projects/locafy-website`, on a branch `feat/<slug>-lead-magnet` cut from a
fresh `origin/main`:

1. **`src/app/<slug>/<data>.ts`**: all copy and every copyable string (commands,
   prompts). The page and copy buttons both read from it, so they can't drift.
2. **`src/app/<slug>/page.tsx`**: copy the structure of `jev-seo-playbook/page.tsx`:
   - header comment explaining the magnet and that it is email-gated on the server
   - `const MAGNET = "<slug>" as const;` then read `leadMagnetCookie(MAGNET)` from `cookies()`
   - **locked branch**: hero + `<EmailGate magnet noun title description buttonLabel />`, and
     nothing else. No content, no JSON-LD, no props carrying protected text
   - **unlocked branch**: `JsonLd` (webPage + FAQ), the content, question-style H2s
     with the answer in the first sentence under each, final "done for you?" CTA
3. **`src/lib/lead-magnet-access.ts`**: append the slug to `LEAD_MAGNETS`.
4. **`src/app/api/lead-magnets/unlock/route.test.ts`**: add a test that
   `{ magnet: "<slug>" }` returns 200, tags `social-media-lead`, `sourceTool: "<slug>"`,
   and sets cookie `locafy_magnet_<slug>` (copy the jev-seo-playbook test).
5. **Discovery**: a `GUIDES` card in `src/app/free-tools/page.tsx`
   (`format: "... · email unlock"`, `tag: "New"`) and a `/<slug>` row in
   `src/app/sitemap.xml/route.ts` next to the other magnets.

Gotchas that have already bitten:
- `lucide-react` is v1, which has **no brand icons** (`Github`, `Twitter`...).
  Use `GitBranch`, `Code2`, etc. The build fails otherwise.
- Tailwind v4: write stacked variants breakpoint-first (`lg:[&>p]:mx-0`).
- The repo's working tree may have Jason's untracked files. Use a worktree or a
  clean clone, and `git add` only the paths above. Never `git add -A`.

## 4. Verify: paste real output

```bash
npm ci && npm run type-check && npm run lint && npm test && npm run build
bash ~/SecondBrain/.claude/skills/locafy-lead-magnet/verify_gate.sh \
  ~/Projects/locafy-website <slug> "<a phrase only in the unlocked content>"
```

`verify_gate.sh` starts the built site with a throwaway secret and proves that:
anonymous visitors get only the gate, a signed cookie unlocks, another magnet's
cookie doesn't, the /free-tools card exists, and nothing scrolls sideways on a
phone. It saves `locked-*.png` and `unlocked-*.png` to `/tmp/lead-magnet-<slug>/`.
**Look at the screenshots yourself** before sending them. It never calls Listmonk.

Any red means no PR. Fix it or tell Jason what's broken.

## 5. PR and text back

Open the PR per `ship-code` (body: what, source link, verification output,
anything not verified). Then text Jason:

1. One line: what the page is and its final URL (`https://www.locafy.com/<slug>`).
2. The `unlocked-mobile.png` and `locked-mobile.png` screenshots.
3. The PR link, with "Tap Merge in the GitHub app to put it live (~1 min deploy)."

The Vercel preview on the PR only shows the locked page (the preview has no
signing secret, and a real signup there would write to Listmonk). That's why
the screenshots exist. Don't sign up on the preview.

## 6. After Jason merges

If Jason says it's merged, poll `https://www.locafy.com/<slug>` for up to 10
minutes. A 404 right after merge usually means the build is still running.
Confirm the live page shows "Free, instant access" and not the unlocked
phrase, then reply with the live URL. Only submit it to Prime Indexer if he asks.
