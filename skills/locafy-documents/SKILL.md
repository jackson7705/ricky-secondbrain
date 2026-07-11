---
name: locafy-documents
description: Produce branded Locafy PDF deliverables (briefings, one-pagers, reports, proposals, decks) from styled HTML via Chrome headless, then upload to Google Drive and return a share link. ALWAYS use this for any document/briefing/report/PDF Jason asks for — it is the branded path. Do NOT fall back to the generic `pdf`/fpdf2 skill, which produces unbranded output.
version: 2.0.0
tags: [docs, pdf, reports, briefings, proposals, drive, locafy, branding]
---

# locafy-documents (branded)

Every document Jason asks for goes out on the **Locafy template** — real logo, real brand
colors, "Powered by Locafy Localizer" footer. This skill replaces the generic `pdf` skill for
any deliverable. If a request implies a real file (briefing, report, one-pager, PDF, write-up,
proposal, deck), build it HERE.

> Why this exists: a June 2026 "always deliver a PDF to Drive" directive accidentally routed docs
> to the generic `pdf` skill, stripping the brand. This skill is the branded replacement. The
> deliverable directive in `.claude/chat/engine.py` now points here.

---

## QUALITY BAR — match the house style

The standard is the **Locafy report house style** (the Wonderly SEO Plan, Poseidon Founding
Offer, and Job Description reports from May 2026). That design system was lost in the OpenClaw→
SecondBrain migration; it is reconstructed here. Every doc must look like it came from that set:
eyebrows, heavy navy headlines, KPI stat cards, meta strips, colored callout boxes, three-part
footers. A bare logo + a key-value table is NOT good enough.

**Use the prebuilt stylesheet — do not hand-roll CSS.** Link it at the top of every doc:
```html
<link rel="stylesheet" href="file:///Users/magicman/SecondBrain/.claude/assets/locafy-brand.css">
```
(If Chrome fails to load it via file://, paste the file's contents into a `<style>` tag instead.)
It defines every component below as a CSS class. You assemble components; you don't restyle them.

## BRAND tokens (already in the stylesheet — do not invent colors)

| Token | Value | Use |
|-------|-------|-----|
| Teal | `#00A89D` | Primary: cover, top rule, eyebrows, KPI numbers, table headers, accents |
| Coral | `#F08A5D` | Pills, solid callouts, CTA buttons, footer status text |
| Navy | `#1E2A38` | Headlines, dark callout/CTA boxes, meta values |
| Body Gray | `#4A4A4A` | Body text |
| Light BG / Line | `#F8F9FA` / `#E5E7EB` | Panel fills, alt rows, borders |
| Green / Red / Amber | `#2ECC71` / `#E5484D` / `#E9A23B` | Callout & card left-borders (good / caution / warning) |
| **Font** | `-apple-system, system-ui` (renders as **SF Pro** on the Mac) | Headlines weight 800; body 400/600. NOT Inter/Arial. |

**Logo — use the real one, never a text wordmark:**
- Local file (stable, verified, ALWAYS use this): `file:///Users/magicman/SecondBrain/.claude/assets/locafy_logo.png`
- It is the full-color Locafy pinwheel + dark-gray "Locafy" wordmark on transparent/white. **Do NOT invert, recolor, distort, or rotate it.**
- On a **white** background: drop it in as-is.
- On the **teal cover**: place it inside a white rounded chip (padding ~16px, border-radius 12px) — never recolor the mark itself.
- If the local file is ever missing, re-fetch once: `curl -sSL -o ~/SecondBrain/.claude/assets/locafy_logo.png https://locafy.com/logo-dark.png` then verify with `file` that it's a real PNG (a 404 silently produces a blank cover). Never substitute a CSS/text wordmark.

Design principles: flat and executive — no shadows, no gradients. Data-forward. Locafy is always
positioned as the technology leader ("the engine behind your results"), not a vendor.

---

## WORKFLOW (every deliverable)

1. **Build styled HTML** at `/tmp/<slug>_doc.html` using the template below. One `.page` div per page; `page-break-before: always`.
2. **Render to PDF** with Chrome headless:
   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
     --headless --disable-gpu \
     --print-to-pdf="/tmp/<slug>.pdf" \
     /tmp/<slug>_doc.html
   ```
   Fallbacks if Chrome is unavailable: `weasyprint` then `wkhtmltopdf`.
3. **Verify** the PDF is non-empty and the cover isn't blank (logo loaded): `ls -la /tmp/<slug>.pdf`.
4. **Upload to Google Drive** and make it shareable, then return the link:
   ```python
   from integrations import drive_api
   link = drive_api.upload_file("/tmp/<slug>.pdf", "119jT4HsjLV9Dm-ib1UScX0TYPn2ANaW_")  # Ricky Briefings (growthpro)
   # business-scoped work → route to the relevant Locafy/Wonderly/Air Sense folder instead
   ```
   Make it `anyoneWithLink` reader so Jason can open it on his phone.
5. **Reply** with a 1–3 sentence cover note ending in the Drive `webViewLink`. Do NOT dump the document body into the chat.

Naming: `<Subject>_<Type>_<MonthYear>.pdf` (e.g. `AirSense_Briefing_June2026.pdf`).

---

## DOCUMENT SKELETON

```html
<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="file:///Users/magicman/SecondBrain/.claude/assets/locafy-brand.css">
</head><body>

<!-- COVER -->
<div class="cover">
  <div class="chip"><img src="file:///Users/magicman/SecondBrain/.claude/assets/locafy_logo.png"></div>
  <h1>[Document Title]</h1>
  <div class="sub">[One-line subtitle]</div>
  <div class="ghost">For Internal Use Only</div>
  <div class="strip"></div>
</div>

<!-- BODY PAGE -->
<div class="page">
  <div class="toprule"></div>
  <div class="hdr">
    <img src="file:///Users/magicman/SecondBrain/.claude/assets/locafy_logo.png">
    <div class="eyebrow">Section 01 — Executive Summary<span class="sub">Locafy</span></div>
  </div>

  <h2 class="title">[Big navy headline that makes the point.]</h2>
  <div class="subhead">[Supporting one-liner.]</div>

  <!-- meta strip (key facts) -->
  <div class="meta">
    <div class="cell"><div class="k">Document Type</div><div class="v">Capabilities Overview</div></div>
    <div class="cell"><div class="k">Prepared By</div><div class="v">Locafy Limited</div></div>
    <div class="cell"><div class="k">Audience</div><div class="v">Enterprise Brands</div></div>
  </div>

  <!-- KPI cards -->
  <div class="kpis">
    <div class="kpi"><div class="n">~3.6K</div><div class="k">Monthly Searches</div><div class="d">Core keyword volume.</div></div>
    <div class="kpi"><div class="n">Top 3</div><div class="k">Target by Mo 6</div><div class="d">Organic position goal.</div></div>
    <div class="kpi"><div class="n">150+</div><div class="k">Leads / Mo</div><div class="d">Conservative model.</div></div>
  </div>

  <div class="sec"><span class="bar"></span><h3>The Play</h3></div>
  <p>Body copy with <strong>bold lead-ins</strong> and inline <code>highlights</code>.</p>
  <ul><li><strong>Point one</strong> — detail.</li><li><strong>Point two</strong> — detail.</li></ul>

  <!-- callouts: .coral / .soft / .green / .amber / .navy -->
  <div class="box coral"><span class="lbl">The Bet</span><strong>Headline claim</strong> with the supporting sentence.</div>
  <div class="box soft"><span class="lbl">Strategic Opening</span>Context paragraph.</div>

  <div class="foot"><span>Locafy · [Doc Name]</span><span class="mid">For Internal Use Only</span><span>Page 1</span></div>
</div>

</body></html>
```

**Component classes available** (all in `locafy-brand.css`): `.cover` (+`.land` landscape),
`.pill` badge, `h1.hero`, `.eyebrow`, `.sec` vertical-bar header, `.meta` strip, `.kpis/.kpi`
stat cards, `.box` callouts (`.coral .soft .green .amber .navy`), `.cardrow/.card` (`.red .green`
borders), `.price` cards, `.cta` dark bar with `.btn`, `ul.arrow` arrow bullets, `.cols` two-column,
tables (styled by default), `.foot` three-part footer.

### Layout rules (match the references)
- **One-pager** (offer, job desc, brief): portrait `.page`, header + hero + meta strip + 2–4 sections + a `.cta` or strong closing box. Like Poseidon / the Job Description.
- **Multi-page report** (SEO plan, strategy): teal-gradient `.cover`, then numbered section pages (`Section 01 —`, `02 —` …), KPI cards on the summary page, `.foot` with `Page N of M`. Use landscape (`.page.land`, `@page size:letter landscape`) for data-heavy reports like Wonderly.
- Never leave a near-empty page — fill with real substance or tighten to fewer pages.
- Flat and executive: no drop shadows, no gradients except the cover. Let structure carry it.

---

## WHEN GOOGLE-NATIVE IS BETTER

For collaborative docs the client will edit (not a final PDF), create a Google Doc/Slides via
`gog` instead — but still apply the brand: "Powered by Locafy Localizer" subtitle, teal headings,
and the logo. Default for "briefing / report / one-pager / PDF" is the branded PDF path above.

## RELATED
- `locafy-gsc-reporting` — the 5-page SEO report (same brand system, GSC data). This skill is the general-purpose sibling.
