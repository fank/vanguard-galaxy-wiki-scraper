import pytest

from shipdata import ShipData, ShipRecord, load, parse_lua, spec_sentences


def test_parse_lua_extracts_three_ships(tiny_shipdata_lua):
    records = parse_lua(tiny_shipdata_lua)
    assert set(records) == {"Cudal", "Cudal-Marade", "Eclipse"}


def test_parse_lua_extracts_string_fields(tiny_shipdata_lua):
    cudal = parse_lua(tiny_shipdata_lua)["Cudal"]
    assert cudal["manufacturer"] == "Frontier"
    assert cudal["class"] == "Cutter"
    assert cudal["shipyardFaction"] == "Frontier"


def test_parse_lua_coerces_numeric_fields(tiny_shipdata_lua):
    cudal = parse_lua(tiny_shipdata_lua)["Cudal"]
    assert cudal["hullScale"] == 2.1
    assert cudal["speed"] == 5800
    assert cudal["crew"] == 1


def test_parse_lua_extracts_hardpoint_arrays(tiny_shipdata_lua):
    eclipse = parse_lua(tiny_shipdata_lua)["Eclipse"]
    assert eclipse["hardpoints"] == ["L", "M", "M", "M"]


def test_parse_lua_extracts_booleans(tiny_shipdata_lua):
    eclipse = parse_lua(tiny_shipdata_lua)["Eclipse"]
    assert eclipse["notForSale"] is True


def test_parse_lua_omits_missing_fields(tiny_shipdata_lua):
    eclipse = parse_lua(tiny_shipdata_lua)["Eclipse"]
    assert "shipyardLevel" not in eclipse
    assert "shipyardFaction" not in eclipse


def test_parse_lua_keeps_keys_with_dashes(tiny_shipdata_lua):
    records = parse_lua(tiny_shipdata_lua)
    assert records["Cudal-Marade"]["manufacturer"] == "Marade Wharf"
    assert records["Cudal-Marade"]["conquestRank"] == "Cutthroat"


class FakeSession:
    def __init__(self, lua_text: str, revid: int = 42):
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


def test_load_returns_shipdata_with_revid(tiny_shipdata_lua):
    sess = FakeSession(tiny_shipdata_lua, revid=1234)
    data = load(sess)
    assert isinstance(data, ShipData)
    assert data.revid == 1234
    assert "Cudal" in data.records


def test_shiprecord_exposes_named_fields(tiny_shipdata_lua):
    data = load(FakeSession(tiny_shipdata_lua))
    cudal = data.records["Cudal"]
    assert isinstance(cudal, ShipRecord)
    assert cudal.key == "Cudal"
    assert cudal.display_name == "Cudal"
    assert cudal.manufacturer == "Frontier"
    assert cudal.ship_class == "Cutter"
    assert cudal.hardpoints == ["S", "S"]
    assert cudal.not_for_sale is False  # default when absent


def test_shiprecord_handles_missing_optional_fields(tiny_shipdata_lua):
    data = load(FakeSession(tiny_shipdata_lua))
    eclipse = data.records["Eclipse"]
    assert eclipse.shipyard_faction is None
    assert eclipse.shipyard_level is None
    assert eclipse.not_for_sale is True


def test_load_calls_api_once(tiny_shipdata_lua):
    sess = FakeSession(tiny_shipdata_lua)
    load(sess)
    assert sess.calls == 1


def _records(lua):
    return load(FakeSession(lua)).records


def test_spec_identity_sentence(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal"], records)
    assert "The Cudal is a Frontier cutter." in text


def test_spec_combat_profile_includes_modifiers(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal"], records)
    assert "hull modifier is 2.1×" in text
    assert "shield 2.9×" in text
    assert "armor 1.8×" in text


def test_spec_combat_profile_includes_hardpoints(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Eclipse"], records)
    assert "1 large, 3 medium" in text


def test_spec_shipyard_sentence(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal"], records)
    assert "It sells at Frontier shipyards" in text
    assert "shipyard level 1+" in text
    assert "Neutral reputation" in text
    assert "player level 1" in text


def test_spec_conquest_sentence(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal-Marade"], records)
    assert "Cutthroat conquest rank" in text


def test_spec_not_for_sale_sentence(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Eclipse"], records)
    assert "awarded as a story reward" in text
    assert "not sold at any shipyard" in text
    assert "Frontier shipyards" not in text


def test_spec_variant_sentence_links_canonical(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal-Marade"], records)
    assert "Cudal-Marade is the Marade Wharf-resold variant of the Cudal" in text


def test_spec_canonical_ship_has_no_variant_sentence(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal"], records)
    assert "variant" not in text.lower()
