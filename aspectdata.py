"""Aspects page accessor for the wiki scraper.

Mirrors `shipdata.py`: fetches the [[Aspects]] content page, parses its
Aspect List ``<tabber>`` + wikitables into typed `AspectRecord`s, and builds
RAG-friendly chunks (per-aspect Spec cards + slot-grouped rosters).

Replaces the previous Module:AspectData Lua pipeline — Lua modules were
removed from the wiki and aspect data now lives in the Aspects page tables.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from shipdata import _split_table_rows


_API_URL = "https://vanguard-galaxy.fandom.com/api.php"


# Tabber tab name → canonical slot enum used by AspectRecord. Values mirror
# the `_SLOT_LABEL` keys so the rest of the pipeline stays unchanged.
_TAB_SLOT = {
    "Weapons":     "Weapons",
    "Dronebay":    "Dronebay",
    "Scanner":     "Scanner",
    "Hull":        "Hull",
    "Armor":       "Armor",
    "All Modules": "AllModules",
    "All Items":   "AllItems",
}


# Display labels for slot enum values. Mirrors Module:Aspectbox.SLOT_LABEL so
# the scraped chunks read the same way as the rendered wiki page.
_SLOT_LABEL = {
    "Weapons": "Weapons",
    "Dronebay": "Dronebay",
    "Hull": "Hull",
    "Armor": "Armor",
    "Scanner": "Scanner",
    "AllItems": "All Items",
    "AllModules": "All Modules",
}


def _slot_label(slot: str | None) -> str:
    if slot is None:
        return "any"
    return _SLOT_LABEL.get(slot, slot)


@dataclass(frozen=True)
class AspectRecord:
    key: str
    display_name: str
    slot: str | None = None
    description: str | None = None
    common: bool = True
    size_note: str | None = None
    boost_stats: tuple[dict[str, float | str], ...] = ()

    @classmethod
    def from_dict(cls, key: str, d: dict[str, Any]) -> "AspectRecord":
        # boostStats was a structured field on the old Module:AspectData; the
        # Aspects content page doesn't expose it (the effect lives in the prose
        # description), so it's an empty tuple here. `_boost_sentence` already
        # short-circuits on empty input, so the Spec card just relies on the
        # description for stat-effect language.
        return cls(
            key=key,
            display_name=d.get("displayName") or key,
            slot=d.get("slot"),
            description=d.get("description"),
            common=bool(d.get("common", True)),
            size_note=d.get("sizeNote"),
            boost_stats=(),
        )

    @property
    def has_image(self) -> bool:
        return self.display_name != self.key  # placeholder convention


@dataclass(frozen=True)
class AspectData:
    records: dict[str, AspectRecord]
    revid: int


# --- Aspects-page table parser ----------------------------------------------

# Color-span around an aspect name encodes rarity: green = Common, purple = Rare.
_ASPECT_NAME_RE = re.compile(
    r'<span\s+style="color:\s*(?P<color>[A-Za-z ]+?)\s*"\s*>(?P<name>[^<]+)</span>',
    re.IGNORECASE,
)
# Slot cell may include a size restriction like "Dronebay (M/L only)".
_SLOT_NOTE_RE = re.compile(r"\(([^)]+?)\s*only\)", re.IGNORECASE)


def _slugify(name: str) -> str:
    """Aspect record key — lowercase, non-alphanumerics→underscore.

    Distinct from `display_name` so `has_image` (which checks key≠name) stays
    True for every real aspect on the wiki page."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return s or name


def _parse_aspect_cell(cell: str) -> tuple[str, bool] | None:
    """Return (display_name, is_common) from the 'Aspects' column cell, or None."""
    m = _ASPECT_NAME_RE.search(cell)
    if not m:
        return None
    color = m.group("color").strip().lower()
    name = m.group("name").strip()
    return name, color == "green"


def _parse_slot_cell(cell: str) -> tuple[str | None, str | None]:
    """Return (slot_enum, size_note) from the 'Slots' column cell."""
    raw = re.sub(r"\s+", " ", cell).strip()
    if not raw:
        return None, None
    note_m = _SLOT_NOTE_RE.search(raw)
    size_note = note_m.group(1).strip() if note_m else None
    bare = _SLOT_NOTE_RE.sub("", raw).strip()
    return _TAB_SLOT.get(bare, bare), size_note


def parse_aspects(wikitext: str) -> dict[str, dict[str, Any]]:
    """Walk the Aspect List ``<tabber>`` and return ``{key: lua-shaped dict}``
    suitable for `AspectRecord.from_dict`."""
    records: dict[str, dict[str, Any]] = {}
    for tabber_m in re.finditer(r"<tabber>([\s\S]*?)</tabber>", wikitext):
        inner = tabber_m.group(1)
        tab_matches = list(re.finditer(r"(?:^|\n)\|-\|([^=\n]+)=", inner))
        for i, tm in enumerate(tab_matches):
            tab_name = tm.group(1).strip()
            slot_enum = _TAB_SLOT.get(tab_name)
            if slot_enum is None:
                continue
            tab_start = tm.end()
            tab_end = tab_matches[i + 1].start() if i + 1 < len(tab_matches) else len(inner)
            for tbl_m in re.finditer(r"\{\|[^\n]*\n[\s\S]*?\n\|\}",
                                     inner[tab_start:tab_end]):
                rows = _split_table_rows(tbl_m.group(0))
                if len(rows) < 2:
                    continue
                # Headers come back as e.g. ['', 'Aspects', 'Description', 'Slots']
                # (leading "!" cell is empty for the image column).
                headers = [h.strip() for h in rows[0]]
                try:
                    aspect_idx = headers.index("Aspects")
                    desc_idx = headers.index("Description")
                    slots_idx = headers.index("Slots")
                except ValueError:
                    continue
                for cells in rows[1:]:
                    if len(cells) <= max(aspect_idx, desc_idx, slots_idx):
                        continue
                    parsed = _parse_aspect_cell(cells[aspect_idx])
                    if not parsed:
                        continue
                    name, is_common = parsed
                    slot_value, size_note = _parse_slot_cell(cells[slots_idx])
                    # Fall back to the tab-derived slot if the cell didn't
                    # match a known enum (e.g. cell says "Dronebay" already).
                    slot_value = slot_value if slot_value in _SLOT_LABEL else slot_enum
                    records[_slugify(name)] = {
                        "displayName": name,
                        "slot": slot_value,
                        "description": cells[desc_idx].strip() or None,
                        "common": is_common,
                        "sizeNote": size_note,
                    }
    return records


def load(session) -> AspectData:
    """Fetch and parse [[Aspects]]. One network call per scraper run."""
    resp = session.get(
        _API_URL,
        params={
            "action": "parse",
            "page": "Aspects",
            "prop": "wikitext|revid",
            "format": "json",
            "formatversion": "2",
        },
        timeout=30,
    )
    resp.raise_for_status()
    parse = resp.json()["parse"]
    raw = parse_aspects(parse["wikitext"])
    records = {k: AspectRecord.from_dict(k, v) for k, v in raw.items()}
    return AspectData(records=records, revid=int(parse["revid"]))


# ---- spec card builder ----

def _strip_trailing_period(text: str) -> str:
    return text.rstrip(" .")


def _identity_sentence(r: AspectRecord) -> str:
    rarity = "common" if r.common else "rare"
    slot_text = _slot_label(r.slot)
    article = "an" if rarity[0] in "aeiou" else "a"
    if not r.description:
        return f"{r.display_name} is {article} {rarity} {slot_text}-slot aspect."
    # Lowercase the description's first letter so it splices naturally onto
    # the identity clause ("Increases X" → "...aspect: increases X.").
    desc = _strip_trailing_period(r.description)
    desc_spliced = desc[:1].lower() + desc[1:]
    return (
        f"{r.display_name} is {article} {rarity} {slot_text}-slot aspect: "
        f"{desc_spliced}."
    )


def _size_sentence(r: AspectRecord) -> str:
    if not r.size_note:
        return ""
    return f"Restricted to {r.size_note} modules."


def _boost_sentence(r: AspectRecord) -> str:
    if not r.boost_stats:
        return ""
    parts: list[str] = []
    for b in r.boost_stats:
        amt = b["amount"]
        mult = b["multiplier"]
        stat = b["stat"]
        if mult and mult != 1.0:
            pct = round((float(mult) - 1.0) * 100)
            parts.append(f"+{pct}% {stat}")
        elif amt:
            # Resists / chances are stored as 0..1 fractions; everything else
            # is a flat number. Heuristic: amount strictly between 0 and 1
            # reads better as a percent.
            if 0 < float(amt) < 1:
                parts.append(f"+{round(float(amt) * 100)}% {stat}")
            else:
                parts.append(f"+{amt:g} {stat}")
    if not parts:
        return ""
    return "Stat effects: " + ", ".join(parts) + "."


def aspect_sentences(record: AspectRecord) -> str:
    """1-3 sentence Spec card body for one aspect."""
    paragraphs: list[str] = [_identity_sentence(record)]
    size = _size_sentence(record)
    if size:
        paragraphs.append(size)
    boost = _boost_sentence(record)
    if boost:
        paragraphs.append(boost)
    return "\n\n".join(paragraphs)


def slot_roster_chunk(
    records: dict[str, AspectRecord],
) -> tuple[str, str] | None:
    """Quick alphabetical index — every aspect grouped by slot, names only.
    Useful for breadth queries ('how many aspects exist?'). Per-slot detail
    chunks (`per_slot_chunks`) carry the same grouping with descriptions."""
    by_slot: dict[str, list[str]] = {}
    for r in records.values():
        if not r.has_image:
            # Skip placeholder/internal entries that the wiki suppresses too.
            continue
        label = _slot_label(r.slot)
        by_slot.setdefault(label, []).append(r.display_name)
    if not by_slot:
        return None
    lines = ["All aspects grouped by slot:", ""]
    for slot in sorted(by_slot):
        names = sorted(by_slot[slot])
        lines.append(f"{slot} ({len(names)}): {', '.join(names)}")
    return ("Aspect roster", "\n".join(lines))


def _aspect_line(r: AspectRecord, *, include_slot: bool, include_rarity: bool) -> str:
    """One line summarizing an aspect for an aggregate chunk."""
    badges: list[str] = []
    if include_slot:
        badges.append(_slot_label(r.slot))
    if include_rarity:
        badges.append("common" if r.common else "rare")
    if r.size_note:
        badges.append(r.size_note)
    badge_text = f" ({', '.join(badges)})" if badges else ""
    desc = r.description or "no description"
    return f"{r.display_name}{badge_text}: {desc}"


def per_slot_chunks(
    records: dict[str, AspectRecord],
) -> list[tuple[str, str]]:
    """One chunk per slot label, each listing every aspect with its full
    description. Answers 'what aspects fit X slot?' on a single chunk."""
    by_slot: dict[str, list[AspectRecord]] = {}
    for r in records.values():
        if not r.has_image:
            continue
        label = _slot_label(r.slot)
        by_slot.setdefault(label, []).append(r)
    out: list[tuple[str, str]] = []
    for slot in sorted(by_slot):
        aspects = sorted(by_slot[slot], key=lambda r: r.display_name)
        lines = [
            f"Aspects available for the {slot} slot ({len(aspects)} total):",
            "",
        ]
        for r in aspects:
            lines.append(_aspect_line(r, include_slot=False, include_rarity=True))
        out.append((f"Aspects in {slot} slot", "\n".join(lines)))
    return out


def per_rarity_chunks(
    records: dict[str, AspectRecord],
) -> list[tuple[str, str]]:
    """One chunk for common aspects, one for rare. Answers 'which rare
    aspects exist?' / 'list common aspects'. Includes synonyms in the body
    so embeddings match queries phrased as 'epic' / 'purple' / 'green'."""
    common: list[AspectRecord] = []
    rare: list[AspectRecord] = []
    for r in records.values():
        if not r.has_image:
            continue
        (common if r.common else rare).append(r)

    out: list[tuple[str, str]] = []
    for label, aspects, synonyms in (
        ("Common", common,
         "Common aspects (also called green-tier or standard-rarity aspects) "
         "are the more frequently rolled tier."),
        ("Rare", rare,
         "Rare aspects (also called purple-tier, epic, or exotic aspects) "
         "are the less common, generally stronger tier."),
    ):
        if not aspects:
            continue
        aspects = sorted(aspects, key=lambda r: r.display_name)
        lines = [
            f"{label} aspects ({len(aspects)} total):",
            "",
            synonyms,
            "",
        ]
        for r in aspects:
            lines.append(_aspect_line(r, include_slot=True, include_rarity=False))
        out.append((f"{label} aspects", "\n".join(lines)))
    return out


# Effect-category detection. Each entry: (chunk title, predicate). Predicates
# inspect both `boost_stats` (structured) and `description` (free-form) so
# aspects with empty boost lists still get categorized via their prose.
def _has_stat(r: AspectRecord, *needles: str) -> bool:
    return any(any(n in b["stat"] for n in needles) for b in r.boost_stats)


def _desc_has(r: AspectRecord, *phrases: str) -> bool:
    desc = (r.description or "").lower()
    return any(p in desc for p in phrases)


_EFFECT_CATEGORIES: tuple[tuple[str, Any], ...] = (
    ("damage resistance",
     lambda r: _has_stat(r, "Resist", "DamageReduction")
               or _desc_has(r, "resistance", "reduces damage")),
    ("critical hits",
     lambda r: _has_stat(r, "Critical")
               or _desc_has(r, "critical")),
    ("drones",
     lambda r: r.slot == "Dronebay"
               or _desc_has(r, "drone")),
    ("weapon range",
     lambda r: _has_stat(r, "WeaponRange")
               or _desc_has(r, "weapon range")),
    ("reload and firing speed",
     lambda r: _has_stat(r, "AttackSpeed", "ReloadSpeed", "MagazineSize")
               or _desc_has(r, "reload", "fire rate", "attack speed", "magazine")),
    ("reactor and energy",
     lambda r: _has_stat(r, "EnergyCapacity")
               or _desc_has(r, "reactor", "energy capacity")),
    ("repair and regeneration",
     lambda r: _desc_has(r, "regenerat", "auto-repair", "repair")),
    ("extra damage type",
     lambda r: any(b["stat"].endswith("Damage") and b["stat"] != "Damage"
                   for b in r.boost_stats)
               or _desc_has(r, "additional", "deals an additional",
                            "extra damage")),
)


def per_effect_chunks(
    records: dict[str, AspectRecord],
) -> list[tuple[str, str]]:
    """One chunk per effect category, each listing matching aspects with
    descriptions. Answers 'which aspects boost crit/drones/range/...?' on a
    single chunk. An aspect can appear in multiple categories — that's
    intentional, since players ask the same question several ways."""
    out: list[tuple[str, str]] = []
    for category, predicate in _EFFECT_CATEGORIES:
        matches = [
            r for r in records.values()
            if r.has_image and predicate(r)
        ]
        if not matches:
            continue
        matches.sort(key=lambda r: r.display_name)
        lines = [
            f"Aspects that boost {category} ({len(matches)} total):",
            "",
        ]
        for r in matches:
            lines.append(_aspect_line(r, include_slot=True, include_rarity=True))
        out.append((f"Aspects boosting {category}", "\n".join(lines)))
    return out
