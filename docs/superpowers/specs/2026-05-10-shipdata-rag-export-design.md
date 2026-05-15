# Ship-data RAG export — design

**Date:** 2026-05-10
**Component:** `wiki-scraper/`
**Goal:** Make ship facts and lore retrievable through the vrt-cogs Assistant
RAG cog. Build the scaffolding so items and modules can plug in later without
re-architecting the scraper.

## Problem

Per-ship article pages (`Cudal`, `Hurricane`, `Eclipse`, …) now consist of:

- One `{{#invoke:Shipbox|infobox|<Name>}}` call (the entire stat block).
- A short narrative line, e.g.
  `The '''Hurricane''' is an [[{{#invoke:Shipbox|field|Hurricane|manufacturer}}]] destroyer sold at [[Akai Armory]] shipyards.`
- Optional `== Acquisition ==` lore (story-reward ships).
- Optional `== Notes ==` callouts using the same `field` invoke pattern for
  class-leading numbers (`{{#invoke:Shipbox|field|Anotan|speed}} ls/s`).

`mwparserfromhell.strip_code` cannot expand parser-function `#invoke` calls.
The current scraper therefore emits chunks like:

> The Hurricane is an  destroyer sold at  shipyards.
> Fastest dredger —  ls/s warp speed with  ls/s² acceleration, both class-leading.

The structured ship facts live in `Module:ShipData` (namespace 828), which the
scraper does not enumerate. The bulk `Ship List – Large Ships` chunks contain
the data but as undifferentiated tabular walls — query-hostile.

Items and modules will move to the same author-via-Lua-module pattern soon, so
a one-off ship fix is the wrong shape.

## Architecture

Two new files in `wiki-scraper/`:

### `resolvers.py` — `#invoke` resolver registry

A registry keyed by `(module_name, function_name)` that maps each known parser
function to a callable returning replacement wikitext. Built-in handlers:

| Key | Handler | Returns |
|---|---|---|
| `("Shipbox", "field")` | `shipbox_field(ship_key, field_name)` | The literal field value (`Akai Armory`). |
| `("Shipbox", "infobox")` | `shipbox_infobox(ship_key)` | Empty string — facts are emitted as a separate Spec card chunk; suppressing here avoids duplication on the article page. |

Unhandled invokes are dropped silently (current behavior). The substitution
pass runs before `to_text` so resolved values flow through the existing
`strip_code` / cleanup pipeline. Wikilinks remain intact:
`[[{{#invoke:Shipbox|field|Hurricane|manufacturer}}]]` →
`[[Akai Armory]]` → plain `Akai Armory` after strip_code.

Adding a new module later is a registry entry plus a handler; no changes in
`scrape.py`.

### `shipdata.py` — Module:ShipData accessor + spec-card builder

- `load(session) -> dict[str, ShipRecord]` — fetches `Module:ShipData` via
  `api.php?action=parse&page=Module:ShipData&prop=wikitext|revid`, parses the
  Lua table (lifting `ENTRY_RE` / `FIELD_RE` from
  `dataexport/tools/merge_shipdata.py`), returns one `ShipRecord` per ship key.
  Cached for the lifetime of the scraper run.
- `spec_sentences(record) -> str` — builds the natural-language Spec card body
  (see "Spec card content" below).
- `revid()` — exposes the Module's revid for manifest tracking.

`ShipRecord` is a thin dataclass over the Lua fields the scraper actually
needs: `displayName`, `manufacturer`, `class`, `hullScale`, `shieldScale`,
`armorScale`, `hardpoints`, `speed`, `accel`, `crew`, `cargo`, `playerLevel`,
`shipyardLevel`, `shipyardRep`, `shipyardFaction`, `conquestRank`,
`notForSale`. Missing fields are tolerated — every sentence guards on
presence so partial records don't crash the run.

### `scrape.py` integration

Two additions to the existing pipeline:

1. **Resolver pass** — inside `to_text`, before `render_templates_inline`,
   walk the wikicode for parser-function nodes (`code.filter_templates`
   includes them; identify by leading `#invoke:`), look up the handler, and
   replace with the returned wikitext as a `Wikicode` node. The
   replacement is parsed via `mwparserfromhell.parse(...)` so that any
   wikilinks or formatting it contains (e.g. `[[Akai Armory]]`) flow
   through the rest of the pipeline normally.
2. **Spec-card emission pass** — after the article enumeration loop, iterate
   `shipdata.load(session)`. For each ship key, build the Spec card body via
   `shipdata.spec_sentences(record)` and append a row
   `(f"{displayName} – Spec", body)` to `new_rows`. Variant keys
   (`Cudal-Marade` ≠ `Cudal`) get distinct Spec cards.

## Spec card content

**Naming:** `<displayName> – Spec`. For variants where the key differs from
the displayName (`Cudal-Marade` keyed entry, displayName `Cudal`), the Spec
card uses the *key* to keep a unique chunk name and matches the existing
manufacturer-tabber link convention.

**Body shape:** 1–3 short paragraphs of natural-language sentences, each
focused on one concern so retrieval stays well-targeted.

1. **Identity & role** *(always present)* — manufacturer, class
   (Cutter / Destroyer / Hewer / …), and one-line role inferred from class
   (combat, mining, salvage, cargo). Sentence:
   > The Hurricane is an Akai Armory destroyer, a combat hull.

2. **Combat profile** *(always present)* — hull / shield / armor modifiers
   in `×` form, hardpoint layout in compact notation, warp speed and
   acceleration, cargo and crew capacity. Sentence form keeps each stat
   labelled so an LLM can quote a specific number back:
   > Its hull modifier is 14.7×, shield 12.3×, armor 11.4×. It carries 1
   > large, 2 medium, and 2 small hardpoints, warps at 4420 ls/s with class-
   > standard acceleration, has 5 crew slots and 1080 cargo units.

3. **Acquisition** *(branched)* — three cases:
   - **Shipyard purchase**:
     > It sells at Akai Armory shipyards from shipyard level 40+ at Respected
     > reputation, requiring player level 45.
   - **Conquest hull** (entry has `conquestRank`):
     > Above adds: "…and Associate conquest rank."
   - **Story reward** (`notForSale=true`):
     > The Eclipse is awarded as a story reward and is not sold at any
     > shipyard.
   - **Variant** (Lua key differs from `displayName`, indicating an
     alternate-vendor or alternate-loadout reskin of another hull):
     > The Cudal-Marade is the Marade Wharf-resold variant of the Cudal.

     Detection is data-driven: if `record.key != record.displayName` and
     the canonical hull's `displayName` exists as another `ShipData` entry,
     emit the variant sentence pointing at the canonical entry's
     `manufacturer`. No hardcoded suffix list.

All numbers and faction names come from the live `ShipData` record — never
hardcoded.

## Output

**New chunks per run:** ~90 (one per `Module:ShipData` key). At 400–800 chars
each, roughly +50 KB on `vg_wiki.json`.

**Existing chunks affected:**
- Article-page chunks (`Cudal – Overview`, `Eclipse – Acquisition`,
  `Anotan – Notes`) keep their names but now contain resolved values instead
  of empty placeholders. The Notes class-leading callouts get their numbers.
- `Ship List – *` chunks remain untouched. Redundant once Spec cards exist,
  but harmless — RAG will score per-ship Spec cards higher for ship-specific
  queries while the bulk list still serves "which ships are destroyers?"
  pattern queries.

**Manifest:** `vg_wiki.manifest.json` gains one sentinel entry:

```json
{ "__module_shipdata": <revid>, ... }
```

If `Module:ShipData`'s revid changes between runs, every `<Name> – Spec`
chunk is re-emitted regardless of article-page revids. Article-page
incremental behavior is unchanged.

## Future extensibility

Items and modules follow the same pattern by registering against the same
scaffolding:

| Future module | Registry entries | Spec builder |
|---|---|---|
| `Module:ItemData` | `(Itembox, field)`, `(Itembox, infobox)` | `itemdata.spec_sentences(record)` |
| `Module:ModuleData` | `(Modulebox, field)`, `(Modulebox, infobox)` | `moduledata.spec_sentences(record)` |

`scrape.py` learns the new module by adding one import + one entry in the
post-enumeration spec-emission loop. Nothing else changes.

## Testing

- Resolver pass: a unit test against a captured Cudal page wikitext confirms
  the substituted text contains "Frontier" (manufacturer) where the
  unsubstituted text does not.
- Spec card builder: dataclass→sentences mapping is pure; one
  parametrized test per acquisition branch (shipyard, conquest, story
  reward, variant) covers the prose paths.
- End-to-end: a `--dry-run` mode that prints the row count + a sample Spec
  card for `Hurricane` without writing to disk, used to spot-check before
  committing changes.

## Out of scope

- HTML rendering pipeline (Approach 2 in brainstorming) — rejected because
  it invasively reworks every page for a problem localized to `#invoke`.
- Demoting or rebuilding `Ship List – *` chunks — leave for a later pass once
  Spec cards prove themselves in retrieval.
- Embedding-model tuning advice — already covered in the wiki-scraper README.
