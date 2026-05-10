# Ship-data RAG export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve `{{#invoke:Shipbox|...}}` parser-function calls in scraped wikitext, and emit one natural-language Spec card per ship from `Module:ShipData`, so the vrt-cogs Assistant RAG cog can answer ship questions accurately.

**Architecture:** Add a small resolver registry (`resolvers.py`) keyed on `(module, function)` that substitutes parser-function calls with wikitext during `to_text`. Add a Lua module accessor (`shipdata.py`) that fetches and parses `Module:ShipData` once per run, exposes typed `ShipRecord`s, and builds Spec-card sentences. Wire both into `scrape.py` without disturbing the article-page incremental flow.

**Tech Stack:** Python 3.10+, `requests`, `mwparserfromhell`, `pytest` (new — dev-only).

**Spec:** `docs/superpowers/specs/2026-05-10-shipdata-rag-export-design.md`

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `resolvers.py` | new | Registry of `(module, fn) → handler`. Built-in handlers for `Shipbox.field` / `Shipbox.infobox`. Public API: `register(module, fn)` decorator, `resolve(module, fn, args, ctx) -> str | None`. |
| `shipdata.py` | new | Fetch `Module:ShipData` via API; Lua parser; `ShipRecord` dataclass; `load(session) -> ShipData` (returns records dict + revid); `spec_sentences(record, all_records) -> str`. |
| `scrape.py` | modify | Call `resolve_invokes` in `to_text`; emit Spec cards in `main()`; track `Module:ShipData` revid in manifest under `__module_shipdata`. |
| `tests/` | new | `pytest` test directory. |
| `tests/conftest.py` | new | Shared fixtures: `cudal_page_wikitext`, `tiny_shipdata_lua`. |
| `tests/test_shipdata.py` | new | Parser + ShipRecord + spec_sentences tests. |
| `tests/test_resolvers.py` | new | Registry + Shipbox handler tests. |
| `tests/test_scrape_integration.py` | new | `to_text` resolver integration; main() spec-card emission. |
| `tests/fixtures/Cudal.wikitext` | new | Captured Cudal page wikitext. |
| `tests/fixtures/Module_ShipData_tiny.lua` | new | Three-ship Lua excerpt for parser tests. |
| `requirements-dev.txt` | new | `pytest>=8.0`. |
| `README.md` | modify | Document new Spec-card chunks, `__module_shipdata` manifest sentinel, `--dry-run` flag. |

---

## Task 1: Test scaffolding

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/Cudal.wikitext`
- Create: `tests/fixtures/Module_ShipData_tiny.lua`
- Create: `pyproject.toml`

- [ ] **Step 1: Create dev requirements file**

`requirements-dev.txt`:
```
pytest>=8.0
```

- [ ] **Step 2: Create the test package init**

`tests/__init__.py`:
```python
```

(Empty file. Just makes pytest treat `tests/` as a package so fixtures imports resolve.)

- [ ] **Step 3: Create pyproject.toml for pytest configuration**

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

- [ ] **Step 4: Add the Cudal wikitext fixture**

`tests/fixtures/Cudal.wikitext`:
```
{{#invoke:Shipbox|infobox|Cudal}}

The '''Cudal''' is a [[{{#invoke:Shipbox|field|Cudal|manufacturer}}]] cutter sold at [[Frontier]] shipyards. [[Marade Wharf]] resells the same hull as the Cudal-Marade.

[[Category:Ships]]
[[Category:Cutters]]
[[Category:{{#invoke:Shipbox|field|Cudal|manufacturer}}]]
```

- [ ] **Step 5: Add a tiny ShipData Lua fixture**

`tests/fixtures/Module_ShipData_tiny.lua`:
```lua
return {
    ["Cudal"] = {
        displayName = "Cudal",
        manufacturer = "Frontier",
        class = "Cutter",
        hullScale = 2.1,
        shieldScale = 2.9,
        armorScale = 1.8,
        hardpoints = {"S", "S"},
        speed = 5800,
        accel = 14.2,
        crew = 1,
        cargo = 80,
        playerLevel = 1,
        shipyardLevel = "1+",
        shipyardRep = "Neutral",
        shipyardFaction = "Frontier",
    },
    ["Cudal-Marade"] = {
        displayName = "Cudal",
        manufacturer = "Marade Wharf",
        class = "Cutter",
        hullScale = 2.1,
        shieldScale = 2.9,
        armorScale = 1.8,
        hardpoints = {"S", "S"},
        speed = 5800,
        accel = 14.2,
        crew = 1,
        cargo = 80,
        playerLevel = 5,
        shipyardLevel = "5+",
        shipyardRep = "Distinguished",
        shipyardFaction = "Marauders",
        conquestRank = "Cutthroat",
        notes = "Original manufacturer is [[Frontier]].",
    },
    ["Eclipse"] = {
        displayName = "Eclipse",
        manufacturer = "Kharon Forgeworks",
        class = "Destroyer",
        hullScale = 8.1,
        shieldScale = 8.9,
        armorScale = 7.5,
        hardpoints = {"L", "M", "M", "M"},
        speed = 4020,
        accel = 11.2,
        crew = 5,
        cargo = 1060,
        notForSale = true,
    },
}
```

- [ ] **Step 6: Create empty conftest.py with fixture loaders**

`tests/conftest.py`:
```python
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cudal_page_wikitext() -> str:
    return (FIXTURES / "Cudal.wikitext").read_text()


@pytest.fixture
def tiny_shipdata_lua() -> str:
    return (FIXTURES / "Module_ShipData_tiny.lua").read_text()
```

- [ ] **Step 7: Verify pytest discovers the empty test set**

Run:
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
```
Expected output ends with `no tests ran` and exit code 5 (pytest's "no tests collected").

- [ ] **Step 8: Commit**

```bash
git add requirements-dev.txt pyproject.toml tests/
git commit -m "test: scaffold pytest with shipdata + cudal page fixtures"
```

---

## Task 2: Lua parser for Module:ShipData

**Files:**
- Create: `shipdata.py`
- Create: `tests/test_shipdata.py`

- [ ] **Step 1: Write the failing parser tests**

`tests/test_shipdata.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/test_shipdata.py -v`
Expected: 7 errors (`ModuleNotFoundError: No module named 'shipdata'`).

- [ ] **Step 3: Implement the parser**

`shipdata.py`:
```python
"""Module:ShipData accessor for the wiki scraper.

Fetches the wiki's Lua data module, parses it into Python dicts, exposes a
typed `ShipRecord` per ship, and builds natural-language Spec card text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# The wiki's Module:ShipData uses a stable emit format from
# `dataexport/tools/merge_shipdata.py`:
#   ["<Key>"] = { name = value, ... },
# so a regex parser over that exact shape is sufficient and avoids pulling in
# a full Lua interpreter.
_ENTRY_RE = re.compile(r'\[\s*"([^"]+)"\s*\]\s*=\s*\{', re.S)
_FIELD_RE = re.compile(
    r'^(\s*)(\w+)\s*=\s*(.*?),\s*(?:--[^\n]*)?$',
    re.M,
)


def _coerce(value_text: str) -> Any:
    v = value_text.strip()
    if v == "nil":
        return None
    if v == "true":
        return True
    if v == "false":
        return False
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    if v.startswith("{") and v.endswith("}"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        # Hardpoints / similar are arrays of strings; sizeSummary is k=v but
        # the scraper doesn't surface it in the spec card so leave it as-is.
        items = [s.strip() for s in inner.split(",") if s.strip()]
        out = []
        for item in items:
            if "=" in item:
                # k=v table — return the original text; spec_sentences ignores it.
                return v
            out.append(_coerce(item))
        return out
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v  # fallback: keep raw text


def parse_lua(text: str) -> dict[str, dict[str, Any]]:
    """Parse a Module:ShipData Lua source into {key: {field: value}}."""
    records: dict[str, dict[str, Any]] = {}
    for m in _ENTRY_RE.finditer(text):
        key = m.group(1)
        depth = 1
        i = m.end()
        while i < len(text) and depth > 0:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        body = text[m.end():i - 1]
        fields: dict[str, Any] = {}
        for fm in _FIELD_RE.finditer(body):
            fields[fm.group(2)] = _coerce(fm.group(3))
        records[key] = fields
    return records
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/test_shipdata.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add shipdata.py tests/test_shipdata.py
git commit -m "feat(shipdata): parse Module:ShipData Lua into Python dicts"
```

---

## Task 3: ShipRecord and load()

**Files:**
- Modify: `shipdata.py`
- Modify: `tests/test_shipdata.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_shipdata.py`:
```python
from shipdata import ShipData, ShipRecord, load


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
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/test_shipdata.py -v`
Expected: 4 new errors importing `ShipData`, `ShipRecord`, `load`.

- [ ] **Step 3: Implement ShipRecord, ShipData, load()**

Append to `shipdata.py`:
```python
@dataclass(frozen=True)
class ShipRecord:
    key: str
    display_name: str
    manufacturer: str | None = None
    ship_class: str | None = None
    hull_scale: float | None = None
    shield_scale: float | None = None
    armor_scale: float | None = None
    hardpoints: list[str] | None = None
    speed: float | None = None
    accel: float | None = None
    crew: int | None = None
    cargo: int | None = None
    player_level: int | None = None
    shipyard_level: str | None = None
    shipyard_rep: str | None = None
    shipyard_faction: str | None = None
    conquest_rank: str | None = None
    not_for_sale: bool = False

    @classmethod
    def from_dict(cls, key: str, d: dict[str, Any]) -> "ShipRecord":
        return cls(
            key=key,
            display_name=d.get("displayName", key),
            manufacturer=d.get("manufacturer"),
            ship_class=d.get("class"),
            hull_scale=d.get("hullScale"),
            shield_scale=d.get("shieldScale"),
            armor_scale=d.get("armorScale"),
            hardpoints=d.get("hardpoints"),
            speed=d.get("speed"),
            accel=d.get("accel"),
            crew=d.get("crew"),
            cargo=d.get("cargo"),
            player_level=d.get("playerLevel"),
            shipyard_level=(
                str(d["shipyardLevel"]) if "shipyardLevel" in d else None
            ),
            shipyard_rep=d.get("shipyardRep"),
            shipyard_faction=d.get("shipyardFaction"),
            conquest_rank=d.get("conquestRank"),
            not_for_sale=bool(d.get("notForSale", False)),
        )


@dataclass(frozen=True)
class ShipData:
    records: dict[str, ShipRecord]
    revid: int


_API_URL = "https://vanguard-galaxy.fandom.com/api.php"


def load(session) -> ShipData:
    """Fetch and parse Module:ShipData. One network call per scraper run."""
    resp = session.get(
        _API_URL,
        params={
            "action": "parse",
            "page": "Module:ShipData",
            "prop": "wikitext|revid",
            "format": "json",
            "formatversion": "2",
        },
        timeout=30,
    )
    resp.raise_for_status()
    parse = resp.json()["parse"]
    raw = parse_lua(parse["wikitext"])
    records = {k: ShipRecord.from_dict(k, v) for k, v in raw.items()}
    return ShipData(records=records, revid=int(parse["revid"]))
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/test_shipdata.py -v`
Expected: all 11 tests pass (7 from Task 2 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add shipdata.py tests/test_shipdata.py
git commit -m "feat(shipdata): typed ShipRecord and load() over MediaWiki API"
```

---

## Task 4: Spec-card sentence builder

**Files:**
- Modify: `shipdata.py`
- Modify: `tests/test_shipdata.py`

- [ ] **Step 1: Add failing tests for each acquisition branch**

Append to `tests/test_shipdata.py`:
```python
from shipdata import spec_sentences


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
    assert "Frontier shipyards" not in text  # no shipyard sentence


def test_spec_variant_sentence_links_canonical(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal-Marade"], records)
    # Marade variant — same displayName as Cudal but different key.
    assert "Cudal-Marade is the Marade Wharf-resold variant of the Cudal" in text


def test_spec_canonical_ship_has_no_variant_sentence(tiny_shipdata_lua):
    records = _records(tiny_shipdata_lua)
    text = spec_sentences(records["Cudal"], records)
    assert "variant" not in text.lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/test_shipdata.py -v`
Expected: 8 new failures (`ImportError: cannot import name 'spec_sentences'`).

- [ ] **Step 3: Implement spec_sentences**

Append to `shipdata.py`:
```python
def _format_hardpoints(hp: list[str]) -> str:
    sizes = {"L": "large", "M": "medium", "S": "small", "T": "tiny"}
    counts: dict[str, int] = {}
    for h in hp:
        counts[h] = counts.get(h, 0) + 1
    parts: list[str] = []
    for code in ("L", "M", "S", "T"):
        n = counts.get(code, 0)
        if n:
            parts.append(f"{n} {sizes[code]}")
    return ", ".join(parts) if parts else "no"


def _identity_sentence(r: ShipRecord) -> str:
    cls = (r.ship_class or "ship").lower()
    mfr = r.manufacturer or "unknown-manufacturer"
    return f"The {r.key} is a {mfr} {cls}."


def _combat_sentence(r: ShipRecord) -> str:
    parts: list[str] = []
    mods = []
    if r.hull_scale is not None:
        mods.append(f"hull modifier is {r.hull_scale:g}×")
    if r.shield_scale is not None:
        mods.append(f"shield {r.shield_scale:g}×")
    if r.armor_scale is not None:
        mods.append(f"armor {r.armor_scale:g}×")
    if mods:
        parts.append("Its " + ", ".join(mods) + ".")
    if r.hardpoints:
        parts.append(f"It carries {_format_hardpoints(r.hardpoints)} hardpoints.")
    misc: list[str] = []
    if r.speed is not None:
        spd = f"warps at {r.speed:g} ls/s"
        if r.accel is not None:
            spd += f" with {r.accel:g} ls/s² acceleration"
        misc.append(spd)
    if r.crew is not None:
        misc.append(f"has {r.crew} crew slots")
    if r.cargo is not None:
        misc.append(f"carries {r.cargo} cargo units")
    if misc:
        parts.append("It " + ", ".join(misc) + ".")
    return " ".join(parts)


def _acquisition_sentence(r: ShipRecord) -> str:
    if r.not_for_sale:
        return (
            f"The {r.key} is awarded as a story reward and is "
            "not sold at any shipyard."
        )
    if r.shipyard_faction is None:
        return ""
    bits = [f"It sells at {r.shipyard_faction} shipyards"]
    if r.shipyard_level is not None:
        bits.append(f"from shipyard level {r.shipyard_level}")
    if r.shipyard_rep is not None:
        bits.append(f"at {r.shipyard_rep} reputation")
    if r.player_level is not None:
        bits.append(f"requiring player level {r.player_level}")
    if r.conquest_rank is not None:
        bits.append(f"and {r.conquest_rank} conquest rank")
    return ", ".join(bits) + "."


def _variant_sentence(
    r: ShipRecord, all_records: dict[str, ShipRecord]
) -> str:
    if r.key == r.display_name:
        return ""
    canonical = next(
        (
            other for other in all_records.values()
            if other.key == r.display_name
            and other.key != r.key
        ),
        None,
    )
    if canonical is None:
        return ""
    mfr = r.manufacturer or "an alternate vendor"
    return (
        f"The {r.key} is the {mfr}-resold variant of the {canonical.key}."
    )


def spec_sentences(
    record: ShipRecord, all_records: dict[str, ShipRecord]
) -> str:
    """Build a 1-3 paragraph natural-language Spec card body."""
    paragraphs: list[str] = []
    paragraphs.append(_identity_sentence(record))
    combat = _combat_sentence(record)
    if combat:
        paragraphs.append(combat)
    acquisition = _acquisition_sentence(record)
    if acquisition:
        paragraphs.append(acquisition)
    variant = _variant_sentence(record, all_records)
    if variant:
        paragraphs.append(variant)
    return "\n\n".join(paragraphs)
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/test_shipdata.py -v`
Expected: all 19 tests pass.

- [ ] **Step 5: Commit**

```bash
git add shipdata.py tests/test_shipdata.py
git commit -m "feat(shipdata): natural-language spec_sentences builder"
```

---

## Task 5: Resolver registry and Shipbox handlers

**Files:**
- Create: `resolvers.py`
- Create: `tests/test_resolvers.py`

- [ ] **Step 1: Write failing tests**

`tests/test_resolvers.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/test_resolvers.py -v`
Expected: 7 errors importing `resolvers`.

- [ ] **Step 3: Implement the registry and Shipbox handlers**

`resolvers.py`:
```python
"""Registry of {{#invoke:Module|fn|args}} handlers used by the scraper.

Each handler returns wikitext (str) or None. The scraper substitutes the
return value in place of the parser-function call before strip_code runs.
Returning an empty string keeps the surrounding wikitext valid (no stray
brackets) but contributes nothing to the chunk text.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


Handler = Callable[[list[str], Any], Optional[str]]
_REGISTRY: dict[tuple[str, str], Handler] = {}


def register(module: str, fn: str) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        _REGISTRY[(module, fn)] = handler
        return handler

    return decorator


def resolve(
    module: str, fn: str, args: list[str], ctx: Any
) -> Optional[str]:
    handler = _REGISTRY.get((module, fn))
    if handler is None:
        return None
    return handler(args, ctx)


# ---- built-in handlers ----

# Map ShipRecord attribute name -> ShipData field name as referenced from the
# wiki in `{{#invoke:Shipbox|field|<key>|<fieldname>}}`. Kept in lockstep with
# Module:Shipbox's COLUMNS schema; missing names yield empty strings.
_FIELD_LOOKUP = {
    "displayName": "display_name",
    "manufacturer": "manufacturer",
    "class": "ship_class",
    "hullScale": "hull_scale",
    "shieldScale": "shield_scale",
    "armorScale": "armor_scale",
    "hardpoints": "hardpoints",
    "speed": "speed",
    "accel": "accel",
    "crew": "crew",
    "cargo": "cargo",
    "playerLevel": "player_level",
    "shipyardLevel": "shipyard_level",
    "shipyardRep": "shipyard_rep",
    "shipyardFaction": "shipyard_faction",
    "conquestRank": "conquest_rank",
}


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@register("Shipbox", "field")
def _shipbox_field(args: list[str], ctx: Any) -> str:
    if ctx is None or len(args) < 2:
        return ""
    key, field_name = args[0], args[1]
    record = ctx.records.get(key)
    if record is None:
        return ""
    attr = _FIELD_LOOKUP.get(field_name)
    if attr is None:
        return ""
    return _format_value(getattr(record, attr, None))


@register("Shipbox", "infobox")
def _shipbox_infobox(args: list[str], ctx: Any) -> str:
    """Suppressed in article body — facts are emitted as a separate Spec
    card chunk by the scraper, so leaving an inline rendering here would
    duplicate them."""
    return ""
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/test_resolvers.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add resolvers.py tests/test_resolvers.py
git commit -m "feat(resolvers): registry + Shipbox.field/infobox handlers"
```

---

## Task 6: Wire the resolver pass into to_text

**Files:**
- Modify: `scrape.py`
- Create: `tests/test_scrape_integration.py`

- [ ] **Step 1: Write failing integration test**

`tests/test_scrape_integration.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/test_scrape_integration.py -v`
Expected: 2 failures (`to_text` doesn't accept `shipdata=` kwarg, or substitution does nothing).

- [ ] **Step 3: Modify scrape.py to wire in the resolver pass**

In `scrape.py`, modify `to_text` and add a helper. Replace lines 136–145 with:

```python
def resolve_invokes(code: mwparserfromhell.wikicode.Wikicode, shipdata) -> None:
    """Substitute every {{#invoke:Module|fn|args}} call with its handler's
    return value. Calls without a registered handler are removed."""
    import resolvers

    for tpl in list(code.filter_templates(recursive=True)):
        name = str(tpl.name).strip()
        if not name.startswith("#invoke:"):
            continue
        # mwparserfromhell stores `#invoke:Module|fn|args...` as:
        #   tpl.name  = "#invoke:Module"
        #   tpl.params[0] = "fn"
        #   tpl.params[1:] = positional/named args
        module = name.split(":", 1)[1].strip()
        if not tpl.params:
            replacement = ""
        else:
            fn = str(tpl.params[0].value).strip()
            args = [str(p.value).strip() for p in tpl.params[1:]]
            out = resolvers.resolve(module, fn, args, ctx=shipdata)
            replacement = out if out is not None else ""
        try:
            code.replace(tpl, mwparserfromhell.parse(replacement))
        except ValueError:
            # Parent already replaced this invoke (nested case).
            continue


def to_text(wikitext: str, shipdata=None) -> str:
    code = mwparserfromhell.parse(wikitext)
    resolve_invokes(code, shipdata)
    strip_file_links(code)
    render_templates_inline(code)
    text = code.strip_code(normalize=True, collapse=True)
    text = IMAGE_EXT_RE.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/test_scrape_integration.py -v`
Expected: both tests pass.

- [ ] **Step 5: Confirm earlier tests still pass**

Run: `pytest`
Expected: all tests across all files pass.

- [ ] **Step 6: Commit**

```bash
git add scrape.py tests/test_scrape_integration.py
git commit -m "feat(scrape): resolve #invoke calls in to_text via resolver registry"
```

---

## Task 7: Spec-card emission and manifest sentinel

**Files:**
- Modify: `scrape.py`
- Modify: `tests/test_scrape_integration.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_scrape_integration.py`:
```python
import json
from pathlib import Path

import scrape


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
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/test_scrape_integration.py -v -k spec_card or manifest`
Expected: 2 errors (`main_with_args` doesn't exist, no spec cards emitted).

- [ ] **Step 3: Refactor `main` and add Spec-card emission**

In `scrape.py`:

1. Add an import line near the others: `import shipdata as shipdata_mod`.

2. Rename `main` to `main_with_args(argv: list[str] | None = None) -> int` and accept `argv`. Update the bottom of the file:

```python
def main() -> int:
    return main_with_args(None)


if __name__ == "__main__":
    sys.exit(main())
```

3. Replace `args = ap.parse_args()` with `args = ap.parse_args(argv)`.

4. Build `shipdata` once after creating the session:

```python
session = requests.Session()
session.headers["User-Agent"] = USER_AGENT

shipdata_ctx = shipdata_mod.load(session)
```

5. Pass `shipdata=shipdata_ctx` into `to_text` everywhere it is called inside `main_with_args` (the per-section loop).

6. Track the Module:ShipData revid in the manifest. Right after the article-page loop, add:

```python
manifest["__module_shipdata"] = shipdata_ctx.revid
shipdata_changed = prev.get("__module_shipdata") != shipdata_ctx.revid
```

7. After the per-page loop and before the existing `# Incremental merge:` comment, add the Spec-card emission:

```python
for key, record in sorted(shipdata_ctx.records.items()):
    body = shipdata_mod.spec_sentences(record, shipdata_ctx.records)
    if not body:
        continue
    name = f"{key} – Spec"
    chunks = chunk(body, TEXT_CAP)
    for j, c in enumerate(chunks):
        n = name if len(chunks) == 1 else f"{name} ({j + 1}/{len(chunks)})"
        new_rows.append((n[:NAME_CAP], c))
```

8. Update the incremental-merge block to also drop kept Spec rows when ShipData changed:

```python
if prev and not args.full and csv_path.exists():
    kept: list[tuple[str, str]] = []
    changed_titles = {t for t, r in manifest.items()
                      if not t.startswith("__") and prev.get(t) != r}
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["name"].endswith(" – Spec") or " – Spec (" in row["name"]:
                if shipdata_changed:
                    continue
                kept.append((row["name"], row["text"]))
                continue
            page = row["name"].split(" – ", 1)[0]
            if page in changed_titles or page not in manifest:
                continue
            kept.append((row["name"], row["text"]))
    rows = kept + new_rows
else:
    rows = new_rows
```

9. Update the manifest write so the sentinel survives sorting (it already will — `sort_keys=True`).

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/test_scrape_integration.py -v`
Expected: all tests pass.

- [ ] **Step 5: Confirm full suite still passes**

Run: `pytest`
Expected: all tests across files pass.

- [ ] **Step 6: Commit**

```bash
git add scrape.py tests/test_scrape_integration.py
git commit -m "feat(scrape): emit per-ship Spec cards from Module:ShipData"
```

---

## Task 8: --dry-run flag

**Files:**
- Modify: `scrape.py`
- Modify: `tests/test_scrape_integration.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_scrape_integration.py`:
```python
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
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `pytest tests/test_scrape_integration.py::test_dry_run_prints_sample_card_and_writes_nothing -v`
Expected: failure (`--dry-run` is not a known argument).

- [ ] **Step 3: Add the flag and the dry-run branch**

In `scrape.py`:

1. Add the argument near the other `ap.add_argument` calls:

```python
ap.add_argument("--dry-run", action="store_true",
                help="print row count + a sample Spec card and exit")
```

2. Right after the spec-card emission loop, before the incremental merge:

```python
if args.dry_run:
    sample_key = "Cudal" if "Cudal" in shipdata_ctx.records else \
        next(iter(shipdata_ctx.records))
    sample_body = shipdata_mod.spec_sentences(
        shipdata_ctx.records[sample_key], shipdata_ctx.records
    )
    print(f"would write {len(new_rows)} rows")
    print()
    print(f"=== {sample_key} – Spec ===")
    print(sample_body)
    return 0
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `pytest tests/test_scrape_integration.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scrape.py tests/test_scrape_integration.py
git commit -m "feat(scrape): --dry-run prints row count + sample Spec card"
```

---

## Task 9: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Ship Spec cards" subsection under "What it does"**

Insert after the existing numbered list in `README.md` (after step 8 of "What it does"):

```markdown
9. Fetches `Module:ShipData` once per run, parses it, and emits one
   `<Name> – Spec` chunk per ship as natural-language sentences (manufacturer,
   class, hull/shield/armor modifiers, hardpoints, warp speed, crew, cargo,
   shipyard requirements, conquest rank where applicable). The Module's revid
   is tracked under `__module_shipdata` in the manifest so a Module edit
   re-emits every Spec card.
10. Resolves `{{#invoke:Shipbox|field|...}}` and `{{#invoke:Shipbox|infobox|...}}`
    parser-function calls in article wikitext using a small registry
    (`resolvers.py`). Future modules (e.g. `Module:ItemData`) plug in by
    registering a handler — no scraper changes.
```

- [ ] **Step 2: Document the --dry-run flag under Usage**

Append to the source-usage block:
```bash
python scrape.py --dry-run        # print row count + a sample Spec card and exit
```

- [ ] **Step 3: Document dev setup**

Add a new section before "Targeting a different wiki":

```markdown
## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Tests run offline against captured fixtures in `tests/fixtures/`. No network
calls during test runs.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: cover Spec cards, resolver registry, and --dry-run"
```

---

## Manual verification (post-merge)

This is not part of the TDD task list — run after merging to confirm the live wiki produces sane output.

- Run `python scrape.py --dry-run --full --sleep 0.05`
- Confirm the printed sample Spec card has manufacturer, class, hardpoints, and shipyard line filled.
- Run `python scrape.py --full --sleep 0.05` and `grep '"Hurricane – Spec"' out/vg_wiki.json | head` — confirm the chunk exists with resolved facts.
- Run `python scrape.py` again immediately — confirm 0 changed pages (cache hit) and a `__module_shipdata` entry in the manifest.

## Self-review

- **Spec coverage:** identity / combat / acquisition / variant sentences (Task 4); resolver registry + Shipbox handlers (Task 5); resolver wired into to_text (Task 6); Spec-card emission + manifest sentinel (Task 7); `--dry-run` (Task 8); README delta (Task 9). All design sections covered.
- **Placeholder scan:** every step has concrete code. No "TODO" / "TBD" / "implement appropriately".
- **Type consistency:** `ShipRecord` attribute names (`hull_scale`, `ship_class`, `not_for_sale`) used identically in tests, builder, and resolvers `_FIELD_LOOKUP`. `ShipData(records, revid)` shape stable across `load`, `_shipbox_field`, and main.
- **Manifest sentinel:** `__module_shipdata` is treated as non-page in the incremental-merge `changed_titles` set (`not t.startswith("__")`), and Spec rows are detected by ` – Spec` suffix in name.
