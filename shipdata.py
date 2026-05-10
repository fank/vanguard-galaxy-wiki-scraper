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
