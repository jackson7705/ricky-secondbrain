#!/usr/bin/env python3
"""memory_lint.py — the "Lint" leg of the LLM-Wiki pattern for Ricky's vault.

Health-checks Dynamous/Memory for the bookkeeping drift LLMs are supposed to own:
stale index, orphaned entity pages, missing cross-references, past-due dated
claims, broken filesystem references, and duplicate-entity candidates.

DRY-RUN (default): reports findings only, changes nothing.
Deterministic checks run here. Semantic checks (contradictions, "is this claim
still true") need the Agent SDK pass and are listed but not run in dry-run.

    uv run --project .claude/scripts python .claude/scripts/memory_lint.py --dry-run
"""
from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path

VAULT = Path(__file__).resolve().parents[1].parent / "Dynamous" / "Memory"
ENTITY_DIRS = ["people", "projects", "vendors", "references"]
TODAY = datetime.now().date()

CODE_BLOCK = re.compile(r"```.*?```", re.S)
WIKILINK = re.compile(r"\[\[([^\]|#]+)")
ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
LONG_DATE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})\b")
EXPIRY_NEAR = re.compile(r"(expir\w*|valid until|until|as of|by|renew\w*|due)\b", re.I)
PATHREF = re.compile(r"(~|/Users/[\w.-]+)(/[\w.\-/]+)")

MONTHS = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], start=1)}


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def strip_code(t: str) -> str:
    return CODE_BLOCK.sub("", t)


SEMANTIC_PROMPT = """You are auditing a personal knowledge vault for a busy executive (Jason, COO of Locafy). Ricky is his AI assistant. Find ONLY high-confidence bookkeeping problems in these three categories:

1. CONTRADICTION — a claim in an entity page or MEMORY.md that conflicts with a MORE RECENT daily log or another page (e.g. a page says a tool "runs on X" but a recent log shows it moved to Y).
2. STALE — a claim written as currently-true that is very likely no longer true (past dated statuses, "currently…", superseded facts).
3. MERGE — two pages that are clearly the SAME real-world entity under different names.

Be conservative — skip anything you're not confident about. It is better to report nothing than to report a false positive.

Output ONLY a JSON array (no prose). Each element:
{"type":"CONTRADICTION|STALE|MERGE","pages":["folder/File.md",...],"issue":"one sentence","suggestion":"one sentence, concrete"}
If nothing qualifies, output []."""


def run_semantic() -> int:
    import json
    import subprocess

    facts = []
    for d in ENTITY_DIRS:
        for p in sorted((VAULT / d).glob("*.md")):
            facts.append(f"### {d}/{p.name}\n{read(p)[:2500]}")
    mem = read(VAULT / "MEMORY.md")[:6000]
    dailies = sorted((VAULT / "daily").glob("20*.md"))[-8:]
    recent = "\n\n".join(f"### DAILY {p.name}\n{read(p)[:1800]}" for p in dailies)
    payload = (f"{SEMANTIC_PROMPT}\n\n=== MEMORY.md ===\n{mem}\n\n"
               f"=== ENTITY PAGES ===\n" + "\n\n".join(facts) +
               f"\n\n=== RECENT DAILY LOGS ===\n{recent}\n")
    print(f"[semantic] auditing {len(facts)} entity pages + MEMORY + {len(dailies)} dailies "
          f"(~{len(payload)//4} tokens) via claude…")
    try:
        res = subprocess.run(["claude", "-p"], input=payload, capture_output=True,
                             text=True, timeout=420)
    except Exception as exc:
        print(f"[semantic] claude call failed: {exc}")
        return 1
    out = (res.stdout or "").strip()
    a, b = out.find("["), out.rfind("]")
    findings = []
    if a != -1 and b != -1:
        try:
            findings = json.loads(out[a:b + 1])
        except Exception:
            print("[semantic] could not parse JSON; raw output:\n" + out[:1500])
            return 1
    # append to LINT.md (propose-only)
    lint = VAULT / "LINT.md"
    body = lint.read_text(encoding="utf-8") if lint.exists() else f"# LINT — vault health ({TODAY})\n"
    section = [f"\n## 🧠 Semantic findings — LLM, propose-only ({TODAY}) — {len(findings)} item(s)\n"]
    for f in findings:
        section.append(f"- [ ] **{f.get('type','?')}** · {', '.join('`'+x+'`' for x in f.get('pages',[]))}\n"
                       f"    - {f.get('issue','')}\n    - → {f.get('suggestion','')}\n")
    if not findings:
        section.append("- none flagged this run\n")
    # replace an existing semantic section if present, else append
    body = re.sub(r"\n## 🧠 Semantic findings.*?(?=\n## |\Z)", "", body, flags=re.S)
    lint.write_text(body.rstrip() + "\n" + "".join(section), encoding="utf-8")
    print(f"[semantic] {len(findings)} finding(s) written to {lint}")
    for f in findings:
        print(f"  • {f.get('type')}: {f.get('issue','')[:100]}")
    return 0


def main(dry_run: bool) -> int:
    md = [p for p in VAULT.rglob("*.md") if ".trash" not in p.parts]
    text = {p: read(p) for p in md}
    print(f"=== memory_lint DRY-RUN — {TODAY} — {len(md)} pages in {VAULT} ===\n")

    # link graph
    inbound: dict[str, int] = {}
    for p, t in text.items():
        for m in WIKILINK.findall(t):
            inbound[m.strip().lower()] = inbound.get(m.strip().lower(), 0) + 1

    entities = {}  # name(lower) -> path
    for d in ENTITY_DIRS:
        for p in (VAULT / d).glob("*.md"):
            entities[p.stem.lower()] = p

    # 1) ORPHANS — entity page with no inbound links AND no outbound links
    orphans = []
    for name, p in entities.items():
        outbound = len(WIKILINK.findall(text.get(p, "")))
        if inbound.get(name, 0) == 0 and outbound == 0:
            orphans.append(p.relative_to(VAULT))
    print(f"[1] ORPHANED entity pages (no links in or out): {len(orphans)}")
    for o in sorted(orphans)[:15]:
        print(f"      - {o}")
    if len(orphans) > 15:
        print(f"      … +{len(orphans)-15} more")

    # 2) MISSING LINKS — entity name appears unlinked in another page's prose
    missing = []
    for name, ep in entities.items():
        if len(name) < 4:
            continue
        pat = re.compile(r"(?<!\[)\b" + re.escape(ep.stem) + r"\b(?!\]|\|)")
        hits = 0
        for p, t in text.items():
            if p == ep:
                continue
            body = strip_code(t)
            # count bare mentions not already inside a [[...]]
            for m in pat.finditer(body):
                s = body[max(0, m.start()-2):m.start()]
                if "[[" not in body[max(0, m.start()-30):m.start()]:
                    hits += 1
        if hits:
            missing.append((ep.stem, hits))
    missing.sort(key=lambda x: -x[1])
    total_missing = sum(h for _, h in missing)
    print(f"\n[2] MISSING cross-references (entity named in prose, not [[linked]]): "
          f"~{total_missing} across {len(missing)} entities")
    for nm, h in missing[:12]:
        print(f"      - {nm}: ~{h} unlinked mention(s)")

    # 3) STALE MAP — MAP.md 'today/recent dailies' vs newest daily file
    dailies = sorted((VAULT / "daily").glob("20*.md"))
    newest = dailies[-1].stem if dailies else "(none)"
    mapt = text.get(VAULT / "MAP.md", "")
    map_dates = sorted(set(ISO_DATE.findall(mapt)))
    map_newest = "-".join(map_dates[-1]) if map_dates else "(none)"
    stale_map = map_newest != newest
    print(f"\n[3] STALE INDEX (MAP.md): {'STALE' if stale_map else 'ok'}")
    print(f"      MAP.md newest daily referenced: {map_newest}")
    print(f"      actual newest daily on disk:    {newest}")

    # 4) PAST-DUE dated claims (date near an expiry/renewal word, in the past)
    past = []
    for p, t in text.items():
        for line in strip_code(t).splitlines():
            if not EXPIRY_NEAR.search(line):
                continue
            found = None
            mi = ISO_DATE.search(line)
            if mi:
                found = date(int(mi.group(1)), int(mi.group(2)), int(mi.group(3)))
            else:
                ml = LONG_DATE.search(line)
                if ml:
                    found = date(int(ml.group(3)), MONTHS[ml.group(1)[:3]], int(ml.group(2)))
            if found and found < TODAY:
                past.append((p.relative_to(VAULT), found, line.strip()[:90]))
    print(f"\n[4] PAST-DUE dated claims (expiry/renewal date already passed): {len(past)}")
    for rp, d, ln in sorted(past, key=lambda x: x[1])[:12]:
        print(f"      - {rp} [{d}] {ln}")

    # 5) BROKEN filesystem references
    broken = []
    for p, t in text.items():
        for m in PATHREF.finditer(strip_code(t)):
            raw = (m.group(1) + m.group(2)).rstrip(".,`) ")
            fp = Path(raw.replace("~", str(Path.home()), 1))
            if len(fp.parts) > 3 and not fp.exists():
                broken.append((p.relative_to(VAULT), raw))
    # dedup
    seen = set(); broken = [(a, b) for a, b in broken if (a, b) not in seen and not seen.add((a, b))]
    print(f"\n[5] BROKEN path references (cited file/dir doesn't exist): {len(broken)}")
    for rp, raw in broken[:12]:
        print(f"      - {rp} → {raw}")

    # 6) DUPLICATE-entity candidates (fuzzy filename overlap)
    names = list(entities)
    dups = []
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            a, b = names[i], names[j]
            aw, bw = set(a.split()), set(b.split())
            if aw & bw and (aw <= bw or bw <= aw) and a != b:
                dups.append((entities[a].relative_to(VAULT), entities[b].relative_to(VAULT)))
    print(f"\n[6] DUPLICATE-entity candidates (name overlap): {len(dups)}")
    for a, b in dups[:10]:
        print(f"      - {a}  ≈  {b}")

    # ── APPLY (safe, reversible fixes only) ─────────────────────────────
    map_fixed = False
    links_added = 0
    files_linked = 0
    if not dry_run:
        # fix 3: refresh MAP.md Today + Recent Dailies
        recent = [d.stem for d in dailies][-8:][::-1]
        if stale_map and recent:
            today_block = f"## Today\n\n- [[{recent[0]}]] — today's daily log\n\n"
            recent_block = "## Recent Dailies\n\n" + "\n".join(f"- [[{d}]]" for d in recent) + "\n"
            new = re.sub(r"## Today\n.*?(?=\n## )", today_block, mapt, count=1, flags=re.S)
            new = re.sub(r"## Recent Dailies\n.*?(?=\n## |\Z)", recent_block, new, count=1, flags=re.S)
            if new != mapt:
                (VAULT / "MAP.md").write_text(new, encoding="utf-8")
                map_fixed = True

        # fix 2: backfill FIRST-occurrence [[links]] per page (conservative)
        for p, t in text.items():
            if p.name in ("MAP.md", "LINT.md"):
                continue  # index files: never auto-link (and don't clobber the refresh)
            lines = t.split("\n")
            in_code = in_fm = changed = False
            done_here: set[str] = set()
            for idx, line in enumerate(lines):
                s = line.strip()
                if idx == 0 and s == "---":
                    in_fm = True; continue
                if in_fm:
                    if s == "---": in_fm = False
                    continue
                if s.startswith("```"):
                    in_code = not in_code; continue
                if in_code:
                    continue
                for name, ep in entities.items():
                    if ep == p or name in done_here or len(ep.stem) < 4:
                        continue
                    if "[[" + ep.stem in line:
                        done_here.add(name); continue
                    m = re.search(r"(?<![\[\w])" + re.escape(ep.stem) + r"(?![\w\]])", lines[idx])
                    if m:
                        pre = lines[idx][:m.start()]
                        if pre.count("[[") > pre.count("]]"):
                            continue
                        lines[idx] = lines[idx][:m.start()] + "[[" + ep.stem + "]]" + lines[idx][m.end():]
                        done_here.add(name); links_added += 1; changed = True
                        break
            if changed:
                p.write_text("\n".join(lines), encoding="utf-8")
                files_linked += 1

        # write LINT.md queue for the judgment calls
        lint = [f"---\nname: LINT\ntype: index\n---\n\n# LINT — vault health ({TODAY})\n",
                "> Auto-generated by `memory_lint.py`. Auto-fixes applied; items below need your call.\n",
                f"\n## Auto-applied this run\n- MAP.md refreshed: {'yes' if map_fixed else 'no (already current)'}\n"
                f"- Cross-reference links added: **{links_added}** across **{files_linked}** pages\n",
                f"\n## ⚠️ Past-due dated claims — done or drop? ({len(past)})\n"]
        for rp, d, ln in sorted(past, key=lambda x: x[1]):
            lint.append(f"- [ ] `{rp}` [{d}] {ln}\n")
        lint.append(f"\n## Orphaned pages — link or archive? ({len(orphans)})\n")
        for o in sorted(orphans):
            lint.append(f"- [ ] `{o}`\n")
        lint.append("\n## Deferred to the semantic (LLM) pass\n"
                    "- [ ] Contradictions vs recent daily logs / MEMORY.md\n"
                    "- [ ] Semantic staleness ('runs on X', 'currently …')\n"
                    "- [ ] Same-entity merges across names (e.g. Kalpraj Solutions ↔ Backlink Base)\n")
        (VAULT / "LINT.md").write_text("".join(lint), encoding="utf-8")
        print(f"\n=== APPLIED ===")
        print(f"  MAP.md refreshed: {map_fixed}")
        print(f"  links added: {links_added} across {files_linked} pages")
        print(f"  wrote {VAULT / 'LINT.md'} ({len(past)} past-due + {len(orphans)} orphans queued)")

    print("\n=== needs the Agent SDK pass (NOT run here) ===")
    print("  • Contradictions, semantic staleness, same-entity merges")
    print("\n(DRY-RUN — nothing changed.)" if dry_run else "")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", dest="dry_run", action="store_false")
    ap.add_argument("--semantic", action="store_true", help="Run the LLM propose-only pass")
    args = ap.parse_args()
    if args.semantic:
        raise SystemExit(run_semantic())
    main(args.dry_run)
