import pytest

from shipdata import ShipData, ShipRecord, load, parse_lua, spec_sentences


def test_parse_lua_extracts_three_ships(tiny_shipdata_lua):
    records = parse_lua(tiny_shipdata_lua)
    assert set(records) == {"Cudal", "Cudal-Marade", "Eclipse"}


def test_parse_lua_extracts_string_fields(tiny_shipdata_lua):
    cudal = parse_lua(tiny_shipdata_lua)["Cudal"]
    assert cudal["manufacturer"] == "Frontier"
    assert cudal["class"] == "Cutters"
    assert cudal["shipyardRep"] == "Neutral"


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
    assert cudal.ship_class == "Cutters"
    assert cudal.hardpoints == ["S", "S"]
    assert cudal.not_for_sale is False  # default when absent


def test_shiprecord_handles_missing_optional_fields(tiny_shipdata_lua):
    data = load(FakeSession(tiny_shipdata_lua))
    eclipse = data.records["Eclipse"]
    assert eclipse.shipyard_factions is None
    assert eclipse.shipyard_level is None
    assert eclipse.not_for_sale is True


def test_shiprecord_parses_shipyard_factions_list(tiny_shipdata_lua):
    data = load(FakeSession(tiny_shipdata_lua))
    cudal = data.records["Cudal"]
    assert cudal.shipyard_factions == ["Frontier"]
    marade = data.records["Cudal-Marade"]
    assert marade.shipyard_factions == ["Marauders", "Corsair Syndicate"]


def test_shiprecord_falls_back_to_legacy_singular_field():
    legacy = {"shipyardFaction": "Frontier"}
    record = ShipRecord.from_dict("Legacy", legacy)
    assert record.shipyard_factions == ["Frontier"]


def test_load_calls_api_once(tiny_shipdata_lua):
    sess = FakeSession(tiny_shipdata_lua)
    load(sess)
    assert sess.calls == 1


def _records(lua):
    return load(FakeSession(lua)).records


def test_spec_identity_sentence(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal"], records)
    assert "The Cudal is a Frontier cutter, a combat hull." in text


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


def test_spec_shipyard_sentence_joins_multiple_factions(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal-Marade"], records)
    # Cudal-Marade now lists two factions; sentence should join naturally.
    assert "It sells at Marauders and Corsair Syndicate shipyards" in text


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


def test_spec_combat_sentence_singularizes_crew(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal"], records)
    # Cudal has crew=1 — must read "1 crew slot", not "1 crew slots".
    assert "1 crew slot" in text
    assert "1 crew slots" not in text


def test_spec_combat_sentence_pluralizes_crew(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Eclipse"], records)
    # Eclipse has crew=5.
    assert "5 crew slots" in text


def test_spec_identity_singularizes_plural_class(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal"], records)
    # Live ShipData stores class as plurals ('Cutters'); the sentence must
    # singularize so it reads naturally.
    assert " cutters" not in text.lower()
    assert "cutter" in text


def test_spec_identity_includes_role(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    eclipse_text = spec_sentences(records["Eclipse"], records)
    assert "a combat hull" in eclipse_text
    cudal_text = spec_sentences(records["Cudal"], records)
    assert "a combat hull" in cudal_text


from shipdata import ranking_chunks, class_roster_chunk


def test_ranking_chunks_returns_one_per_stat(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    chunks = ranking_chunks(records)
    names = [n for n, _ in chunks]
    assert "Ship rankings – Cargo capacity" in names
    assert "Ship rankings – Hull modifier" in names
    assert "Ship rankings – Shield modifier" in names
    assert "Ship rankings – Armor modifier" in names
    assert "Ship rankings – Warp speed" in names
    assert "Ship rankings – Warp acceleration" in names
    assert "Ship rankings – Crew capacity" in names


def test_ranking_chunks_sorted_descending(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    chunks = dict(ranking_chunks(records))
    body = chunks["Ship rankings – Cargo capacity"]
    # Eclipse=1060, Cudal=Cudal-Marade=80 — Eclipse must come first.
    eclipse_pos = body.index("Eclipse")
    cudal_pos = body.index("Cudal")
    assert eclipse_pos < cudal_pos


def test_ranking_chunks_excludes_none_values(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    chunks = dict(ranking_chunks(records))
    # Every entry that ships in the leaderboard must list a numeric value
    # (no "None" strings leaking through).
    for name, body in chunks.items():
        assert "None" not in body, f"{name} contains a None value"


def test_ranking_chunk_includes_class_and_manufacturer(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    chunks = dict(ranking_chunks(records))
    body = chunks["Ship rankings – Cargo capacity"]
    assert "(Kharon Forgeworks destroyer)" in body  # Eclipse
    assert "(Frontier cutter)" in body              # Cudal


def test_class_roster_lists_all_ships_grouped(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    name, body = class_roster_chunk(records)
    assert name == "Ship roster"
    # Cudal and Cudal-Marade share class Cutters; Eclipse is Destroyers.
    assert "Cutters (2): Cudal, Cudal-Marade" in body
    assert "Destroyers (1): Eclipse" in body


def test_class_roster_groups_alphabetically_by_class(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    _, body = class_roster_chunk(records)
    # Cutters before Destroyers alphabetically.
    assert body.index("Cutters") < body.index("Destroyers")
