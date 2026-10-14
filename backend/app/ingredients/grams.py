"""
Convert a parsed amount into grams of a specific USDA food.

Mass units convert directly. Volumes and counts use the food's own USDA
portion weights ("1 cup, chopped = 67 g"; "1 large = 50 g"), picking the
portion whose wording best fits the recipe ("chopped" vs "sliced").
"""

import re
from dataclasses import dataclass, field

from app.ingredients.parse import NUMBER, ParsedLine, to_number
from app.ingredients.units import MASS_G, STICK_GRAMS, VOLUME_TSP, canonical_unit

ML_PER_TSP = 4.92892


@dataclass
class Portion:
    description: str
    gram_weight: float


@dataclass
class PortionUnit:
    amount: float
    unit: str | None
    modifier: str
    grams: float


@dataclass
class GramResult:
    grams: float | None
    method: str
    warnings: list[str] = field(default_factory=list)


def read_portion(portion: Portion) -> PortionUnit:
    """'1 cup, chopped' -> amount 1, unit 'cup', modifier 'chopped'."""
    text = portion.description.lower().replace('"', " in ")
    m = re.match(rf"\s*({NUMBER})\s+(.*)", text)
    amount = to_number(m.group(1)) if m else 1.0
    rest = m.group(2) if m else text
    words = rest.replace(",", " ").split()
    unit = None
    if len(words) > 1 and canonical_unit(" ".join(words[:2])) == "fl oz":
        unit, words = "fl oz", words[2:]
    elif words and canonical_unit(words[0]):
        unit, words = canonical_unit(words[0]), words[1:]
    elif len(words) > 1 and canonical_unit(words[1]):  # "1 Potato medium (2-1/4" dia)"
        unit, words = canonical_unit(words[1]), words[2:]
    return PortionUnit(amount=amount or 1.0, unit=unit, modifier=" ".join(words),
                       grams=portion.gram_weight)


def _best(options: list[PortionUnit], note: str) -> PortionUnit:
    """Prefer the portion whose modifier shares words with the recipe line."""
    note_words = set(re.findall(r"[a-z]+", note.lower()))

    def overlap(p: PortionUnit) -> int:
        return len(note_words & set(re.findall(r"[a-z]+", p.modifier)))

    return max(options, key=lambda p: (overlap(p), -len(p.modifier)))


def to_grams(parsed: ParsedLine, portions: list[Portion]) -> GramResult:
    if parsed.quantity is None:
        return GramResult(None, "no amount", ["amount not given; not counted"])

    q, unit = parsed.quantity, parsed.unit
    units = [read_portion(p) for p in portions if p.gram_weight > 0]

    if unit in MASS_G:
        return GramResult(q * MASS_G[unit], f"{unit} to grams")

    if unit == "can" and parsed.package_grams:
        return GramResult(q * parsed.package_grams, "package size on the label")

    if unit == "stick":
        return GramResult(q * STICK_GRAMS, "standard stick = 113 g")

    if unit in VOLUME_TSP:
        volume = [u for u in units if u.unit in VOLUME_TSP]
        # A "dash" or "pinch" portion is too rough to scale from when a real
        # measure exists.
        measured = [u for u in volume if u.unit not in {"dash", "pinch"}]
        volume = measured or volume
        if volume:
            p = _best(volume, f"{parsed.note} {parsed.original}")
            grams_per_tsp = p.grams / (p.amount * VOLUME_TSP[p.unit])
            return GramResult(q * VOLUME_TSP[unit] * grams_per_tsp,
                              f"USDA portion '{p.amount:g} {p.unit} {p.modifier}'".strip())
        return GramResult(q * VOLUME_TSP[unit] * ML_PER_TSP, "assumed density of water",
                          ["no USDA volume portion for this food; estimated"])

    # Counted items: match the size or count word, else fall back sensibly.
    if unit is not None:
        same = [u for u in units if u.unit == unit]
        if same:
            p = _best(same, f"{parsed.note} {parsed.original}")
            return GramResult(q * p.grams / p.amount, f"USDA portion '1 {unit}'")
    for preferred in ("medium", "piece", "large", "small"):
        same = [u for u in units if u.unit == preferred]
        if same:
            p = same[0]
            warnings = [] if unit is None else [f"no '{unit}' portion; used '{preferred}'"]
            return GramResult(q * p.grams / p.amount, f"USDA portion '1 {preferred}'",
                              warnings)
    countable = [u for u in units if u.unit not in VOLUME_TSP and u.unit not in MASS_G]
    if countable:
        p = countable[0]
        return GramResult(q * p.grams / p.amount, f"USDA portion '{p.amount:g} "
                          f"{p.unit or ''} {p.modifier}'".replace("  ", " ").strip(),
                          ["no matching size; used the food's first counted portion"])
    return GramResult(None, "no usable portion", ["couldn't convert this amount to grams"])
