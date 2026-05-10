import pytest

from aspectdata import (
    AspectData,
    AspectRecord,
    aspect_sentences,
    load,
    slot_roster_chunk,
)


class FakeSession:
    def __init__(self, lua_text: str, revid: int = 99):
        self.lua_text = lua_text
        self.revid = revid
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return _FakeResponse({
            "parse": {"wikitext": self.lua_text, "revid": self.revid}
        })


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _records(lua):
    return load(FakeSession(lua)).records


def test_load_returns_aspectdata_with_revid(tiny_aspectdata_lua):
    sess = FakeSession(tiny_aspectdata_lua, revid=2150)
    data = load(sess)
    assert isinstance(data, AspectData)
    assert data.revid == 2150
    assert "TurretCriticalDamage" in data.records


def test_aspectrecord_exposes_named_fields(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    crit = records["TurretCriticalDamage"]
    assert isinstance(crit, AspectRecord)
    assert crit.display_name == "Critical Attenuation"
    assert crit.slot == "Weapons"
    assert crit.common is True
    assert crit.size_note is None


def test_aspectrecord_parses_boost_stats(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    gamma = records["GenericRadioResist"]
    assert len(gamma.boost_stats) == 2
    stats = {b["stat"]: b for b in gamma.boost_stats}
    assert stats["RadiationResist"]["amount"] == pytest.approx(0.05)
    assert stats["EnergyResist"]["multiplier"] == pytest.approx(1.0)


def test_aspectrecord_handles_empty_boost_stats(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    crit = records["TurretCriticalDamage"]
    assert crit.boost_stats == ()


def test_aspectrecord_marks_placeholder_entries(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    placeholder = records["GenericElementResist"]  # image = nil
    assert placeholder.has_image is False
    real = records["GenericRadioResist"]
    assert real.has_image is True


def test_aspect_sentences_identity_includes_slot_and_rarity(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    text = aspect_sentences(records["TurretCriticalDamage"])
    assert "Critical Attenuation is a common Weapons-slot aspect" in text
    assert "increases critical strike damage" in text


def test_aspect_sentences_marks_rare_aspects(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    text = aspect_sentences(records["ModuleDroneAmountMk2"])
    assert "Oversized Drone Bay is a rare Dronebay-slot aspect" in text


def test_aspect_sentences_includes_size_note(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    text = aspect_sentences(records["ModuleDroneAmountMk2"])
    assert "Restricted to M/L only modules." in text


def test_aspect_sentences_emits_stat_effects_for_multiplier(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    text = aspect_sentences(records["ModuleEnergyBoost"])
    # multiplier 1.1 → +10% EnergyCapacity
    assert "Stat effects: +10% EnergyCapacity." in text


def test_aspect_sentences_emits_stat_effects_for_amount(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    text = aspect_sentences(records["GenericRadioResist"])
    assert "+5% RadiationResist" in text
    assert "+5% EnergyResist" in text


def test_aspect_sentences_uses_renamed_slot_label(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    text = aspect_sentences(records["GenericRadioResist"])
    # AllItems renders with a space.
    assert "All Items-slot aspect" in text


def test_slot_roster_groups_by_label_and_skips_placeholders(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    name, body = slot_roster_chunk(records)
    assert name == "Aspect roster"
    assert "Weapons (1): Critical Attenuation" in body
    assert "Dronebay (1): Oversized Drone Bay" in body
    assert "All Items (1): Gamma Ward" in body
    assert "All Modules (1): Microgenerators" in body
    # Placeholder entry (no image) must not show up.
    assert "GenericElementResist" not in body


from aspectdata import per_slot_chunks, per_rarity_chunks, per_effect_chunks


def test_per_slot_chunks_one_per_slot(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    chunks = dict(per_slot_chunks(records))
    # Slot labels (with spaces for compound enums) drive chunk names.
    assert "Aspects in Weapons slot" in chunks
    assert "Aspects in Dronebay slot" in chunks
    assert "Aspects in All Items slot" in chunks
    assert "Aspects in All Modules slot" in chunks


def test_per_slot_chunk_lists_aspects_with_descriptions(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    chunks = dict(per_slot_chunks(records))
    body = chunks["Aspects in Weapons slot"]
    assert "Critical Attenuation (common)" in body
    assert "Increases critical strike damage of this weapon by 25%" in body


def test_per_slot_chunk_skips_placeholder_entries(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    # GenericElementResist has slot=nil and image=nil — must not pollute any
    # per-slot chunk.
    for _, body in per_slot_chunks(records):
        assert "GenericElementResist" not in body


def test_per_rarity_chunks_split_common_and_rare(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    chunks = dict(per_rarity_chunks(records))
    assert "Common aspects" in chunks
    assert "Rare aspects" in chunks
    common_body = chunks["Common aspects"]
    rare_body = chunks["Rare aspects"]
    # Critical Attenuation is common; Oversized Drone Bay is rare.
    assert "Critical Attenuation" in common_body
    assert "Critical Attenuation" not in rare_body
    assert "Oversized Drone Bay" in rare_body
    assert "Oversized Drone Bay" not in common_body


def test_per_rarity_chunks_include_synonym_phrasing(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    chunks = dict(per_rarity_chunks(records))
    # 'epic' / 'purple' / 'green' are common player vocabulary; chunks
    # mention them so embedding-similarity queries land.
    assert "purple" in chunks["Rare aspects"].lower()
    assert "epic" in chunks["Rare aspects"].lower()
    assert "green" in chunks["Common aspects"].lower()


def test_per_effect_chunks_categorize_via_boost_stats(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    chunks = dict(per_effect_chunks(records))
    # Gamma Ward has Resist boostStats — must land in the resistance chunk.
    assert "Aspects boosting damage resistance" in chunks
    assert "Gamma Ward" in chunks["Aspects boosting damage resistance"]


def test_per_effect_chunks_categorize_via_description(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    chunks = dict(per_effect_chunks(records))
    # Critical Attenuation has empty boost_stats but description mentions
    # "critical" — must still land in the critical-hits chunk.
    assert "Aspects boosting critical hits" in chunks
    assert "Critical Attenuation" in chunks["Aspects boosting critical hits"]


def test_per_effect_chunk_lists_drones_aspects(tiny_aspectdata_lua):
    records = _records(tiny_aspectdata_lua)
    chunks = dict(per_effect_chunks(records))
    assert "Aspects boosting drones" in chunks
    body = chunks["Aspects boosting drones"]
    assert "Oversized Drone Bay" in body
