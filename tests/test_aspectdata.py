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
