from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cudal_page_wikitext() -> str:
    return (FIXTURES / "Cudal.wikitext").read_text()


@pytest.fixture
def tiny_shipdata_lua() -> str:
    return (FIXTURES / "Module_ShipData_tiny.lua").read_text()
