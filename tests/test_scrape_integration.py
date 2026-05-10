import json
from pathlib import Path

import shipdata
import scrape
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


class _SessAllPages:
    """Minimal session stub: returns a fixed allpages list, the Cudal page
    wikitext, and a tiny Module:ShipData."""

    def __init__(self, cudal_text: str, lua_text: str):
        self.cudal_text = cudal_text
        self.lua_text = lua_text
        self.headers: dict[str, str] = {}

    def get(self, url, params=None, timeout=None):
        params = params or {}
        action = params.get("action")
        if action == "query" and params.get("list") == "allpages":
            return _Resp({
                "query": {"allpages": [{"title": "Cudal", "pageid": 1}]}
            })
        if action == "parse":
            page = params.get("page")
            if page == "Module:ShipData":
                return _Resp({"parse": {"wikitext": self.lua_text, "revid": 99}})
            return _Resp({"parse": {"wikitext": self.cudal_text, "revid": 7}})
        raise AssertionError(f"unexpected request: {params}")


def test_main_emits_spec_card_per_ship(
    cudal_page_wikitext, tiny_shipdata_lua, tmp_path, monkeypatch
):
    sess = _SessAllPages(cudal_page_wikitext, tiny_shipdata_lua)
    monkeypatch.setattr(scrape.requests, "Session", lambda: sess)
    monkeypatch.setattr(scrape, "list_articles",
                        lambda s: iter([("Cudal", 1)]))

    rc = scrape.main_with_args(["--out", str(tmp_path), "--full", "--sleep", "0"])
    assert rc == 0
    payload = json.loads((tmp_path / "vg_wiki.json").read_text())
    assert "Cudal – Spec" in payload
    assert "Cudal-Marade – Spec" in payload
    assert "Eclipse – Spec" in payload
    # Article chunk has resolved values.
    overview = payload["Cudal – Overview"]["text"]
    assert "Frontier cutter" in overview


def test_main_records_shipdata_revid_in_manifest(
    cudal_page_wikitext, tiny_shipdata_lua, tmp_path, monkeypatch
):
    sess = _SessAllPages(cudal_page_wikitext, tiny_shipdata_lua)
    monkeypatch.setattr(scrape.requests, "Session", lambda: sess)
    monkeypatch.setattr(scrape, "list_articles",
                        lambda s: iter([("Cudal", 1)]))

    scrape.main_with_args(["--out", str(tmp_path), "--full", "--sleep", "0"])
    manifest = json.loads((tmp_path / "vg_wiki.manifest.json").read_text())
    assert manifest["__module_shipdata"] == 99


def test_dry_run_prints_sample_card_and_writes_nothing(
    cudal_page_wikitext, tiny_shipdata_lua, tmp_path, monkeypatch, capsys
):
    sess = _SessAllPages(cudal_page_wikitext, tiny_shipdata_lua)
    monkeypatch.setattr(scrape.requests, "Session", lambda: sess)
    monkeypatch.setattr(scrape, "list_articles",
                        lambda s: iter([("Cudal", 1)]))

    rc = scrape.main_with_args(
        ["--out", str(tmp_path), "--full", "--sleep", "0", "--dry-run"]
    )
    assert rc == 0
    assert not (tmp_path / "vg_wiki.json").exists()
    out = capsys.readouterr().out
    assert "Cudal – Spec" in out
    assert "Frontier cutter" in out


def test_main_emits_ranking_and_roster_chunks(
    cudal_page_wikitext, tiny_shipdata_lua, tmp_path, monkeypatch
):
    sess = _SessAllPages(cudal_page_wikitext, tiny_shipdata_lua)
    monkeypatch.setattr(scrape.requests, "Session", lambda: sess)
    monkeypatch.setattr(scrape, "list_articles",
                        lambda s: iter([("Cudal", 1)]))

    rc = scrape.main_with_args(["--out", str(tmp_path), "--full", "--sleep", "0"])
    assert rc == 0
    payload = json.loads((tmp_path / "vg_wiki.json").read_text())
    assert "Ship rankings – Cargo capacity" in payload
    assert "Ship rankings – Warp speed" in payload
    assert "Ship roster" in payload
    cargo = payload["Ship rankings – Cargo capacity"]["text"]
    assert cargo.index("Eclipse") < cargo.index("Cudal")
