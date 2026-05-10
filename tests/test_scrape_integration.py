import shipdata
from scrape import to_text


class _Sess:
    def __init__(self, lua): self.lua = lua
    def get(self, *a, **kw):
        return _Resp({"parse": {"wikitext": self.lua, "revid": 1}})


class _Resp:
    def __init__(self, p): self._p = p
    def raise_for_status(self): pass
    def json(self): return self._p


def test_to_text_resolves_shipbox_field(cudal_page_wikitext, tiny_shipdata_lua):
    ctx = shipdata.load(_Sess(tiny_shipdata_lua))
    out = to_text(cudal_page_wikitext, shipdata=ctx)
    # Manufacturer field substitutes in for the #invoke call.
    assert "Frontier cutter" in out
    # Bare invoke calls do not survive in the output.
    assert "#invoke" not in out
    # The infobox call is suppressed — no leftover braces.
    assert "{{" not in out


def test_to_text_without_shipdata_drops_invokes(cudal_page_wikitext):
    out = to_text(cudal_page_wikitext)
    # No ShipData passed — invokes drop silently, leaving the prose with
    # gaps, but never emit literal #invoke markers.
    assert "#invoke" not in out
