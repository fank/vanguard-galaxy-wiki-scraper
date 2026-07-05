from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cudal_page_wikitext() -> str:
    return (FIXTURES / "Cudal.wikitext").read_text()


@pytest.fixture
def ship_list_wikitext() -> str:
    """Saved snapshot of [[Ship List]] — the canonical ship data source after
    the Lua modules were removed from the wiki."""
    return (FIXTURES / "ship_list.wt").read_text()


@pytest.fixture
def aspects_wikitext() -> str:
    """Saved snapshot of [[Aspects]] — the canonical aspect data source after
    the Lua modules were removed from the wiki."""
    return (FIXTURES / "aspects.wt").read_text()
