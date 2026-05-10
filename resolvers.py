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
    "shipyardFactions": "shipyard_factions",
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
