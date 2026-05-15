import pytest

import resolvers
from shipdata import ShipRecord, ShipData


@pytest.fixture(autouse=True)
def isolate_registry():
    saved = dict(resolvers._REGISTRY)
    yield
    resolvers._REGISTRY.clear()
    resolvers._REGISTRY.update(saved)


def test_resolve_returns_none_for_unknown_module():
    assert resolvers.resolve("Unknown", "fn", [], ctx=None) is None


def test_register_and_resolve_roundtrip():
    @resolvers.register("Custom", "echo")
    def _echo(args, ctx):
        return ":".join(args)

    assert resolvers.resolve("Custom", "echo", ["a", "b"], ctx=None) == "a:b"


def test_shipbox_field_returns_value_from_record():
    record = ShipRecord(key="Cudal", display_name="Cudal", manufacturer="Frontier")
    ctx = ShipData(records={"Cudal": record}, revid=1)
    out = resolvers.resolve("Shipbox", "field", ["Cudal", "manufacturer"], ctx=ctx)
    assert out == "Frontier"


def test_shipbox_field_returns_empty_for_missing_record():
    ctx = ShipData(records={}, revid=1)
    out = resolvers.resolve("Shipbox", "field", ["Ghost", "manufacturer"], ctx=ctx)
    assert out == ""


def test_shipbox_field_returns_empty_for_unknown_field():
    record = ShipRecord(key="Cudal", display_name="Cudal", manufacturer="Frontier")
    ctx = ShipData(records={"Cudal": record}, revid=1)
    out = resolvers.resolve("Shipbox", "field", ["Cudal", "noSuchField"], ctx=ctx)
    assert out == ""


def test_shipbox_infobox_returns_empty_string():
    """Infobox is suppressed in article wikitext; facts are emitted as
    a separate Spec card chunk."""
    record = ShipRecord(key="Cudal", display_name="Cudal", manufacturer="Frontier")
    ctx = ShipData(records={"Cudal": record}, revid=1)
    out = resolvers.resolve("Shipbox", "infobox", ["Cudal"], ctx=ctx)
    assert out == ""


def test_shipbox_field_speed_renders_numeric():
    record = ShipRecord(key="Eclipse", display_name="Eclipse", speed=4020)
    ctx = ShipData(records={"Eclipse": record}, revid=1)
    out = resolvers.resolve("Shipbox", "field", ["Eclipse", "speed"], ctx=ctx)
    assert out == "4020"
