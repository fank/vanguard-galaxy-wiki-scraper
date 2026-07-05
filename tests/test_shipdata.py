"""Tests for shipdata.py — both the Ship List page parser and the downstream
Spec / ranking / roster generators. Generators are exercised against dict-built
ShipRecord objects so they don't depend on the live wiki snapshot."""
from __future__ import annotations

import pytest

from shipdata import (
    ShipData,
    ShipRecord,
    class_roster_chunk,
    load,
    parse_ship_list,
    ranking_chunks,
    spec_sentences,
)


# ---- parser tests against a saved Ship List wikitext fixture ---------------

def test_parse_ship_list_extracts_records(ship_list_wikitext):
    raw = parse_ship_list(ship_list_wikitext)
    # Every Spec record must have a class and at least one numeric stat.
    populated = [v for v in raw.values()
                 if v.get("class") and any(v.get(k) is not None
                                           for k in ("cargo", "speed", "hullScale"))]
    assert len(populated) == len(raw) > 100  # ~120 ships at fixture time


def test_parse_ship_list_disambiguates_same_name_under_multiple_manufacturers(
    ship_list_wikitext,
):
    raw = parse_ship_list(ship_list_wikitext)
    # Cudal sells at both Frontier and Marade Wharf — the parser keys them
    # with " (Manufacturer)" so the variant sentence has something to link.
    assert "Cudal (Frontier)" in raw
    assert "Cudal (Marade Wharf)" in raw
    assert raw["Cudal (Frontier)"]["manufacturer"] == "Frontier"
    assert raw["Cudal (Marade Wharf)"]["manufacturer"] == "Marade Wharf"


def test_parse_ship_list_assigns_tabber_class(ship_list_wikitext):
    raw = parse_ship_list(ship_list_wikitext)
    # Raptor appears under the Cutters tab → ship_class should be plural form
    # (ShipRecord._singularize_class handles the natural-language conversion).
    assert raw["Raptor"]["class"] == "Cutters"


def test_parse_ship_list_parses_decimal_stats(ship_list_wikitext):
    raw = parse_ship_list(ship_list_wikitext)
    raptor = raw["Raptor"]
    # Raptor row: Hull=1.9, Shld=0.25, Crgo=60 from the fixture.
    assert raptor["hullScale"] == 1.9
    assert raptor["shieldScale"] == 0.25
    assert raptor["cargo"] == 60


def test_parse_ship_list_parses_hardpoint_codes(ship_list_wikitext):
    raw = parse_ship_list(ship_list_wikitext)
    # "1S" → ["S"]; if a row had "2M 3S" it would expand to ["M","M","S","S","S"].
    assert raw["Raptor"]["hardpoints"] == ["S"]


def test_parse_ship_list_drops_dash_for_optional_fields(ship_list_wikitext):
    raw = parse_ship_list(ship_list_wikitext)
    # Most ships have no conquest rank requirement — represented by "—" in
    # the table, must come back as None.
    none_cnq = [k for k, v in raw.items() if v.get("conquestRank") is None]
    assert none_cnq  # at least one such record exists


# ---- ShipRecord construction from dict (no Lua, no wikitext) ---------------

def _cudal_dict():
    return {
        "class": "Cutters",
        "displayName": "Cudal",
        "manufacturer": "Frontier",
        "crew": 1,
        "hullScale": 2.1,
        "shieldScale": 2.9,
        "armorScale": 1.8,
        "hardpoints": ["S", "S"],
        "speed": 5800,
        "accel": 17,
        "cargo": 80,
        "playerLevel": 1,
        "shipyardLevel": "1+",
        "shipyardRep": "Neutral",
        "shipyardFactions": ["Frontier"],
    }


def _eclipse_dict():
    return {
        "class": "Destroyers",
        "displayName": "Eclipse",
        "manufacturer": "Kharon Forgeworks",
        "crew": 5,
        "hullScale": 4.0,
        "hardpoints": ["L", "M", "M", "M"],
        "cargo": 1060,
        "notForSale": True,
    }


def test_shiprecord_falls_back_to_legacy_singular_field():
    # The dataclass still tolerates the pre-migration `shipyardFaction` key
    # so any cached/serialized state from the old pipeline still loads.
    record = ShipRecord.from_dict("Legacy", {"shipyardFaction": "Frontier"})
    assert record.shipyard_factions == ["Frontier"]


def test_shiprecord_exposes_named_fields():
    cudal = ShipRecord.from_dict("Cudal", _cudal_dict())
    assert cudal.ship_class == "Cutters"
    assert cudal.manufacturer == "Frontier"
    assert cudal.hardpoints == ["S", "S"]
    assert cudal.not_for_sale is False


def test_shiprecord_handles_missing_optional_fields():
    eclipse = ShipRecord.from_dict("Eclipse", _eclipse_dict())
    assert eclipse.shipyard_factions is None
    assert eclipse.shipyard_level is None
    assert eclipse.not_for_sale is True


# ---- spec_sentences against dict-built records -----------------------------

def _records():
    return {
        "Cudal": ShipRecord.from_dict("Cudal", _cudal_dict()),
        "Cudal-Marade": ShipRecord.from_dict("Cudal-Marade", {
            **_cudal_dict(),
            "manufacturer": "Marade Wharf",
            "displayName": "Cudal",  # canonical name → variant sentence fires
            "shipyardFactions": ["Marauders", "Corsair Syndicate"],
            "conquestRank": "Cutthroat",
        }),
        "Eclipse": ShipRecord.from_dict("Eclipse", _eclipse_dict()),
    }


def test_spec_identity_sentence():
    records = _records()
    assert "The Cudal is a Frontier cutter, a combat hull." in \
        spec_sentences(records["Cudal"], records)


def test_spec_combat_profile_includes_modifiers():
    text = spec_sentences(_records()["Cudal"], _records())
    assert "hull modifier is 2.1×" in text
    assert "shield 2.9×" in text
    assert "armor 1.8×" in text


def test_spec_combat_profile_includes_hardpoints():
    text = spec_sentences(_records()["Eclipse"], _records())
    assert "1 large, 3 medium" in text


def test_spec_shipyard_sentence():
    text = spec_sentences(_records()["Cudal"], _records())
    assert "It sells at Frontier shipyards" in text
    assert "shipyard level 1+" in text
    assert "Neutral reputation" in text
    assert "player level 1" in text


def test_spec_conquest_sentence():
    text = spec_sentences(_records()["Cudal-Marade"], _records())
    assert "Cutthroat conquest rank" in text


def test_spec_joins_multiple_factions():
    text = spec_sentences(_records()["Cudal-Marade"], _records())
    assert "It sells at Marauders and Corsair Syndicate shipyards" in text


def test_spec_not_for_sale_sentence():
    text = spec_sentences(_records()["Eclipse"], _records())
    assert "awarded as a story reward" in text
    assert "not sold at any shipyard" in text


def test_spec_variant_sentence_links_canonical():
    text = spec_sentences(_records()["Cudal-Marade"], _records())
    assert "Cudal-Marade is the Marade Wharf-resold variant of the Cudal" in text


def test_spec_canonical_ship_has_no_variant_sentence():
    text = spec_sentences(_records()["Cudal"], _records())
    assert "variant" not in text.lower()


def test_spec_singularizes_plural_class():
    text = spec_sentences(_records()["Cudal"], _records())
    assert " cutters" not in text.lower()
    assert "cutter" in text


# ---- ranking / roster ------------------------------------------------------

def test_ranking_chunks_returns_one_per_stat():
    chunks = dict(ranking_chunks(_records()))
    for stat in ("Cargo capacity", "Hull modifier", "Shield modifier",
                 "Armor modifier", "Warp speed", "Warp acceleration",
                 "Crew capacity"):
        assert f"Ship rankings – {stat}" in chunks


def test_ranking_chunks_sorted_descending():
    body = dict(ranking_chunks(_records()))["Ship rankings – Cargo capacity"]
    # Eclipse=1060 > Cudal=80 — Eclipse must come first.
    assert body.index("Eclipse") < body.index("Cudal")


def test_ranking_chunks_excludes_none_values():
    for name, body in ranking_chunks(_records()):
        assert "None" not in body, f"{name} contains a None value"


def test_ranking_chunk_includes_class_and_manufacturer():
    body = dict(ranking_chunks(_records()))["Ship rankings – Cargo capacity"]
    assert "(Kharon Forgeworks destroyer)" in body  # Eclipse
    assert "(Frontier cutter)" in body              # Cudal


def test_class_roster_groups_ships_by_class():
    name, body = class_roster_chunk(_records())
    assert name == "Ship roster"
    assert "Cutters (2): Cudal, Cudal-Marade" in body
    assert "Destroyers (1): Eclipse" in body


def test_load_returns_shipdata_with_revid(ship_list_wikitext):
    """Smoke-test load() against a mocked session that returns the saved
    Ship List wikitext fixture."""
    class _Resp:
        def __init__(self, p): self._p = p
        def raise_for_status(self): pass
        def json(self): return self._p

    class _Sess:
        def get(self, url, params=None, timeout=None):
            return _Resp({"parse": {"wikitext": ship_list_wikitext, "revid": 4242}})

    data = load(_Sess())
    assert isinstance(data, ShipData)
    assert data.revid == 4242
    assert len(data.records) > 100
