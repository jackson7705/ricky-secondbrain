"""Entity linker — wraps known names in [[wikilinks]] for Obsidian's graph.

Used by `append_to_daily_log` (heartbeat) and `flush.py` (chat sessions) so
every new write contributes to the graph instead of producing isolated nodes.

Design rules:
  - Conservative: never link inside code blocks, never double-wrap, never link
    inside an existing [[wikilink]] or markdown link.
  - Longest-match-first so "Citations+" wins over "Citations".
  - Word-boundary aware so "Locafyer" doesn't match "Locafy".
  - Case-sensitive on first letter (so "locafy" in URLs/code doesn't match).

Adding a new entity:
  Add a tuple (pattern, link_target) below. `pattern` is matched literally as a
  word; `link_target` is what goes inside [[...]]. To get a display alias use
  the `display` 3rd element: ("Growth Pro Agency", "Growth Pro", "Growth Pro Agency").

The corresponding `Memory/people/<link_target>.md` (or projects/, vendors/)
must exist for Obsidian to resolve the link. Stubs are created by
`vault_stubs.py` once and committed to the vault.
"""

from __future__ import annotations

import re

# (pattern, link_target [, display_text])
# Order matters only for documentation — we sort by length descending at runtime.
_ENTITIES: list[tuple[str, ...]] = [
    # ── People (Memory/people/) ──────────────────────────────────────
    ("Paul Harvell", "Paul Harvell"),
    ("Mark Demilio", "Mark Demilio"),
    ("Chris Kealley", "Chris Kealley"),
    ("Daryl", "Daryl"),
    ("Maria", "Maria"),
    ("Gavin", "Gavin"),
    ("Melvin", "Melvin"),
    ("Ray", "Ray"),  # only used in Locafy/Experience.com context per dailies
    # ── Companies / brands (Memory/projects/) ────────────────────────
    ("Locafy", "Locafy"),
    ("Wonderly", "Wonderly"),
    ("Growth Pro Agency", "Growth Pro", "Growth Pro Agency"),
    ("Growth Pro", "Growth Pro"),
    ("Experience.com", "Experience.com"),
    ("NXT4 Life Training", "NXT4 Life Training"),
    ("NXT4", "NXT4 Life Training", "NXT4"),
    # ── Products / internal codenames (Memory/projects/) ─────────────
    ("Localizer", "Localizer"),
    ("MapBoost", "MapBoost"),
    ("Citations+", "Citations+"),
    ("Citations", "Citations"),
    ("Poseidon", "Poseidon"),
    ("WriteOS", "WriteOS"),
    ("GBPOS", "GBPOS"),
    ("EntityOS", "EntityOS"),
    # ── Tools / SaaS (Memory/vendors/) ───────────────────────────────
    ("ClickUp", "ClickUp"),
    ("Fathom", "Fathom"),
    ("Anthropic", "Anthropic"),
    ("BlueBubbles", "BlueBubbles"),
    ("Ricky Bobby", "Ricky Bobby"),
    ("Slack", "Slack"),
    ("LinkedIn", "LinkedIn"),
    ("Google Search Console", "Google Search Console"),
    ("Ahrefs", "Ahrefs"),
    ("Stripe", "Stripe"),
    ("SuperSend", "SuperSend"),
    ("Backlink Factory", "Backlink Factory"),
    ("GHL", "GHL"),
    ("Entity Elevation", "Entity Elevation"),
    ("Blacklist Alliance", "Blacklist Alliance"),
    ("Clearout Phone", "Clearout Phone"),
    ("Spectrum", "Spectrum"),
    ("Acronis", "Acronis"),
    ("Liquid Web", "Liquid Web"),
    ("Hostinger", "Hostinger"),
    ("Railway", "Railway"),
    ("Elestio", "Elestio"),
    ("Supabase", "Supabase"),
    ("DoorDash", "DoorDash"),
    ("Vons", "Vons"),
    ("Starbucks", "Starbucks"),
    ("Southwest Airlines", "Southwest Airlines"),
    ("Southwest", "Southwest Airlines", "Southwest"),
    ("South Point Hotel & Casino", "South Point Hotel & Casino"),
    ("South Point", "South Point Hotel & Casino", "South Point"),
    # ── Concepts (link to knowledge/concepts via slug) ───────────────
    # Display the human term, link to the kebab-case slug.
    ("AEO", "concepts/aeo", "AEO"),
    ("GBP", "concepts/gbp", "GBP"),
    ("Localizer platform", "concepts/locafy-mapboost-naming", "Localizer platform"),
]


def _build_replacement_table() -> tuple[re.Pattern[str], dict[str, str]]:
    """Build a single combined regex + lookup table for one-pass replacement.

    Single-pass avoids the nested-wrap bug where a longer alias's display text
    contained a shorter entity name that the next pattern then re-matched.
    """
    sorted_entities = sorted(_ENTITIES, key=lambda e: -len(e[0]))
    lookup: dict[str, str] = {}
    alts: list[str] = []
    for entry in sorted_entities:
        if len(entry) == 2:
            phrase, target = entry
            display = phrase
        else:
            phrase, target, display = entry  # type: ignore[misc]
        replacement = f"[[{target}]]" if display == target else f"[[{target}|{display}]]"
        lookup[phrase] = replacement
        alts.append(re.escape(phrase))

    # One regex with alternation. Order matters in alternation when patterns
    # can overlap — Python's re is leftmost-first which preserves length-desc
    # because we sorted that way. Lookbehind/lookahead avoid wrapping inside
    # existing [[wikilinks]] or alphanumeric runs.
    pattern = re.compile(
        rf"(?<![\w\[\|])(?:{'|'.join(alts)})(?![\w\]])"
    )
    return pattern, lookup


_PATTERN, _LOOKUP = _build_replacement_table()

# Match fenced and inline code so we can preserve them untouched.
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
# Pre-existing wikilinks — stash them so they don't get touched.
_WIKILINK_RE = re.compile(r"\[\[[^\[\]]+\]\]")


def wrap_entities(text: str) -> str:
    """Return `text` with known entities wrapped in [[wikilinks]].

    Skips:
      - content inside fenced ```code blocks```
      - content inside `inline code`
      - content already inside [[existing wikilinks]]
    """
    if not text:
        return text

    placeholders: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"\x00P{len(placeholders) - 1}\x00"

    # Order matters: protect code first (might contain `[[` literals), then
    # protect existing wikilinks.
    stashed = _CODE_BLOCK_RE.sub(_stash, text)
    stashed = _INLINE_CODE_RE.sub(_stash, stashed)
    stashed = _WIKILINK_RE.sub(_stash, stashed)

    # Single-pass replacement — each character matches at most once.
    stashed = _PATTERN.sub(lambda m: _LOOKUP[m.group(0)], stashed)

    for idx, original in enumerate(placeholders):
        stashed = stashed.replace(f"\x00P{idx}\x00", original)
    return stashed


# Public helper: build a YAML frontmatter block for a daily log file.
def daily_frontmatter(date_str: str) -> str:
    """Standard frontmatter for daily log files. Idempotent — safe to inject
    only if the file doesn't already start with `---`."""
    return (
        "---\n"
        f"date: {date_str}\n"
        "type: daily\n"
        "tags: [daily, second-brain]\n"
        "---\n\n"
    )
