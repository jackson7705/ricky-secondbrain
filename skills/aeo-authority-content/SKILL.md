---
name: aeo-authority-content
description: Draft LinkedIn posts for Jason anchored to REAL numbers (Ahrefs Brand Radar, GSC, Rank Tracker), and — ONLY after Jason explicitly approves — publish them via `publish.py`. Replaces locafy-linkedin and linkedin-post. Use when Jason says "draft me a LinkedIn post", "what's worth posting today", "turn this GSC move into a post", "ship it", "post the draft", or "publish that draft".
---

# aeo-authority-content

Data-backed LinkedIn authority for Jason Jackson. Every post cites **real numbers** — no generic thought leadership, no vibes. Rebuild of `locafy-linkedin` that swaps "scan the news" for "check the data."

**Never auto-publish.** Drafts always go to `Dynamous/Memory/drafts/active/YYYY-MM-DD_linkedin_<topic>.md`. Publishing happens ONLY after Jason explicitly flips `status: approved` in the frontmatter AND tells Ricky "post it" / "ship it" / "publish". `publish.py` then sends the post to LinkedIn via the `w_member_social` API. See the "Publish Gate" section below.

## Audience + Brand

- **Jason:** COO of Locafy (Nasdaq: LCFY). Leader in AEO + SEO for home service businesses.
- **Target audience:** agency owners, marketing directors, business operators, SEO/AI-search community.
- **Go-to-market reality:** **Locafy's partners sell Locafy, not Jason directly.** Posts should arm partners with air cover, not market Locafy to end customers. When writing case-study content, the partner wins are the hero — Locafy is the engine.
- **Framing (READ `/Users/magicman/.claude/skills/content-research/references/positioning-strategy.md`):** Frame every post around how AI is changing how businesses get discovered, win customers, and grow revenue — outcome over mechanism. Jason posts as a public-company COO giving Bloomberg/CNBC-style market analysis, not as an SEO/AEO educator. Run each angle through AI Announcement -> Business Impact -> Revenue Impact -> What To Do Next, then anchor it to a real data signal per the Data-First Workflow below.

## Content Pillars (unchanged from `locafy-linkedin`)

1. **AI Search Updates — Business Impact.** How changes to AI search (ChatGPT, Perplexity, Google AI Overviews, Gemini) move real business outcomes.
2. **AEO — What it is, why it matters.** Educate the market on Answer Engine Optimization.
3. **SEO Updates and Algorithm Changes.** Be the analyst, not the alarmist.
4. **Locafy / Localizer / Partner Wins.** Real client numbers, real results.

Pillar-specific data hooks, post angles, and templates live in `pillars/`.

## Data-First Workflow

Instead of scanning news, **scan Jason's own data** for what's moving. Anchor every post in a specific signal.

### Sourcing Order (check each before news)

1. **Ahrefs Brand Radar** — new AI citations for Locafy, its partners, or the "home services" space. See `data-sources.md` → Brand Radar.
2. **Google Search Console** — keyword/page movers on growthproagency.com, locafy.com, and tracked partner properties. See `data-sources.md` → GSC.
3. **Ahrefs Rank Tracker** — competitor shifts, SOV changes in home-services SERPs.
4. **Partner wins surfaced in chat / ClickUp** — case study material Jason's already mentioned.
5. **Fallback: news (old workflow).** Only if none of the above surface something post-worthy *and* something notable dropped in the last 48h. Use web_search.

### "Post-Worthy" Thresholds

Only recommend drafting when the data crosses one of these bars. Sub-threshold signals are noise — skip them.

| Signal | Threshold |
|---|---|
| Brand Radar AI citation count | +20% week-over-week, OR a brand-new citation on a tracked brand |
| Brand Radar Share of Voice | ±10 percentage points vs 7-day baseline |
| GSC keyword move | ≥5 positions, top-20 keyword, with ≥100 monthly impressions |
| GSC new ranking keyword | First-ever impressions on a top-20 keyword |
| Rank Tracker competitor shift | Competitor loses top-3 position on a tracked keyword |
| Partner result | ≥2x lead/revenue change tied to the platform |
| External news | Platform-level update (Google/OpenAI/Perplexity) — AND Jason has own-data to back the angle |

### Data-Pull Examples

Use the Ahrefs MCP (`mcp__claude_ai_Ahrefs__*`) for the first four sources. Common pulls:

```
# AI citations for Locafy + tracked partners
mcp__claude_ai_Ahrefs__brand-radar-ai-responses   (last 7 days)
mcp__claude_ai_Ahrefs__brand-radar-mentions-overview
mcp__claude_ai_Ahrefs__brand-radar-sov-history    (SOV trend)

# Ranking + organic movement
mcp__claude_ai_Ahrefs__gsc-keywords               (top movers)
mcp__claude_ai_Ahrefs__gsc-keyword-history        (drill down)
mcp__claude_ai_Ahrefs__gsc-pages-history          (page-level)
mcp__claude_ai_Ahrefs__rank-tracker-competitors-overview

# Market / keyword opportunity
mcp__claude_ai_Ahrefs__keywords-explorer-overview
mcp__claude_ai_Ahrefs__keywords-explorer-volume-history
```

Render heavy data responses with the matching `mcp__claude_ai_Ahrefs__render-*` tools when the MCP result includes `render_with` metadata.

## Jason's Voice (unchanged — do not drift)

- **Authoritative** — knows the space cold, no hedging.
- **Direct** — says what he means, no fluff.
- **Practical** — gives people something usable.
- **Grounded** — not hype-y. Never "game-changer" every other sentence.
- **Confident** — not arrogant. There's a difference.
- **Zero emojis.** See [[../../Dynamous/Memory/SOUL]].

Reads like a seasoned operator at a boardroom table, not an intern who thinks they know what goes viral.

## Post Structure (same as locafy-linkedin — keep the muscle memory)

1. **Hook** (line 1 — all LinkedIn shows before "see more")
   - Lead with the number. "$600K in 5 months. One roofing client. Here's what we did."
   - Or the bold claim. "Most roofing companies are invisible in AI search."
2. **Body** — 1–3 sentence paragraphs, line breaks between. Data-forward. Specifics over generalities.
3. **Takeaway** — actionable or thought-provoking; soft CTA only ("if you're not sure where you stand, that's the first problem to solve"). Never a hard sell.
4. **Hashtags** — max 3, relevant only. Choose from: `#AEO #SEO #LocalSEO #AISearch #SearchMarketing #HomeServices #Locafy #DigitalMarketing #GoogleSearch`. Skip if they add nothing.

## Length Guide

- **Standard:** 150–250 words (bread-and-butter).
- **Thought leadership:** 300–500 words (deeper takes, breakdowns).
- **Case study:** 250–400 words (lead with the result).

If a sentence can be cut in half, cut it.

## Creatives

Same decision framework as `locafy-linkedin`. In addition, when the post leans on a live data pull:

- **Prefer a GSC / Brand Radar screenshot** as the primary visual over a stock graphic. The data is the proof.
- **Anonymize partner / client data** in every screenshot. Never ship an identifiable URL or brand name without Jason's explicit clearance.
- Use the `screenshot-anonymize` convention: crop to the metric only, blur domain/brand, add a clean caption.

## Output File

Write drafts to `Dynamous/Memory/drafts/active/YYYY-MM-DD_linkedin_<slug>.md` with YAML frontmatter that the draft-reconciliation heartbeat can read:

```yaml
---
type: linkedin
source_id: <trigger-data-key>    # e.g. "ahrefs:brand-radar:2026-W16"
pillar: "aeo"                    # aeo | seo | ai-updates | locafy-wins
creative: "text-only"            # text-only | static | screenshot | carousel
data_anchor: "GSC: 'roofing repair near me' moved +7 (pos 12→5), 340 imp/mo"
created: 2026-04-19
status: active
---

## Draft Post

[Full post text — copy-paste ready]

Suggested hashtags: #AEO #LocalSEO
Word count: 172
Creative brief: [if not text-only]
```

## Full Workflow (end to end)

1. **Trigger** — Jason asks for a post, or a scheduled cadence check runs.
2. **Scan** — Pull Ahrefs Brand Radar + GSC movers + Rank Tracker for tracked properties (Locafy, Growth Pro, tracked partners). Use the MCP calls listed above.
3. **Filter** — Apply post-worthy thresholds. If nothing clears the bar, fall back to news. If still nothing, tell Jason "no fresh signal today" — don't force it.
4. **Pick pillar** — Map the signal to one of the four pillars. Read the pillar file in `pillars/` for angle templates.
5. **Draft** — Write the post in Jason's voice, following the post structure.
6. **Creative** — Decide if a visual is needed. If yes, include a creative brief or screenshot plan.
7. **Save** — Write to `Dynamous/Memory/drafts/active/` with the frontmatter above. `status: active` means "Jason hasn't signed off yet."
8. **Hand off** — Show Jason the draft + the data anchor in a tight message. Ask for approval / edits.
9. **Publish gate** — see next section. Never publish without Jason's explicit OK.

## Publish Gate (the only way to ship to LinkedIn)

`publish.py` is the only thing that can post to Jason's LinkedIn. It refuses unless **all four** gates are satisfied:

1. The file's frontmatter has `type: linkedin`.
2. The frontmatter has `status: approved` (Jason flips it from `active` → `approved` himself, or tells Ricky to flip it on his behalf in chat).
3. There's no existing `linkedin_post_urn` in the frontmatter (no double-posts).
4. Either `--yes` is passed on the CLI (chat-driven, after Ricky verbally confirms with Jason), or the operator types `y` at an interactive prompt.

### The script

```bash
cd .claude/skills/aeo-authority-content
uv run --project ../../scripts python publish.py \
    "../../../Dynamous/Memory/drafts/active/2026-04-20_linkedin_aeo-citation-spike.md"
# Interactive — prints the full post, asks "Publish to LinkedIn now? [y/N]"
```

Chat-driven flow (Jason says "ship it"):

```bash
# Ricky flips status: active → status: approved in the draft file first, then:
uv run --project ../../scripts python publish.py \
    "<path-to-draft.md>" --yes
```

### What the script does on success

- POSTs the text to `https://api.linkedin.com/v2/ugcPosts` with `visibility=PUBLIC` (or `CONNECTIONS` via `--visibility`).
- Writes `linkedin_post_urn`, `linkedin_url`, `published_at`, and `status: sent` back into the draft's frontmatter.
- Moves the file from `drafts/active/` to `drafts/sent/`.
- Prints the LinkedIn URL. Ricky then passes it to Jason.

### One-time setup (Jason side)

See `LINKEDIN_SETUP.md`. TL;DR: create a LinkedIn Developer app, enable "Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect", add `http://localhost:8765/callback` as a redirect URL, paste the Client ID + Client Secret into `.env`, then run:

```bash
cd .claude/scripts && uv run python setup_auth.py --linkedin
```

Browser opens, Jason clicks Allow, done. Token saved to `integrations/linkedin_token.json`.

### Safety invariants — don't relax these

- Ricky must **never** flip `status` to `approved` without an explicit "approve" / "ship it" / "post it" from Jason in chat. Silence is not approval.
- `publish.py` with `--yes` is only for immediately-after-Jason-said-yes chat flows. Never in a cron job. Never in a heartbeat. Never in a background script.
- No `launchd` job may schedule `publish.py`. Only drafting can be automated; posting must be a human-in-the-loop decision, every time.

## Things to Avoid (unchanged but worth repeating)

- "I'm thrilled / excited / honored to share..."
- "In today's digital landscape..."
- "Game-changer", "revolutionary", "unprecedented"
- AI slop — if it sounds like a LinkedIn bot wrote it, rewrite it.
- Hashtag stacking.
- "What do you think? Drop a comment below!"
- Vague claims with no supporting number.
- Sharing partner / client data without explicit clearance from Jason.
- Reacting to news older than 5 days as if it's breaking.
- **New for AEO-authority:** posting without a concrete data anchor. If you can't name the number, don't post.

## Related

- [[pillars/aeo]] — AEO-pillar data hooks + sample angles
- [[pillars/seo-wins]] — SEO / GSC movement → post templates
- [[pillars/ai-search-updates]] — platform update posts backed by own data
- [[pillars/locafy-wins]] — partner case studies and anonymization rules
- [[data-sources]] — Ahrefs + GSC query reference
- [[../../Dynamous/knowledge/concepts/communication-preferences]] — zero-emoji rule
- `locafy-linkedin` (legacy) — to be retired once this skill has 3+ shipped posts
