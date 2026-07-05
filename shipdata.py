"""Ship List page accessor for the wiki scraper.

Fetches the wiki's [[Ship List]] content page, parses the <tabber>+wikitable
structure into Python dicts, exposes a typed `ShipRecord` per ship, and builds
natural-language Spec card text.

Replaces the previous Module:ShipData Lua-source pipeline — the Lua modules
were removed from the wiki and the canonical ship data now lives in the
Ship List page's tables directly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# Hull-class plural (tab name) → singular form used by ShipRecord.ship_class
# and the existing _CLASS_ROLE map further down. Mirrors the wiki's tabber
# headers under each H2 size bucket.
_CLASS_SINGULAR = {
    "Cutters": "Cutter",
    "Gunships": "Gunship",
    "Mining Skiffs": "Mining Skiff",
    "Hewers": "Hewer",
    "Salvage Skiffs": "Salvage Skiff",
    "Scows": "Scow",
    "Couriers": "Courier",
    "Ferries": "Ferry",
    "Corvettes": "Corvette",
    "Frigates": "Frigate",
    "Dredgers": "Dredger",
    "Breakers": "Breaker",
    "Scrappers": "Scrapper",
    "Wreckers": "Wrecker",
    "Haulers": "Hauler",
    "Freighters": "Freighter",
    "Destroyers": "Destroyer",
    "Harvesters": "Harvester",
    "Reclaimers": "Reclaimer",
    "Carracks": "Carrack",
}

# Ship List "Hrdp" column codes — table cells read like "2M 3S" or "1L 2S"
# while ShipRecord/_format_hardpoints expects an expanded list ["M","M","S","S","S"].
_HARDPOINT_RE = re.compile(r"(\d+)\s*([LMST])")

# Cell pre-clean: strip [[File:...]] image markup and trailing <br>... noise
# that ride along with the ship-name cell. Manufacturer cells are bare wikilinks
# (`[[Akai Armory]]`) so a separate regex handles those.
_FILE_LINK_RE = re.compile(r"\[\[File:[^\]]+\]\]", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_PLAIN_LINK_RE = re.compile(r"\[\[([^\|\]]+?)(?:\|[^\]]+)?\]\]")


def _clean_cell(text: str) -> str:
    """Strip image markup, <br> tags, and wikilink decoration from a table cell."""
    s = _FILE_LINK_RE.sub("", text)
    s = _BR_RE.sub(" ", s)
    s = _PLAIN_LINK_RE.sub(r"\1", s)
    # squash inner whitespace, drop trailing comment-style remnants
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_number(text: str) -> Any:
    """Coerce a table cell to int/float, return None for blank/dash markers."""
    s = text.strip()
    if not s or s in {"—", "-"}:
        return None
    # "0!" — starter-ship marker on PlyrL — strip the trailing bang.
    if s.endswith("!"):
        s = s[:-1].strip()
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return None


def _parse_hardpoints(text: str) -> list[str] | None:
    """'2M 3S' → ['M','M','S','S','S']. Blank → None."""
    s = text.strip()
    if not s or s in {"—", "-"}:
        return None
    out: list[str] = []
    for n, code in _HARDPOINT_RE.findall(s):
        out.extend([code] * int(n))
    return out or None


# Column header (as it appears in the table's `!` row) → field name handed to
# ShipRecord.from_dict. Anything not in this map is ignored.
_COL_FIELD_PARSER: dict[str, tuple[str, Any]] = {
    "Ships":        ("displayName",     lambda c: _clean_cell(c)),
    "Manufacturer": ("manufacturer",    lambda c: _clean_cell(c) or None),
    "Crew":         ("crew",            lambda c: _parse_number(c)),
    "Hull":         ("hullScale",       lambda c: _parse_number(c)),
    "Armr":         ("armorScale",      lambda c: _parse_number(c)),
    "Shld":         ("shieldScale",     lambda c: _parse_number(c)),
    "Crgo":         ("cargo",           lambda c: _parse_number(c)),
    "Spd":          ("speed",           lambda c: _parse_number(c)),
    "Acc":          ("accel",           lambda c: _parse_number(c)),
    "Hrdp":         ("hardpoints",      lambda c: _parse_hardpoints(c)),
    "ShpR":         ("shipyardRep",     lambda c: (_clean_cell(c) or None)
                                                  if _clean_cell(c) not in {"", "—", "-"} else None),
    "Cnq":          ("conquestRank",    lambda c: (_clean_cell(c) or None)
                                                  if _clean_cell(c) not in {"", "—", "-"} else None),
    "PlyrL":        ("playerLevel",     lambda c: _parse_number(c)),
    "ShpL":         ("shipyardLevel",   lambda c: (_clean_cell(c) or None)
                                                  if _clean_cell(c) not in {"", "—", "-"} else None),
}


def split_table_rows(table_wt: str) -> list[list[str]]:
    """Parse one ``{| ... |}`` wikitable into a row-of-cells list.

    Handles both compact rows (``| a || b || c``) and one-cell-per-line rows
    (``| a\\n| b\\n| c``); strips leading ``+`` caption rows."""
    # Normalise ``|- style="..."`` to a bare ``|-`` so the row-split
    # pattern below doesn't miss rows with inline CSS attributes.
    table_wt = re.sub(r"\n\s*\|-[ \t]+[^|\n]*\n", "\n|-\n", table_wt)
    m = re.search(r"\{\|[^\n]*\n([\s\S]*?)\n\|\}", table_wt)
    if not m:
        return []
    body = m.group(1)
    # Drop caption lines ("|+ caption") and class/style attribute lines.
    body = re.sub(r"^\|\+[^\n]*\n?", "", body, flags=re.MULTILINE)
    # Some tables open with a leading `|-` before the header row; others put the
    # header on the line right after `{|`. Strip a leading separator so both
    # shapes split into the same row sequence.
    body = re.sub(r"^\|-\s*\n", "", body)

    # Strip File: and Image: link markup before cell-splitting — their internal
    # `|` (e.g. `[[File:Raptor.png|thumb|center]]`) would otherwise be mistaken
    # for a column separator and shift every subsequent cell.
    body = re.sub(r"\[\[(?:File|Image):[^\]]+\]\]", "", body, flags=re.IGNORECASE)

    raw_rows = re.split(r"\n\s*\|-\s*\n", body)
    rows: list[list[str]] = []
    for raw in raw_rows:
        raw = raw.strip()
        if not raw:
            continue
        is_header = raw.startswith("!")
        text = raw.lstrip("!|").strip() if is_header else raw.lstrip("|").strip()
        # `[ \t]*` after the pipe — not `\s*` — so a blank cell on its own line
        # (`| \n|`) stays as an empty cell instead of being swallowed by the
        # separator. The cell-split anchor is the literal newline-pipe pair.
        sep = r"[ \t]*!![ \t]*|\n![ \t]*" if is_header else r"[ \t]*\|\|[ \t]*|\n\|[ \t]*"
        cells = [c.strip() for c in re.split(sep, text)]
        rows.append(cells)
    return rows


def parse_ship_list(wikitext: str) -> dict[str, dict[str, Any]]:
    """Return ``{key: lua-shaped dict}`` for ``ShipRecord.from_dict``.

    Walks every ``<tabber>...</tabber>`` block on the Ship List page. Each
    ``|-|TabName=`` tab contributes one hull class. Same display-name across
    multiple manufacturers gets disambiguated as ``"Name (Manufacturer)"``."""
    records: dict[str, dict[str, Any]] = {}
    # First pass: collect all rows with their class+manufacturer so we can
    # disambiguate keys for same-name multi-manufacturer ships at the end.
    pending: list[tuple[str, dict[str, Any]]] = []

    for tabber_m in re.finditer(r"<tabber>([\s\S]*?)</tabber>", wikitext):
        inner = tabber_m.group(1)
        # `|-|TabName=tab body` repeated; the first tab has no leading "|-|".
        tab_matches = list(re.finditer(r"(?:^|\n)\|-\|([^=\n]+)=", inner))
        if not tab_matches:
            continue
        # Splice in an implicit start marker at 0 for the first tab — its name
        # is on the first "|-|" so the inner content before that first marker
        # is the tabber preamble (we don't need it).
        for i, tm in enumerate(tab_matches):
            tab_name = tm.group(1).strip()
            tab_start = tm.end()
            tab_end = tab_matches[i + 1].start() if i + 1 < len(tab_matches) else len(inner)
            tab_body = inner[tab_start:tab_end]
            ship_class = _CLASS_SINGULAR.get(tab_name)
            if ship_class is None:
                continue  # unknown tab — skip rather than guess
            for tbl_m in re.finditer(r"\{\|[^\n]*\n[\s\S]*?\n\|\}", tab_body):
                rows = split_table_rows(tbl_m.group(0))
                if len(rows) < 2:
                    continue
                headers = rows[0]
                for cells in rows[1:]:
                    if not any(cells):
                        continue
                    fields: dict[str, Any] = {"class": ship_class + "s"}
                    for col, cell in zip(headers, cells):
                        col = col.strip()
                        if col not in _COL_FIELD_PARSER:
                            continue
                        field, parser = _COL_FIELD_PARSER[col]
                        fields[field] = parser(cell)
                    name = fields.get("displayName")
                    if not name:
                        continue
                    mfr = fields.get("manufacturer")
                    if mfr:
                        fields["shipyardFactions"] = [mfr]
                    pending.append((name, fields))

    # Disambiguate keys: when multiple manufacturers sell the same ship, keep
    # the first entry as the bare-name canonical and suffix " (Manufacturer)"
    # only on subsequent entries. This guarantees ``_variant_sentence`` can
    # always find a bare-name key to link back to.
    seen_names: set[str] = set()
    for name, fields in pending:
        if name in seen_names and fields.get("manufacturer"):
            key = f"{name} ({fields['manufacturer']})"
        else:
            key = name
            seen_names.add(name)
        records[key] = fields
    return records


@dataclass(frozen=True)
class ShipRecord:
    key: str
    display_name: str
    manufacturer: str | None = None
    ship_class: str | None = None
    hull_scale: float | None = None
    shield_scale: float | None = None
    armor_scale: float | None = None
    hardpoints: list[str] | None = None
    speed: float | None = None
    accel: float | None = None
    crew: int | None = None
    cargo: int | None = None
    player_level: int | None = None
    shipyard_level: str | None = None
    shipyard_rep: str | None = None
    shipyard_factions: list[str] | None = None
    conquest_rank: str | None = None
    not_for_sale: bool = False

    @classmethod
    def from_dict(cls, key: str, d: dict[str, Any]) -> "ShipRecord":
        # Module:ShipData migrated from `shipyardFaction` (single string) to
        # `shipyardFactions` (Lua list) so that hulls sold at multiple
        # vendors can list every shipyard. Tolerate the legacy spelling for
        # any caller that still hands us pre-migration data.
        factions = d.get("shipyardFactions")
        if factions is None and d.get("shipyardFaction") is not None:
            factions = [d["shipyardFaction"]]
        return cls(
            key=key,
            display_name=d.get("displayName", key),
            manufacturer=d.get("manufacturer"),
            ship_class=d.get("class"),
            hull_scale=d.get("hullScale"),
            shield_scale=d.get("shieldScale"),
            armor_scale=d.get("armorScale"),
            hardpoints=d.get("hardpoints"),
            speed=d.get("speed"),
            accel=d.get("accel"),
            crew=d.get("crew"),
            cargo=d.get("cargo"),
            player_level=d.get("playerLevel"),
            shipyard_level=(
                str(d["shipyardLevel"]) if "shipyardLevel" in d else None
            ),
            shipyard_rep=d.get("shipyardRep"),
            shipyard_factions=factions,
            conquest_rank=d.get("conquestRank"),
            not_for_sale=bool(d.get("notForSale", False)),
        )


@dataclass(frozen=True)
class ShipData:
    records: dict[str, ShipRecord]
    revid: int


_API_URL = "https://vanguard-galaxy.fandom.com/api.php"


def load(session) -> ShipData:
    """Fetch and parse [[Ship List]]. One network call per scraper run."""
    resp = session.get(
        _API_URL,
        params={
            "action": "parse",
            "page": "Ship List",
            "prop": "wikitext|revid",
            "format": "json",
            "formatversion": "2",
        },
        timeout=30,
    )
    resp.raise_for_status()
    parse = resp.json()["parse"]
    raw = parse_ship_list(parse["wikitext"])
    records = {k: ShipRecord.from_dict(k, v) for k, v in raw.items()}
    return ShipData(records=records, revid=int(parse["revid"]))


def _format_hardpoints(hp: list[str]) -> str:
    sizes = {"L": "large", "M": "medium", "S": "small", "T": "tiny"}
    counts: dict[str, int] = {}
    for h in hp:
        counts[h] = counts.get(h, 0) + 1
    parts: list[str] = []
    for code in ("L", "M", "S", "T"):
        n = counts.get(code, 0)
        if n:
            parts.append(f"{n} {sizes[code]}")
    return ", ".join(parts) if parts else "no"


# Map class (singular form, after de-pluralization) -> high-level role for the
# identity sentence's "a combat/mining/salvage/cargo hull" closer.
_CLASS_ROLE = {
    "Cutter": "combat",
    "Gunship": "combat",
    "Corvette": "combat",
    "Frigate": "combat",
    "Destroyer": "combat",
    "Mining Skiff": "mining",
    "Hewer": "mining",
    "Dredger": "mining",
    "Breaker": "mining",
    "Harvester": "mining",
    "Salvage Skiff": "salvage",
    "Scow": "salvage",
    "Scrapper": "salvage",
    "Wrecker": "salvage",
    "Reclaimer": "salvage",
    "Courier": "cargo",
    "Ferry": "cargo",
    "Hauler": "cargo",
    "Freighter": "cargo",
    "Carrack": "cargo",
}


def _singularize_class(cls: str) -> str:
    """Module:ShipData stores class as plurals ('Cutters', 'Destroyers').
    The wiki convention is build_shipdata.py's CLASS_PLURAL map; reversing it
    here lets the identity sentence read naturally."""
    if cls in _CLASS_ROLE:
        return cls
    if cls.endswith("ies"):  # Ferries -> Ferry
        return cls[:-3] + "y"
    if cls.endswith("s") and not cls.endswith("ss"):
        return cls[:-1]
    return cls


def _identity_sentence(r: ShipRecord) -> str:
    raw = r.ship_class or "ship"
    singular = _singularize_class(raw)
    cls_text = singular.lower()
    mfr = r.manufacturer or "unknown-manufacturer"
    role = _CLASS_ROLE.get(singular)
    if role:
        return f"The {r.key} is a {mfr} {cls_text}, a {role} hull."
    return f"The {r.key} is a {mfr} {cls_text}."


def _combat_sentence(r: ShipRecord) -> str:
    parts: list[str] = []
    mods = []
    if r.hull_scale is not None:
        mods.append(f"hull modifier is {r.hull_scale:g}×")
    if r.shield_scale is not None:
        mods.append(f"shield {r.shield_scale:g}×")
    if r.armor_scale is not None:
        mods.append(f"armor {r.armor_scale:g}×")
    if mods:
        parts.append("Its " + ", ".join(mods) + ".")
    if r.hardpoints:
        parts.append(f"It carries {_format_hardpoints(r.hardpoints)} hardpoints.")
    misc: list[str] = []
    if r.speed is not None:
        spd = f"warps at {r.speed:g} ls/s"
        if r.accel is not None:
            spd += f" with {r.accel:g} ls/s² acceleration"
        misc.append(spd)
    if r.crew is not None:
        slots = "slot" if r.crew == 1 else "slots"
        misc.append(f"has {r.crew} crew {slots}")
    if r.cargo is not None:
        units = "unit" if r.cargo == 1 else "units"
        misc.append(f"carries {r.cargo} cargo {units}")
    if misc:
        parts.append("It " + ", ".join(misc) + ".")
    return " ".join(parts)


def _format_faction_list(factions: list[str]) -> str:
    if len(factions) == 1:
        return factions[0]
    if len(factions) == 2:
        return f"{factions[0]} and {factions[1]}"
    return ", ".join(factions[:-1]) + f", and {factions[-1]}"


def _acquisition_sentence(r: ShipRecord) -> str:
    if r.not_for_sale:
        return (
            f"The {r.key} is awarded as a story reward and is "
            "not sold at any shipyard."
        )
    factions = r.shipyard_factions or []
    if not factions:
        return ""
    bits = [f"It sells at {_format_faction_list(factions)} shipyards"]
    if r.shipyard_level is not None:
        bits.append(f"from shipyard level {r.shipyard_level}")
    if r.shipyard_rep is not None:
        bits.append(f"at {r.shipyard_rep} reputation")
    if r.player_level is not None:
        bits.append(f"requiring player level {r.player_level}")
    if r.conquest_rank is not None:
        bits.append(f"and {r.conquest_rank} conquest rank")
    return ", ".join(bits) + "."


def _variant_sentence(
    r: ShipRecord, all_records: dict[str, ShipRecord]
) -> str:
    if r.key == r.display_name:
        return ""
    canonical = next(
        (
            other for other in all_records.values()
            if other.key == r.display_name
            and other.key != r.key
        ),
        None,
    )
    if canonical is None:
        return ""
    mfr = r.manufacturer or "an alternate vendor"
    return (
        f"The {r.key} is the {mfr}-resold variant of the {canonical.key}."
    )


def spec_sentences(
    record: ShipRecord, all_records: dict[str, ShipRecord]
) -> str:
    """Build a 1-3 paragraph natural-language Spec card body."""
    paragraphs: list[str] = []
    paragraphs.append(_identity_sentence(record))
    combat = _combat_sentence(record)
    if combat:
        paragraphs.append(combat)
    acquisition = _acquisition_sentence(record)
    if acquisition:
        paragraphs.append(acquisition)
    variant = _variant_sentence(record, all_records)
    if variant:
        paragraphs.append(variant)
    return "\n\n".join(paragraphs)


# Per-stat ranking aggregates. RAG retrieves top-N chunks by similarity, so
# "biggest cargo ship?" against 120 individual Spec cards rarely surfaces the
# actual leader. A pre-aggregated ranking chunk per stat fixes that — the
# query embeds against "ranked by cargo capacity" once and the LLM gets the
# whole leaderboard in one shot.
_RANKING_DESCRIPTORS: tuple[tuple[str, str, str], ...] = (
    ("Cargo capacity", "cargo", "cargo units"),
    ("Hull modifier", "hull_scale", "× hull"),
    ("Shield modifier", "shield_scale", "× shield"),
    ("Armor modifier", "armor_scale", "× armor"),
    ("Warp speed", "speed", "ls/s"),
    ("Warp acceleration", "accel", "ls/s²"),
    ("Crew capacity", "crew", "crew slots"),
)
_RANKING_TOP_N = 30


def _format_stat_value(v: Any) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def ranking_chunks(
    records: dict[str, ShipRecord],
) -> list[tuple[str, str]]:
    """Build per-stat top-N ranking chunks suitable for RAG retrieval.

    Returns a list of (name, body) tuples ready to be appended to scrape's
    `new_rows`. Names follow `Ship rankings – <stat>`; bodies are numbered
    leaderboards with ship name, value, and a parenthetical class+manufacturer
    line for context."""
    out: list[tuple[str, str]] = []
    for stat_name, attr, unit in _RANKING_DESCRIPTORS:
        ranked = sorted(
            (
                (r, getattr(r, attr))
                for r in records.values()
                if getattr(r, attr) is not None
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if not ranked:
            continue
        top = ranked[:_RANKING_TOP_N]
        unit_sep = "" if unit.startswith("×") else " "
        lines = [f"Ships ranked by {stat_name.lower()} (highest first):", ""]
        for i, (r, v) in enumerate(top, 1):
            cls = _singularize_class(r.ship_class or "ship").lower()
            mfr = r.manufacturer or "unknown"
            value_str = _format_stat_value(v)
            lines.append(
                f"{i}. {r.key} — {value_str}{unit_sep}{unit} "
                f"({mfr} {cls})"
            )
        if len(ranked) > _RANKING_TOP_N:
            lines.append(f"")
            lines.append(f"... and {len(ranked) - _RANKING_TOP_N} more.")
        out.append((f"Ship rankings – {stat_name}", "\n".join(lines)))
    return out


def class_roster_chunk(
    records: dict[str, ShipRecord],
) -> tuple[str, str] | None:
    """Build a single chunk listing every ship grouped by class.

    Lets queries like 'all destroyers' / 'list every harvester' hit one chunk
    instead of fishing per-ship Spec cards out of similarity scores."""
    by_class: dict[str, list[str]] = {}
    for r in records.values():
        cls = r.ship_class or "Unclassified"
        by_class.setdefault(cls, []).append(r.key)
    if not by_class:
        return None
    lines = ["All ships grouped by class:", ""]
    for cls in sorted(by_class):
        ships = sorted(by_class[cls])
        lines.append(f"{cls} ({len(ships)}): {', '.join(ships)}")
    return ("Ship roster", "\n".join(lines))
