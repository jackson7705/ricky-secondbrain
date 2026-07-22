# Ricky's specialist agents

73 named specialist subagents Ricky can dispatch via the `Agent` tool. The
Claude Agent SDK auto-discovers every `*.md` here because the chat engine runs
with `setting_sources: ["user", "project"]` and `cwd = ~/SecondBrain` — no
registration needed. Drop a valid agent file in, and it becomes dispatchable.

## Roster (curated "agency" set)

| Division | # | Examples |
|---|---|---|
| marketing | 36 | SEO Specialist, AI Citation Strategist, AEO Foundations Architect, Content Creator, Social Media Strategist, Email Strategist, PR & Comms |
| sales | 9 | Deal Strategist, Discovery Coach, Pipeline Analyst, Outbound Strategist, Offer & Lead-Gen Strategist |
| design | 9 | brand / UX / visual specialists |
| paid-media | 7 | PPC Strategist, Paid Social Strategist |
| project-management | 7 | delivery / ops specialists |
| finance | 5 | Financial Analyst, Bookkeeper & Controller |

## How Ricky uses them

Ricky dispatches a specialist when a task matches its expertise (e.g. an SEO
audit → *SEO Specialist*; an AEO/citation question → *AI Citation Strategist*).
The specialist does the **thinking/analysis and returns text to Ricky**; Ricky
still produces any client-facing deliverable through the **`locafy-documents`**
skill so it comes out on-brand (Locafy logo, teal palette). Specialists are
generic by design — the branding lives at Ricky's level, not theirs.

## Source & license

Vendored from **[msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents)**
(MIT — see `LICENSE.agency-agents`). Only the agency-relevant divisions were
imported; engineering/GIS/healthcare/etc. were left out to keep Ricky's roster
lean. To add or refresh: copy division `*.md` files here and commit — no code
changes required.
