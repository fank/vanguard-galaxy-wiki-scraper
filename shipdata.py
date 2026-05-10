"""Module:ShipData accessor for the wiki scraper.

Fetches the wiki's Lua data module, parses it into Python dicts, exposes a
typed `ShipRecord` per ship, and builds natural-language Spec card text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# The wiki's Module:ShipData uses a stable emit format from
# `dataexport/tools/merge_shipdata.py`:
#   ["<Key>"] = { name = value, ... },
# so a regex parser over that exact shape is sufficient and avoids pulling in
# a full Lua interpreter.
_ENTRY_RE = re.compile(r'\[\s*"([^"]+)"\s*\]\s*=\s*\{', re.S)
_FIELD_RE = re.compile(
    r'^(\s*)(\w+)\s*=\s*(.*?),\s*(?:--[^\n]*)?$',
    re.M,
)


def _coerce(value_text: str) -> Any:
    v = value_text.strip()
    if v == "nil":
        return None
    if v == "true":
        return True
    if v == "false":
        return False
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    if v.startswith("{") and v.endswith("}"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        # Hardpoints / similar are arrays of strings; sizeSummary is k=v but
        # the scraper doesn't surface it in the spec card so leave it as-is.
        items = [s.strip() for s in inner.split(",") if s.strip()]
        out = []
        for item in items:
            if "=" in item:
                # k=v table — return the original text; spec_sentences ignores it.
                return v
            out.append(_coerce(item))
        return out
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v  # fallback: keep raw text


def parse_lua(text: str) -> dict[str, dict[str, Any]]:
    """Parse a Module:ShipData Lua source into {key: {field: value}}."""
    records: dict[str, dict[str, Any]] = {}
    for m in _ENTRY_RE.finditer(text):
        key = m.group(1)
        depth = 1
        i = m.end()
        while i < len(text) and depth > 0:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        body = text[m.end():i - 1]
        fields: dict[str, Any] = {}
        for fm in _FIELD_RE.finditer(body):
            fields[fm.group(2)] = _coerce(fm.group(3))
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
    shipyard_faction: str | None = None
    conquest_rank: str | None = None
    not_for_sale: bool = False

    @classmethod
    def from_dict(cls, key: str, d: dict[str, Any]) -> "ShipRecord":
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
            shipyard_faction=d.get("shipyardFaction"),
            conquest_rank=d.get("conquestRank"),
            not_for_sale=bool(d.get("notForSale", False)),
        )


@dataclass(frozen=True)
class ShipData:
    records: dict[str, ShipRecord]
    revid: int


_API_URL = "https://vanguard-galaxy.fandom.com/api.php"


def load(session) -> ShipData:
    """Fetch and parse Module:ShipData. One network call per scraper run."""
    resp = session.get(
        _API_URL,
        params={
            "action": "parse",
            "page": "Module:ShipData",
            "prop": "wikitext|revid",
            "format": "json",
            "formatversion": "2",
        },
        timeout=30,
    )
    resp.raise_for_status()
    parse = resp.json()["parse"]
    raw = parse_lua(parse["wikitext"])
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


def _acquisition_sentence(r: ShipRecord) -> str:
    if r.not_for_sale:
        return (
            f"The {r.key} is awarded as a story reward and is "
            "not sold at any shipyard."
        )
    if r.shipyard_faction is None:
        return ""
    bits = [f"It sells at {r.shipyard_faction} shipyards"]
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
