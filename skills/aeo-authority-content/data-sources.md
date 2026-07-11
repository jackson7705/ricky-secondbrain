# Data Sources — Quick Reference

All calls go through the Ahrefs MCP (`mcp__claude_ai_Ahrefs__*`). Before first use, call `mcp__claude_ai_Ahrefs__doc` for the tool's full schema. Monetary values are returned in USD cents (divide by 100 for display).

## Tracked Properties

| Brand | Role | Primary property (GSC/Ahrefs) |
|---|---|---|
| Locafy | Parent product | `locafy.com` |
| Growth Pro Agency | Jason's acquired agency | `growthproagency.com` |
| Partner clients | Anonymized in public posts | Per-partner properties, tracked via Ahrefs projects |

Partners that are NOT to be named publicly without explicit clearance: *all of them, by default*. Anonymize as "a roofing client", "a Southeast HVAC partner", etc.

## Brand Radar (AI-answer citations)

The leading indicator for AEO posts. Detects when tracked brands appear in ChatGPT / Perplexity / Gemini / AI Overview answers.

| MCP tool | Use for |
|---|---|
| `brand-radar-ai-responses` | Actual AI-answer snippets citing a brand. Screenshot gold. |
| `brand-radar-cited-domains` | Which domains show up in AI answers for your topic cluster. |
| `brand-radar-cited-pages` | Which specific pages get cited — inform content strategy. |
| `brand-radar-impressions-overview` / `-history` | How often tracked brands appear in AI answers (volume). |
| `brand-radar-mentions-overview` / `-history` | Mention count trend — directional for SOV moves. |
| `brand-radar-sov-overview` / `-history` | Share-of-voice vs competitors — the headline stat. |
| `management-brand-radar-reports` / `-prompts` | What Brand Radar reports / prompts are already configured. Check before duplicating. |

**Post-worthy thresholds (copied from SKILL.md):**
- AI citation count: +20% week-over-week, OR a brand-new citation on a tracked brand.
- Share-of-Voice: ±10 percentage points vs the 7-day baseline.

## Google Search Console

Jason's own search performance on Growth Pro + Locafy + connected partner properties.

| MCP tool | Use for |
|---|---|
| `gsc-keywords` | Top-performing keywords (picks biggest wins / biggest drops). |
| `gsc-keyword-history` | Drill into a specific keyword's position over time. |
| `gsc-pages` / `gsc-pages-history` | Page-level clicks, impressions, CTR. |
| `gsc-performance-history` | Overall traffic/impression trend. |
| `gsc-positions-history` | Average-position time series (careful — averaged numbers often hide the real story; prefer specific keyword moves). |
| `gsc-ctr-by-position` | Why CTR changed (mix shift vs content change). |
| `gsc-anonymous-queries` | How much traffic is hidden behind anonymized queries (context, not post material). |
| `gsc-metrics-by-country` | For geo-specific angle posts. |

**Post-worthy thresholds:**
- Keyword move ≥5 positions on a top-20 keyword with ≥100 monthly impressions.
- First-ever impressions on a keyword already in top-20.

## Rank Tracker + Keywords Explorer

Useful for competitive and opportunity angles.

| MCP tool | Use for |
|---|---|
| `rank-tracker-overview` | Portfolio-level tracking summary. |
| `rank-tracker-competitors-overview` / `-pages` / `-stats` | Competitor movement — "partner X just knocked competitor Y out of top-3." |
| `rank-tracker-serp-overview` | What the SERP looks like right now for a target keyword. |
| `keywords-explorer-overview` | Volume, difficulty, SERP for a keyword. |
| `keywords-explorer-matching-terms` / `-related-terms` / `-search-suggestions` | Angle exploration when a post needs a concrete keyword hook. |
| `keywords-explorer-volume-history` / `-volume-by-country` | Is demand actually growing? (kills overclaiming.) |

## Site Explorer / Site Audit (secondary — not usually post fuel)

These are for ad-hoc drilling, not the daily scan. `site-explorer-*`, `site-audit-*`. Ignore unless Jason explicitly asks.

## Rendering

When an MCP response's metadata includes `render_with`, call the matching render tool before displaying:

- `mcp__claude_ai_Ahrefs__render-data-table`
- `mcp__claude_ai_Ahrefs__render-scorecard`
- `mcp__claude_ai_Ahrefs__render-time-series-chart`

Do not summarize raw data yourself when a render tool is specified — Jason's UI shows the rendered version.

## Combining Data (the real art)

The strongest posts pair **external narrative** with **own-data proof**:

- "Google AI Overviews just expanded to local queries → *and here's what happened to our partner's impressions the week after.*"
- "Everyone's talking about Perplexity as the new search → *but SOV data says home-services queries still flow through Google.*"
- "A roofing client hit $600K in 5 months → *Brand Radar shows they jumped from 0 to 6 AI citations over that same window.*"

Combine 1 external signal + 1 own-data point whenever possible. That's the authority unlock.

## Limits / Subscription

Check usage periodically with `mcp__claude_ai_Ahrefs__subscription-info-limits-and-usage` — don't burn API quota pulling data for drafts that never ship.
