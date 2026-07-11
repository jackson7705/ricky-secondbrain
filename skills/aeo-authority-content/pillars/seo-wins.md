# Pillar — SEO Wins & GSC Movement

The "analyst, not alarmist" pillar. Turn GSC movement into a crisp story about how search really moves.

## Primary Data Hooks

| Signal | Query | Post angle |
|---|---|---|
| Keyword moved ≥5 positions (top-20) | `gsc-keywords` → `gsc-keyword-history` | "One keyword moved 7 spots. Here's what that's worth in traffic." |
| First-ever top-20 impression | `gsc-keywords` | "A brand-new keyword just started showing up. Here's why that matters." |
| Page-level CTR jump | `gsc-pages` / `gsc-pages-history` | "CTR on this page went from 2% to 7%. Here's what changed." |
| Competitor loses top-3 | `rank-tracker-competitors-overview` | "Top-3 in [niche] just shuffled. Here's the move." |

## Post Angles

- "If you're not tracking these SEO metrics, you're flying blind. Here are the 3 that moved this month."
- "The 3 things that still drive rankings in [year] — and the 3 that don't. Our data says:"
- "A partner's [keyword type] keyword moved from page 3 to page 1 in [window]. The playbook, in 4 bullets:"

## Anonymization Rules (IMPORTANT)

For any partner-client data:
- Never name the partner without explicit Jason sign-off.
- Use archetype: "a roofing partner", "a Southeast HVAC operator".
- Crop screenshots to the metric only — no URL, no page title.
- If the numbers would identify the client on their own (rare, but possible in small markets), round to nearest 10% or convert to multiples ("3x traffic").

## What Makes an SEO-Wins Post Land

- **One keyword, one story.** Don't pile up 10 wins — pick the best and tell it well.
- **Show the before and after.** A chart is worth 200 words.
- **Explain WHY** — what content / schema / internal linking move caused the shift?
- **Avoid "ranking" fetish** — Jason's brand is about revenue / lead impact, not vanity positions. Connect the move to business outcome where possible.

## Hook Library

- "One keyword. Seven positions. [Traffic increase] per month. Here's what we did."
- "Most SEO reports show position changes. Ours show what it's worth in dollars."
- "[Partner archetype] went from page 3 to top 5 in 4 weeks. Not a fluke — here's the playbook."

## Anti-Patterns

- Posting average-position charts (they lie).
- Claiming causation without a concrete change to point to.
- "SEO is not dead" — tired angle, skip.

## Creative Default

- **GSC screenshot** with the query + position line visible (anonymized).
- Or a **custom chart** from `render-time-series-chart` on the keyword's history.
