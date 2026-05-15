#!/usr/bin/env python3
"""
Scrape vanguard-galaxy.fandom.com → CSV for vrt-cogs Assistant RAG ingest.

  python -m venv .venv && . .venv/bin/activate
  pip install -r requirements.txt
  python scrape.py                 # incremental (skips unchanged pages)
  python scrape.py --full          # ignore manifest, re-emit everything

Outputs:
  out/vg_wiki.csv             — name,text columns, ready for `?assistant importcsv true`
  out/vg_wiki.manifest.json   — title → revid, used to skip unchanged pages next run

Schema target: vrt-cogs assistant cog
  https://github.com/vertyco/vrt-cogs/blob/main/assistant/commands/admin.py
  Columns are exactly ['name', 'text']; text is truncated to 4000 chars per row,
  name to 100. We chunk per ==H2== section so retrieval has section-grained context.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

import mwparserfromhell
import requests
import aspectdata as aspectdata_mod
import shipdata as shipdata_mod

API_URL = "https://vanguard-galaxy.fandom.com/api.php"
USER_AGENT = (
    "Fankserver-VGWikiScraper/0.1 "
    "(+https://vanguard-galaxy.fandom.com/wiki/User:Fankserver)"
)
TEXT_CAP = 4000  # vrt-cogs assistant truncates text at 4000 chars
NAME_CAP = 100   # and names at 100


def api(session: requests.Session, **params) -> dict:
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")
    r = session.get(API_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def list_articles(session: requests.Session):
    """Yield (title, pageid) for every non-redirect page in namespace 0."""
    cont: dict = {}
    while True:
        params = dict(
            action="query", list="allpages",
            aplimit=500, apnamespace=0, apfilterredir="nonredirects",
        )
        params.update(cont)
        data = api(session, **params)
        for p in data["query"]["allpages"]:
            yield p["title"], p["pageid"]
        if "continue" not in data:
            return
        cont = data["continue"]


def parse_page(session: requests.Session, title: str):
    data = api(session, action="parse", page=title, prop="wikitext|revid")
    p = data.get("parse")
    if not p:
        return None, None
    return p.get("revid"), p.get("wikitext", "")


SECTION_RE = re.compile(r"^==\s*([^=].*?)\s*==\s*$", re.MULTILINE)

IMAGE_EXT_RE = re.compile(r"\S*\.(?:png|jpe?g|gif|svg|webp)\b", re.IGNORECASE)
IMAGE_PARAM_NAMES = {
    "image", "img", "icon", "logo", "screenshot", "thumb", "thumbnail",
    "picture", "portrait", "pic", "file",
}


def split_sections(wikitext: str, page_title: str):
    """Yield (entry_name, body_wikitext). Lead before first H2 → 'Overview'."""
    matches = list(SECTION_RE.finditer(wikitext))
    if not matches:
        yield page_title, wikitext
        return
    lead = wikitext[: matches[0].start()].strip()
    if lead:
        yield f"{page_title} – Overview", lead
    for i, m in enumerate(matches):
        sec_title = mwparserfromhell.parse(m.group(1).strip()).strip_code().strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(wikitext)
        body = wikitext[m.end():end].strip()
        if body:
            yield f"{page_title} – {sec_title}", body


def render_templates_inline(code: mwparserfromhell.wikicode.Wikicode) -> None:
    """Replace each template with `param: value` lines so infobox data survives strip_code.
    Drops image-ish params (image=foo.png) — those are noise for an LLM RAG store."""
    for tpl in list(code.filter_templates(recursive=True)):
        try:
            lines = []
            for param in tpl.params:
                name = str(param.name).strip()
                value = str(param.value).strip()
                if not value:
                    continue
                if name.lower() in IMAGE_PARAM_NAMES:
                    continue
                if IMAGE_EXT_RE.fullmatch(value):
                    continue
                lines.append(f"{name}: {value}")
            replacement = "\n".join(lines)
            code.replace(tpl, replacement)
        except ValueError:
            # parent already replaced this template (nested case)
            continue


def strip_file_links(code: mwparserfromhell.wikicode.Wikicode) -> None:
    """Remove [[File:foo.png|thumb|caption]] / [[Image:...]] wikilinks entirely.
    Captions are usually redundant with surrounding prose; safer to drop than to risk
    surfacing a filename like 'arle.png' as a 'caption'."""
    for link in list(code.filter_wikilinks()):
        title = str(link.title).strip()
        if title.lower().startswith(("file:", "image:")):
            try:
                code.remove(link)
            except ValueError:
                continue


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
    # Final sweep: any bare filename survivors (raw gallery cells, etc.)
    text = IMAGE_EXT_RE.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk(text: str, cap: int) -> list[str]:
    if len(text) <= cap:
        return [text]
    parts: list[str] = []
    cur = ""
    for para in re.split(r"\n\n+", text):
        if cur and len(cur) + len(para) + 2 > cap:
            parts.append(cur.strip())
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur.strip())
    out: list[str] = []
    for p in parts:
        if len(p) <= cap:
            out.append(p)
            continue
        for i in range(0, len(p), cap):
            out.append(p[i:i + cap])
    return out


def _is_shipdata_derived(row_name: str) -> bool:
    """True for any chunk built from Module:ShipData. Re-emitted whenever the
    Module's revid changes; preserved otherwise."""
    return (
        row_name.endswith(" – Spec")
        or " – Spec (" in row_name
        or row_name.startswith("Ship rankings – ")
        or row_name == "Ship roster"
        or row_name.startswith("Ship roster (")
    )


def _is_aspectdata_derived(row_name: str) -> bool:
    """True for any chunk built from Module:AspectData. Re-emitted whenever
    the Module's revid changes; preserved otherwise."""
    return (
        row_name.endswith(" – Aspect")
        or " – Aspect (" in row_name
        or row_name == "Aspect roster"
        or row_name.startswith("Aspect roster (")
        or row_name.startswith("Aspects in ")
        or row_name == "Common aspects"
        or row_name.startswith("Common aspects (")
        or row_name == "Rare aspects"
        or row_name.startswith("Rare aspects (")
        or row_name.startswith("Aspects boosting ")
    )


def main_with_args(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--out", default="out", help="output dir (default: ./out)")
    ap.add_argument("--full", action="store_true",
                    help="ignore manifest, re-emit every page")
    ap.add_argument("--sleep", type=float, default=0.1,
                    help="seconds between API calls (default: 0.1)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print row count + a sample Spec card and exit")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "vg_wiki.csv"
    json_path = out_dir / "vg_wiki.json"
    manifest_path = out_dir / "vg_wiki.manifest.json"

    prev: dict[str, int] = {}
    if manifest_path.exists() and not args.full:
        prev = json.loads(manifest_path.read_text())

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    shipdata_ctx = shipdata_mod.load(session)
    aspectdata_ctx = aspectdata_mod.load(session)

    titles = list(list_articles(session))
    print(f"Found {len(titles)} articles", file=sys.stderr)

    new_rows: list[tuple[str, str]] = []
    manifest: dict[str, int] = {}
    changed = 0
    skipped = 0

    for i, (title, _pageid) in enumerate(titles, 1):
        time.sleep(args.sleep)
        try:
            revid, wikitext = parse_page(session, title)
        except Exception as e:
            print(f"[{i:>3}/{len(titles)}] ERR  {title}: {e}", file=sys.stderr)
            continue
        if revid is None:
            print(f"[{i:>3}/{len(titles)}] SKIP {title} (no parse)", file=sys.stderr)
            continue
        manifest[title] = revid
        if prev.get(title) == revid:
            skipped += 1
            continue
        changed += 1
        for sec_name, sec_body in split_sections(wikitext, title):
            text = to_text(sec_body, shipdata=shipdata_ctx)
            if not text:
                continue
            chunks = chunk(text, TEXT_CAP)
            for j, c in enumerate(chunks):
                name = sec_name if len(chunks) == 1 else f"{sec_name} ({j + 1}/{len(chunks)})"
                new_rows.append((name[:NAME_CAP], c))
        print(f"[{i:>3}/{len(titles)}] {title} (rev {revid})", file=sys.stderr)

    manifest["__module_shipdata"] = shipdata_ctx.revid
    shipdata_changed = prev.get("__module_shipdata") != shipdata_ctx.revid

    for key, record in sorted(shipdata_ctx.records.items()):
        body = shipdata_mod.spec_sentences(record, shipdata_ctx.records)
        if not body:
            continue
        name = f"{key} – Spec"
        chunks = chunk(body, TEXT_CAP)
        for j, c in enumerate(chunks):
            n = name if len(chunks) == 1 else f"{name} ({j + 1}/{len(chunks)})"
            new_rows.append((n[:NAME_CAP], c))

    for ranking_name, ranking_body in shipdata_mod.ranking_chunks(shipdata_ctx.records):
        chunks = chunk(ranking_body, TEXT_CAP)
        for j, c in enumerate(chunks):
            n = ranking_name if len(chunks) == 1 else f"{ranking_name} ({j + 1}/{len(chunks)})"
            new_rows.append((n[:NAME_CAP], c))

    roster = shipdata_mod.class_roster_chunk(shipdata_ctx.records)
    if roster is not None:
        roster_name, roster_body = roster
        chunks = chunk(roster_body, TEXT_CAP)
        for j, c in enumerate(chunks):
            n = roster_name if len(chunks) == 1 else f"{roster_name} ({j + 1}/{len(chunks)})"
            new_rows.append((n[:NAME_CAP], c))

    manifest["__module_aspectdata"] = aspectdata_ctx.revid
    aspectdata_changed = prev.get("__module_aspectdata") != aspectdata_ctx.revid

    for key, record in sorted(aspectdata_ctx.records.items()):
        if not record.has_image:
            # Mirrors Module:Aspectbox's filter — placeholder/internal entries
            # never reach the rendered wiki, so they shouldn't reach RAG either.
            continue
        body = aspectdata_mod.aspect_sentences(record)
        if not body:
            continue
        name = f"{record.display_name} – Aspect"
        chunks = chunk(body, TEXT_CAP)
        for j, c in enumerate(chunks):
            n = name if len(chunks) == 1 else f"{name} ({j + 1}/{len(chunks)})"
            new_rows.append((n[:NAME_CAP], c))

    aspect_roster = aspectdata_mod.slot_roster_chunk(aspectdata_ctx.records)
    if aspect_roster is not None:
        ar_name, ar_body = aspect_roster
        chunks = chunk(ar_body, TEXT_CAP)
        for j, c in enumerate(chunks):
            n = ar_name if len(chunks) == 1 else f"{ar_name} ({j + 1}/{len(chunks)})"
            new_rows.append((n[:NAME_CAP], c))

    for aggregate_name, aggregate_body in (
        list(aspectdata_mod.per_slot_chunks(aspectdata_ctx.records))
        + list(aspectdata_mod.per_rarity_chunks(aspectdata_ctx.records))
        + list(aspectdata_mod.per_effect_chunks(aspectdata_ctx.records))
    ):
        chunks = chunk(aggregate_body, TEXT_CAP)
        for j, c in enumerate(chunks):
            n = aggregate_name if len(chunks) == 1 else f"{aggregate_name} ({j + 1}/{len(chunks)})"
            new_rows.append((n[:NAME_CAP], c))

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

    # Incremental merge: keep prior rows for unchanged pages, replace rows for changed pages.
    if prev and not args.full and csv_path.exists():
        kept: list[tuple[str, str]] = []
        changed_titles = {t for t, r in manifest.items()
                          if not t.startswith("__") and prev.get(t) != r}
        with csv_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if _is_shipdata_derived(row["name"]):
                    if shipdata_changed:
                        continue
                    kept.append((row["name"], row["text"]))
                    continue
                if _is_aspectdata_derived(row["name"]):
                    if aspectdata_changed:
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

    # Stable order makes diffs reviewable.
    rows.sort(key=lambda r: r[0])

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "text"])
        w.writerows(rows)

    # JSON output matches vrt-cogs `?assistant importjson` schema exactly:
    #   { "<name>": { "text": "..." }, ... }
    # `embedding` and `model` keys are omitted so the cog re-embeds with whatever
    # embed model he has configured (local or OpenAI).
    json_payload = {name: {"text": text} for name, text in rows}
    json_path.write_text(
        json.dumps(json_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(
        f"\nWrote {len(rows)} rows to {csv_path} and {json_path}\n"
        f"Pages: {changed} changed, {skipped} unchanged, {len(titles) - changed - skipped} errored",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    return main_with_args(None)


if __name__ == "__main__":
    sys.exit(main())
