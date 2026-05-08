# vanguard-galaxy-wiki-scraper

Section-grained scraper for [vanguard-galaxy.fandom.com](https://vanguard-galaxy.fandom.com/), built to feed the [vrt-cogs Assistant cog](https://github.com/vertyco/vrt-cogs/tree/main/assistant) (a Discord RAG bot framework). Outputs CSV and JSON in the exact shape the cog's `?assistant importcsv` / `?assistant importjson` commands expect.

Uses the public MediaWiki API (`api.php`) — no scraping, no Cloudflare workarounds, no bot password required for reads.

## What it does

1. Enumerates every non-redirect article in namespace 0 (~115 articles for this wiki).
2. Fetches each page's wikitext + `revid` via `action=parse`.
3. Splits each page on `==H2==` headings so the lead and each top-level section become their own retrieval entry — RAG works better when chunks are concept-sized, not page-sized.
4. Renders templates as `key: value` lines (so infobox data — faction, location, role — survives) while dropping image-only fields (`image: foo.png`).
5. Strips `[[File:…]]` / `[[Image:…]]` wikilinks and any residual `*.png|jpg|gif|svg|webp` tokens.
6. Flattens to plaintext via `mwparserfromhell.strip_code`, normalises whitespace.
7. Splits sections longer than 4000 chars (vrt-cogs' per-entry cap) at paragraph boundaries.
8. Writes a `revid` manifest so subsequent runs only re-emit pages that actually changed.

## Install

```bash
git clone https://github.com/fank/vanguard-galaxy-wiki-scraper.git
cd vanguard-galaxy-wiki-scraper
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python scrape.py                 # incremental — skips pages whose revid hasn't changed
python scrape.py --full          # ignore manifest, re-emit everything
python scrape.py --sleep 0.05    # tighter API spacing (default 0.1s)
python scrape.py --out path      # custom output directory (default ./out)
```

First run takes ~30s for the full wiki. Subsequent runs touch only changed pages.

## Output

```
out/
├── vg_wiki.csv             # name,text columns — for `?assistant importcsv true`
├── vg_wiki.json            # {name: {text}} — for `?assistant importjson true`
└── vg_wiki.manifest.json   # title → revid, drives incremental runs
```

Entry naming is stable: `<Page Title> – <Section Title>`, with lead paragraphs as `<Page Title> – Overview`. Long sections split into `<name> (1/N)`, `<name> (2/N)`. Stable names mean re-imports cleanly overwrite prior entries — no duplicates, no orphaned chunks.

JSON shape matches the cog's importer exactly:

```json
{
  "Damage – Damage calculation": { "text": "Outgoing damage is computed in three stages..." },
  "Damage – Practical implications": { "text": "Roughly, every 5 points of CombatPower..." }
}
```

The `embedding` and `model` keys are deliberately omitted so the bot re-embeds with whatever model it has configured (local Ollama, OpenAI, etc.).

## Discord ingest flow

```
?assistant importjson true       # true = overwrite existing entries with same names
```

Daily refresh:

```bash
# cron entry
0 4 * * * cd /path/to/wiki-scraper && .venv/bin/python scrape.py
```

Then drop the regenerated `out/vg_wiki.json` in Discord and re-run `?assistant importjson true`. The cog only re-embeds entries whose `text` actually changed, so the local embed model isn't doing 342 × 768-dim work every day.

## Tuning the bot side

For local embedding models (e.g. `embeddinggemma`, `nomic-embed-text`) cosine scores run systematically lower than OpenAI's. Defaults will reject every match. Calibrate after first import:

```
?query stacking penalty          # see actual top-N scores for this embed model
?assistant minrelatedness 0.30   # set just below the lowest "good" hit
?assistant topn 5                # widens the funnel
```

The bot's system prompt also needs to explicitly instruct grounding on the injected context — character-roleplay prompts otherwise dominate and the LLM will say "I don't have the lore loaded" even when context is present.

## Targeting a different wiki

Single-wiki tool today — `API_URL` is hardcoded at the top of `scrape.py`. Pointing it at any other Fandom wiki only needs that constant changed (and possibly the `USER_AGENT` for politeness). The MediaWiki API surface is identical across Fandom.

## Acknowledgements

Built thanks to the work of the Vanguard Galaxy Wiki maintainers. This tool consumes the wiki — it doesn't replace authoring it. If you find this useful, contribute back to the wiki.
