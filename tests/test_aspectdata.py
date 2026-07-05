"""Tests for aspectdata.py — Aspects page parser plus the downstream Spec /
roster / per-slot / per-rarity / per-effect generators."""
from __future__ import annotations

import pytest

from aspectdata import (
    AspectData,
    AspectRecord,
    aspect_sentences,
    load,
    parse_aspects,
    per_effect_chunks,
    per_rarity_chunks,
    per_slot_chunks,
    slot_roster_chunk,
)


# ---- parser tests against a saved Aspects wikitext fixture -----------------

def test_parse_aspects_extracts_all_table_rows(aspects_wikitext):
    raw = parse_aspects(aspects_wikitext)
    # 20 aspects across 7 slot tabs at fixture time.
    assert 18 <= len(raw) <= 30
    for key, fields in raw.items():
        assert fields["displayName"]
        assert fields["slot"] in {
            "Weapons", "Dronebay", "Scanner", "Hull", "Armor",
            "AllModules", "AllItems",
        }


def test_parse_aspects_distinguishes_rarity_via_color_span(aspects_wikitext):
    raw = parse_aspects(aspects_wikitext)
    # green-coloured names → common; purple → rare.
    assert raw["critical_attenuation"]["common"] is True
    assert raw["firestarter"]["common"] is False


def test_parse_aspects_captures_size_note_from_slot_cell(aspects_wikitext):
    raw = parse_aspects(aspects_wikitext)
    # "Dronebay (M/L only)" → slot=Dronebay, sizeNote="M/L".
    over = raw["oversized_drone_bay"]
    assert over["slot"] == "Dronebay"
    assert over["sizeNote"] == "M/L"


def test_parse_aspects_carries_description(aspects_wikitext):
    raw = parse_aspects(aspects_wikitext)
    assert "critical strike damage" in raw["critical_attenuation"]["description"]


# ---- AspectRecord construction --------------------------------------------

def _crit_dict():
    return {
        "displayName": "Critical Attenuation",
        "slot": "Weapons",
        "description": "Increases critical strike damage of this weapon by 25%",
        "common": True,
        "sizeNote": None,
    }


def _over_dict():
    return {
        "displayName": "Oversized Drone Bay",
        "slot": "Dronebay",
        "description": "Increases maximum drones by 2",
        "common": False,
        "sizeNote": "M/L",
    }


def _gamma_dict():
    return {
        "displayName": "Gamma Ward",
        "slot": "AllItems",
        "description": "Increases Energy and Radiation damage resistance by 5%",
        "common": True,
        "sizeNote": None,
    }


def _microgen_dict():
    return {
        "displayName": "Microgenerators",
        "slot": "AllModules",
        "description": "Increases reactor energy by 10%",
        "common": True,
        "sizeNote": None,
    }


def _records():
    return {
        "critical_attenuation": AspectRecord.from_dict("critical_attenuation", _crit_dict()),
        "oversized_drone_bay": AspectRecord.from_dict("oversized_drone_bay", _over_dict()),
        "gamma_ward":         AspectRecord.from_dict("gamma_ward",         _gamma_dict()),
        "microgenerators":    AspectRecord.from_dict("microgenerators",    _microgen_dict()),
    }


def test_aspectrecord_exposes_named_fields():
    crit = AspectRecord.from_dict("critical_attenuation", _crit_dict())
    assert crit.display_name == "Critical Attenuation"
    assert crit.slot == "Weapons"
    assert crit.common is True
    assert crit.size_note is None


def test_aspectrecord_has_image_true_when_key_differs_from_display_name():
    # The new parser slugifies the display_name into the key; every real
    # aspect on the page therefore has key ≠ display_name, which is what
    # has_image checks. (Placeholder filtering is no longer needed.)
    crit = AspectRecord.from_dict("critical_attenuation", _crit_dict())
    assert crit.has_image is True


# ---- aspect_sentences ------------------------------------------------------

def test_aspect_sentences_identity_includes_slot_and_rarity():
    text = aspect_sentences(_records()["critical_attenuation"])
    assert "Critical Attenuation is a common Weapons-slot aspect" in text
    assert "increases critical strike damage" in text


def test_aspect_sentences_marks_rare_aspects():
    text = aspect_sentences(_records()["oversized_drone_bay"])
    assert "Oversized Drone Bay is a rare Dronebay-slot aspect" in text


def test_aspect_sentences_includes_size_note():
    text = aspect_sentences(_records()["oversized_drone_bay"])
    assert "Restricted to M/L modules." in text


def test_aspect_sentences_uses_renamed_slot_label():
    text = aspect_sentences(_records()["gamma_ward"])
    # AllItems renders with a space.
    assert "All Items-slot aspect" in text


# ---- slot roster -----------------------------------------------------------

def test_slot_roster_groups_by_label():
    name, body = slot_roster_chunk(_records())
    assert name == "Aspect roster"
    assert "Weapons (1): Critical Attenuation" in body
    assert "Dronebay (1): Oversized Drone Bay" in body
    assert "All Items (1): Gamma Ward" in body
    assert "All Modules (1): Microgenerators" in body


# ---- per_slot / per_rarity / per_effect ------------------------------------

def test_per_slot_chunks_one_per_slot():
    chunks = dict(per_slot_chunks(_records()))
    for slot in ("Weapons", "Dronebay", "All Items", "All Modules"):
        assert f"Aspects in {slot} slot" in chunks


def test_per_slot_chunk_lists_aspects_with_descriptions():
    body = dict(per_slot_chunks(_records()))["Aspects in Weapons slot"]
    assert "Critical Attenuation (common)" in body
    assert "Increases critical strike damage of this weapon by 25%" in body


def test_per_rarity_chunks_split_common_and_rare():
    chunks = dict(per_rarity_chunks(_records()))
    common_body = chunks["Common aspects"]
    rare_body = chunks["Rare aspects"]
    assert "Critical Attenuation" in common_body
    assert "Critical Attenuation" not in rare_body
    assert "Oversized Drone Bay" in rare_body
    assert "Oversized Drone Bay" not in common_body


def test_per_rarity_chunks_include_synonym_phrasing():
    chunks = dict(per_rarity_chunks(_records()))
    assert "purple" in chunks["Rare aspects"].lower()
    assert "epic" in chunks["Rare aspects"].lower()
    assert "green" in chunks["Common aspects"].lower()


def test_per_effect_chunks_categorize_via_description():
    chunks = dict(per_effect_chunks(_records()))
    # Critical Attenuation's description mentions "critical" — categorisation
    # falls back to description matching now that boost_stats is empty.
    assert "Aspects boosting critical hits" in chunks
    assert "Critical Attenuation" in chunks["Aspects boosting critical hits"]


def test_per_effect_chunks_resistance_via_description():
    chunks = dict(per_effect_chunks(_records()))
    assert "Aspects boosting damage resistance" in chunks
    assert "Gamma Ward" in chunks["Aspects boosting damage resistance"]


def test_per_effect_chunk_lists_drones_aspects():
    chunks = dict(per_effect_chunks(_records()))
    assert "Aspects boosting drones" in chunks
    assert "Oversized Drone Bay" in chunks["Aspects boosting drones"]


# ---- load() smoke ---------------------------------------------------------

def test_load_returns_aspectdata_with_revid(aspects_wikitext):
    class _Resp:
        def __init__(self, p): self._p = p
        def raise_for_status(self): pass
        def json(self): return self._p

    class _Sess:
        def get(self, url, params=None, timeout=None):
            return _Resp({"parse": {"wikitext": aspects_wikitext, "revid": 2247}})

    data = load(_Sess())
    assert isinstance(data, AspectData)
    assert data.revid == 2247
    assert len(data.records) >= 18
