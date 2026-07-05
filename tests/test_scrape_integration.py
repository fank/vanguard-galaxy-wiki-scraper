import json
from pathlib import Path

import shipdata
import scrape
from scrape import to_text


class _Resp:
    def __init__(self, p): self._p = p
    def raise_for_status(self): pass
    def json(self): return self._p


def test_to_text_resolves_shipbox_field(cudal_page_wikitext):
    # Build a minimal ShipData context the resolver pipeline can look up "Cudal"
    # against. The saved Cudal.wikitext fixture still references
    # {{#invoke:Shipbox|field|Cudal|manufacturer}}; resolvers fill in the value.
    record = shipdata.ShipRecord.from_dict("Cudal", {
        "displayName": "Cudal",
        "manufacturer": "Frontier",
        "class": "Cutters",
    })
    ctx = shipdata.ShipData(records={"Cudal": record}, revid=0)
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


def test_to_text_strips_bare_category_lines():
    # strip_code leaves [[Category:X]] as a "Category:X" line — must be removed.
    out = to_text("Some prose.\n[[Category:Game World]]\n")
    assert "Category:" not in out
    assert "Some prose" in out


def test_split_sections_folds_character_lists_into_overview():
    wt = (
        "The Darkspace Compact is a major faction.\n\n"
        "== Darkspace Characters ==\n"
        "* [[Midas]]\n\n"
        "== History ==\n"
        "Long ago, things happened.\n"
    )
    sections = scrape.split_sections(wt, "Darkspace Compact")
    names = [n for n, _ in sections]
    assert names == ["Darkspace Compact – Overview", "Darkspace Compact – History"]
    overview_body = sections[0][1]
    # Folded section keeps its label so the LLM still sees the relationship.
    assert "Characters:" in overview_body
    assert "Midas" in overview_body


def test_split_sections_synthesizes_overview_when_only_fold_sections_exist():
    wt = "== Void Drifters Characters ==\n* James Fleddon\n* Claude\n"
    sections = scrape.split_sections(wt, "Void Drifters")
    assert [n for n, _ in sections] == ["Void Drifters – Overview"]
    assert "James Fleddon" in sections[0][1]


def test_split_sections_drops_gallery_sections():
    wt = "== Gallery ==\n[[File:foo.png|thumb]]\n[[Category:World]]\n"
    assert scrape.split_sections(wt, "Industrial Ops") == []


def test_emit_chunks_prepends_name_header_to_embedded_text():
    rows: list[tuple[str, str]] = []
    scrape._emit_chunks("Darkspace Compact – Overview", "Midas runs the compact.", rows)
    assert rows == [("Darkspace Compact – Overview",
                     "Darkspace Compact – Overview\n\nMidas runs the compact.")]


def test_emit_chunks_repeats_header_on_every_sub_chunk():
    """When a body exceeds TEXT_CAP and splits into multiple sub-chunks, every
    sub-chunk must carry the name header — otherwise chunks 2..N lose all
    page/section context and embed as anonymous fragments."""
    rows: list[tuple[str, str]] = []
    # Build a body that paragraph-splits cleanly into ~3 chunks of ~800 chars.
    big_paragraph = "alpha beta gamma " * 60  # ~1020 chars
    body = "\n\n".join([big_paragraph] * 3)
    scrape._emit_chunks("Consumables – Consumables", body, rows)
    assert len(rows) >= 2, "body should have split into at least two chunks"
    for name, text in rows:
        # Every emitted chunk must start with the header line.
        assert text.startswith("Consumables – Consumables\n\n"), \
            f"chunk {name!r} missing header prefix"
        # And the body portion must contain real content, not just the header.
        assert text != "Consumables – Consumables\n\n", \
            f"chunk {name!r} is header-only"


class _SessAllPages:
    """Minimal session stub for end-to-end main_with_args tests.

    Returns a one-entry allpages list, the Cudal page wikitext for regular
    page-parsing, and the saved Ship List / Aspects wikitext snapshots for the
    structured-chunk loaders. Each source page gets a distinct revid so
    manifest sentinels are distinguishable."""

    SHIP_LIST_REVID = 99
    ASPECTS_REVID = 88
    CUDAL_REVID = 7

    def __init__(
        self,
        cudal_text: str,
        ship_list_text: str,
        aspects_text: str | None = None,
    ):
        self.cudal_text = cudal_text
        self.ship_list_text = ship_list_text
        # An empty <tabber> still parses cleanly, yielding zero aspects.
        self.aspects_text = aspects_text or "== Aspect List ==\n<tabber></tabber>"
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
            if page == "Ship List":
                return _Resp({"parse": {
                    "wikitext": self.ship_list_text,
                    "revid": self.SHIP_LIST_REVID,
                }})
            if page == "Aspects":
                return _Resp({"parse": {
                    "wikitext": self.aspects_text,
                    "revid": self.ASPECTS_REVID,
                }})
            return _Resp({"parse": {
                "wikitext": self.cudal_text,
                "revid": self.CUDAL_REVID,
            }})
        raise AssertionError(f"unexpected request: {params}")


def test_main_emits_spec_card_per_ship(
    cudal_page_wikitext, ship_list_wikitext, tmp_path, monkeypatch
):
    sess = _SessAllPages(cudal_page_wikitext, ship_list_wikitext)
    monkeypatch.setattr(scrape.requests, "Session", lambda: sess)
    monkeypatch.setattr(scrape, "list_articles",
                        lambda s: iter([("Cudal", 1)]))

    rc = scrape.main_with_args(["--out", str(tmp_path), "--full", "--sleep", "0"])
    assert rc == 0
    payload = json.loads((tmp_path / "vg_wiki.json").read_text())
    # Fixture has Cudal sold by both Frontier and Marade Wharf — disambiguated
    # keys give two Spec cards, each linking to the other as a variant.
    assert "Cudal (Frontier) – Spec" in payload
    assert "Cudal (Marade Wharf) – Spec" in payload


def test_main_records_shipdata_revid_in_manifest(
    cudal_page_wikitext, ship_list_wikitext, tmp_path, monkeypatch
):
    sess = _SessAllPages(cudal_page_wikitext, ship_list_wikitext)
    monkeypatch.setattr(scrape.requests, "Session", lambda: sess)
    monkeypatch.setattr(scrape, "list_articles",
                        lambda s: iter([("Cudal", 1)]))

    scrape.main_with_args(["--out", str(tmp_path), "--full", "--sleep", "0"])
    manifest = json.loads((tmp_path / "vg_wiki.manifest.json").read_text())
    assert manifest["__module_shipdata"] == _SessAllPages.SHIP_LIST_REVID


def test_dry_run_prints_sample_card_and_writes_nothing(
    cudal_page_wikitext, ship_list_wikitext, tmp_path, monkeypatch, capsys
):
    sess = _SessAllPages(cudal_page_wikitext, ship_list_wikitext)
    monkeypatch.setattr(scrape.requests, "Session", lambda: sess)
    monkeypatch.setattr(scrape, "list_articles",
                        lambda s: iter([("Cudal", 1)]))

    rc = scrape.main_with_args(
        ["--out", str(tmp_path), "--full", "--sleep", "0", "--dry-run"]
    )
    assert rc == 0
    assert not (tmp_path / "vg_wiki.json").exists()
    out = capsys.readouterr().out
    assert "Spec" in out


def test_main_emits_ranking_and_roster_chunks(
    cudal_page_wikitext, ship_list_wikitext, tmp_path, monkeypatch
):
    sess = _SessAllPages(cudal_page_wikitext, ship_list_wikitext)
    monkeypatch.setattr(scrape.requests, "Session", lambda: sess)
    monkeypatch.setattr(scrape, "list_articles",
                        lambda s: iter([("Cudal", 1)]))

    rc = scrape.main_with_args(["--out", str(tmp_path), "--full", "--sleep", "0"])
    assert rc == 0
    payload = json.loads((tmp_path / "vg_wiki.json").read_text())
    # Names may be plain ("Ship rankings – Cargo capacity") or chunk-suffixed
    # ("(1/4)") depending on whether the leaderboard fits one TEXT_CAP slice.
    def _present(prefix: str) -> bool:
        return any(n == prefix or n.startswith(f"{prefix} (") for n in payload)
    assert _present("Ship rankings – Cargo capacity")
    assert _present("Ship rankings – Warp speed")
    assert _present("Ship roster")


def test_main_excludes_ship_list_page_from_per_section_scrape(
    cudal_page_wikitext, ship_list_wikitext, tmp_path, monkeypatch
):
    """The Ship List page is excluded from regular page scraping because its
    content is emitted as structured Spec/Ranking/Roster chunks instead."""
    sess = _SessAllPages(cudal_page_wikitext, ship_list_wikitext)
    monkeypatch.setattr(scrape.requests, "Session", lambda: sess)
    monkeypatch.setattr(scrape, "list_articles",
                        lambda s: iter([("Cudal", 1), ("Ship List", 2)]))

    scrape.main_with_args(["--out", str(tmp_path), "--full", "--sleep", "0"])
    payload = json.loads((tmp_path / "vg_wiki.json").read_text())
    # No "Ship List – *" page-derived chunks should appear.
    assert not any(name.startswith("Ship List – ") for name in payload)


def test_main_emits_aspect_chunks(
    cudal_page_wikitext, ship_list_wikitext, aspects_wikitext, tmp_path, monkeypatch
):
    sess = _SessAllPages(cudal_page_wikitext, ship_list_wikitext, aspects_wikitext)
    monkeypatch.setattr(scrape.requests, "Session", lambda: sess)
    monkeypatch.setattr(scrape, "list_articles",
                        lambda s: iter([("Cudal", 1)]))

    rc = scrape.main_with_args(["--out", str(tmp_path), "--full", "--sleep", "0"])
    assert rc == 0
    payload = json.loads((tmp_path / "vg_wiki.json").read_text())
    assert "Critical Attenuation – Aspect" in payload
    assert "Gamma Ward – Aspect" in payload
    assert "Aspect roster" in payload
    manifest = json.loads((tmp_path / "vg_wiki.manifest.json").read_text())
    assert manifest["__module_aspectdata"] == _SessAllPages.ASPECTS_REVID
