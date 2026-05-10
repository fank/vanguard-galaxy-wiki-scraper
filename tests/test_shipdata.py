import pytest

from shipdata import parse_lua


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
