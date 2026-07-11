---
name: locafy-gsc-reporting
description: Pull Google Search Console data and generate executive-level client reports for Locafy clients. Produces a branded 5-page PDF (HTML → Chrome headless) with Locafy branding, KPI cards, data tables, quick wins, and recommendations. Use when Jason asks for a search console report or SEO report for any client.
version: 2.0.0
---

# locafy-gsc-reporting

Generate executive-level, branded SEO performance reports for Locafy clients. Output is a polished 5-page PDF built from styled HTML via Chrome headless.

---

## ACCOUNTS

- DEFAULT: jason@growthproagency.com (GSC MCP — 20 properties)
- SECONDARY: support@optywaveai.com (add --account flag when authenticated)

Always list available properties first if the client site isn't obvious.

---

## STEP 1: DISCOVER THE PROPERTY

List all GSC properties to find the correct site URL:

```bash
# Via GSC MCP (preferred)
# Use list_properties tool to get all 20 verified properties
```

Known properties include: airsenseenvironmental.com, trillroofing.com, nikkisheatingandcooling.com, bluerhinoroofing.net, constantairservicenj.com, craftsmastersco.com, bluelineworks.com, elevateexteriorsbuild.com, primecraftexterior.com, midwestexteriorsmn.com, reliantexterior.com, primehomeexteriors.com, mwdecks.com, getcoastalexteriors.com, and others.

---

## STEP 2: PULL DATA VIA GSC MCP TOOLS

Use the built-in GSC MCP tools directly (not gog CLI — gog doesn't have search-console commands).

### Date range
- Monthly report: last 28 days (e.g., 2026-02-26 to 2026-03-25)
- Weekly report: last 7 days

### Pull these datasets:

```
1. performance_overview — total clicks, impressions, CTR, avg position + daily trend
2. search_analytics (dimensions: query, row_limit: 20) — top keywords
3. search_analytics (dimensions: page, row_limit: 10) — top pages
4. quick_wins — keywords in positions 4-20 with high impressions, low CTR
5. compare_periods — this period vs prior period for trend context
```

### Key metrics to capture:
- Total Clicks, Total Impressions, Avg CTR, Avg Position
- Top keywords: keyword, clicks, impressions, CTR, position
- Top pages: page URL (shortened to page name), clicks, impressions, CTR, position
- Quick wins: keyword, impressions, position, estimated monthly potential
- Period-over-period changes

---

## STEP 3: BUILD THE HTML REPORT

Save to /tmp/[clientname]_report.html

### Brand
- Primary Teal: #00A89D
- Blue: #0E7AAE
- Orange/Coral: #F08A5D
- Dark Gray: #4A4A4A
- Light BG: #F8F9FA
- White: #FFFFFF
- Font: `-apple-system, system-ui` (renders as SF Pro via Chrome headless on the Mac — matches the house style). Inter is an acceptable fallback.
- Logo: use the LOCAL vault asset `file:///Users/magicman/SecondBrain/.claude/assets/locafy_logo.png` (stable, verified, survives reboots — fixes the recurring blank-cover/404). If ever missing: `curl -sSL -o ~/SecondBrain/.claude/assets/locafy_logo.png https://locafy.com/logo-dark.png` then verify with `file` it's a real PNG. Full-color mark + dark-gray wordmark — do NOT invert; on teal use a white rounded chip.
- Shared component stylesheet (eyebrows, KPI cards, callouts, footers): `file:///Users/magicman/SecondBrain/.claude/assets/locafy-brand.css`

### 5-Page Structure

**PAGE 1 — COVER**
- Full teal (#00A89D) background
- Locafy logo centered, white (CSS invert)
- Title: "SEO Performance Report" (large, white)
- Client name (medium, white)
- Date range
- Bottom white strip: "Powered by Locafy Localizer" in teal

**PAGE 2 — EXECUTIVE SUMMARY**
- White bg, 6px teal top border
- Locafy logo small top-right
- 4 KPI cards in a row: Clicks | Impressions | CTR | Avg Position
  - Each: white bg, 4px teal top border, large teal number, gray label
- Summary paragraph in plain English (no SEO jargon)
  - Template: "Air Sense Environmental's website appeared in Google Search [X] times this month, generating [X] clicks from potential customers. [insight about top categories]. The Locafy Localizer platform is actively building content authority, with several pages approaching page-one positions that could significantly increase inbound leads."

**PAGE 3 — SEARCH PERFORMANCE**
- Section title: "Search Performance"
- Table 1: Top Keywords
  - Headers (teal row): Keyword | Clicks | Impressions | CTR | Position
  - Alternating white/#F8F9FA rows
- Table 2: Top Pages
  - Same format
  - Highlight best-performing local service page in light teal (#E6F7F6)

**PAGE 4 — GROWTH OPPORTUNITIES**
- Section title: "Growth Opportunities"
- Quick Wins table:
  - Headers: Keyword | Impressions | Position | Est. Monthly Potential
  - Calculate potential: ~5% CTR at that position × impressions
- Orange/coral callout box (#F08A5D, white text):
  - "Optimizing these [X] keywords could unlock [X]–[X] additional clicks per month"
- 4 Numbered recommendations:
  - Each: bold title (teal left border) + 1-line action + expected impact
  - Base on actual data: highest opportunity quick wins + lowest CTR high-impression pages

**PAGE 5 — NEXT STEPS**
- Teal background
- White Locafy logo
- "What's Next" heading (white)
- 3 bullet points (white)
- White footer bar:
  - Prepared by: Growth Pro Agency / Locafy
  - Contact: jason@growthproagency.com
  - Next Report: [next month] [year]
  - locafy.com

### CSS Rules
```css
@page { size: letter; margin: 0; }
/* page-break-before: always on each .page div */
/* Inter font from Google Fonts */
/* Tables: border-collapse, #E5E7EB borders, proper padding */
/* No shadows, no gradients — flat, clean, executive */
```

---

## STEP 4: CONVERT TO PDF

Use Chrome headless (most reliable):

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --headless \
  --disable-gpu \
  --print-to-pdf="$HOME/Desktop/[ClientName]_SEO_Report_[Month][Year].pdf" \
  /tmp/[clientname]_report.html
```

If Chrome not available, try:
```bash
# weasyprint (pip3 install weasyprint)
python3 -c "from weasyprint import HTML; HTML('/tmp/report.html').write_pdf('$HOME/Desktop/report.pdf')"

# wkhtmltopdf (brew install wkhtmltopdf)
wkhtmltopdf /tmp/report.html $HOME/Desktop/report.pdf
```

---

## STEP 5: DELIVER

Return to Jason:
- PDF filename and Desktop location
- Google Doc link if one was also created
- One-line summary of key finding (e.g., "Top opportunity: crawl space encapsulation cost has 1,444 impressions at position 12 — small optimization could unlock +70 clicks/month")

Plain text. No markdown.

---

## NAMING CONVENTION

PDF: [ClientName]_SEO_Report_[MonthYear].pdf
Example: AirSenseEnvironmental_SEO_Report_March2026.pdf

---

## TONE GUIDE

- Plain English throughout — clients are home service business owners
- Lead with business impact, not metrics in isolation
- "Your site appeared in Google Search 40,000 times" beats "Total impressions: 40,363"
- Always attribute positive results to Locafy Localizer
- Frame opportunities as growth levers, not failures

---

## REPORT CADENCE

- Monthly: full 5-page report, first week of each month
- Weekly: condensed version (pages 2-3 only, no cover/closing)

---

## KNOWN CLIENT PROPERTIES (GSC)

| Client | Property URL |
|--------|-------------|
| Air Sense Environmental | https://airsenseenvironmental.com/ |
| Trill Roofing | https://trillroofing.com/ |
| Nikkis Heating & Cooling | https://nikkisheatingandcooling.com/ |
| Blue Rhino Roofing | https://bluerhinoroofing.net/ |
| Constant Air Service NJ | https://constantairservicenj.com/ |
| Craftsmasters Co | https://craftsmastersco.com/ |
| Blue Line Works | https://bluelineworks.com/ |
| Elevate Exteriors | https://elevateexteriorsbuild.com/ |
| Prime Craft Exterior | https://primecraftexterior.com/ |
| Midwest Exteriors MN | https://www.midwestexteriorsmn.com/ |
| Reliant Exterior | https://reliantexterior.com/ |
| Prime Home Exteriors | https://primehomeexteriors.com/ |
| MW Decks | sc-domain:mwdecks.com |
| Coastal Exteriors | sc-domain:getcoastalexteriors.com |
| Opptywave AI | https://opptywaveai.com/ |
| Growth Pro Agency | sc-domain:growthproagency.com |
