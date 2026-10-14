"""
Parse one recipe line into amount, unit and food words.

    "1 ½ cups finely chopped kale, stems removed"
    -> ParsedLine(quantity=1.5, unit="cup", food="kale", note="finely chopped; stems removed")
"""

import re
from dataclasses import dataclass, field

from app.ingredients.units import MASS_G, canonical_unit

UNICODE_FRACTIONS = {
    "½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75, "⅕": 0.2, "⅖": 0.4,
    "⅗": 0.6, "⅘": 0.8, "⅙": 1 / 6, "⅚": 5 / 6, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625,
    "⅞": 0.875,
}

NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
                "half": 0.5, "dozen": 12}

# Words that describe preparation, not the food itself. "ground" is deliberately
# absent: ground beef and beef are different foods.
PREP_WORDS = {
    "chopped", "diced", "minced", "sliced", "thinly", "thickly", "finely", "roughly",
    "coarsely", "grated", "shredded", "peeled", "crushed", "packed", "lightly", "firmly",
    "softened", "melted", "cubed", "halved", "quartered", "trimmed", "rinsed", "drained",
    "divided", "optional", "freshly", "about", "approximately", "heaping",
    "level", "scant", "julienned", "torn", "beaten", "whisked", "sifted", "cold", "warm",
    "hot", "room", "temperature", "plus", "more", "for", "serving", "garnish", "of",
    "cut", "into", "pieces", "bite-size", "bite-sized", "stemmed", "seeded", "pitted",
    "deveined", "zested", "juiced",
}

# Size words that stay part of the food when no other unit was given ("2 large eggs"
# keeps unit "large"); otherwise they're dropped from the food words.
SIZE_UNITS = {"large", "medium", "small"}

FRACTION_CHARS = "½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞"
NUMBER = (
    rf"(?:\d+\s*[{FRACTION_CHARS}]|\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?"
    rf"|[{FRACTION_CHARS}])"
)
RANGE = rf"{NUMBER}(?:\s*(?:-|–|to)\s*{NUMBER})?"


@dataclass
class ParsedLine:
    original: str
    quantity: float | None
    unit: str | None
    food: str
    note: str = ""
    # Package size from "1 (15 oz) can": grams per one package.
    package_grams: float | None = None
    warnings: list[str] = field(default_factory=list)


def to_number(text: str) -> float:
    text = text.strip()
    for symbol, value in UNICODE_FRACTIONS.items():
        if symbol in text:
            whole = text.replace(symbol, "").strip()
            return (float(whole) if whole else 0.0) + value
    if " " in text:  # mixed number "1 1/2"
        whole, frac = text.split(None, 1)
        return float(whole) + to_number(frac)
    if "/" in text:
        num, den = text.split("/")
        return float(num) / float(den)
    return float(text)


def _parse_quantity(text: str) -> float:
    parts = re.split(r"\s*(?:-|–|\bto\b)\s*", text)
    values = [to_number(p) for p in parts if p.strip()]
    return sum(values) / len(values)  # a range "2-3" becomes its midpoint


def _package_grams(inner: str) -> float | None:
    """'15 oz', '15-ounce', '400 g' -> grams; volumes or unknown units -> None."""
    m = re.match(rf"\s*({NUMBER})\s*-?\s*([a-zA-Z. ]+)", inner)
    if not m:
        return None
    unit = canonical_unit(m.group(2).strip())
    if unit in MASS_G:
        return to_number(m.group(1)) * MASS_G[unit]
    return None


def parse_line(line: str) -> ParsedLine:
    original = line
    text = " ".join(line.replace("⁄", "/").split())  # fraction slash, odd spacing
    warnings: list[str] = []

    # Notes after the first comma ("onion, diced") and in trailing parentheses.
    note_parts = []
    package_grams = None
    for inner in re.findall(r"\(([^)]*)\)", text):
        grams = _package_grams(inner)
        if grams is not None and package_grams is None:
            package_grams = grams
        else:
            note_parts.append(inner.strip())
    text = re.sub(r"\([^)]*\)", " ", text)
    if "," in text:
        text, rest = text.split(",", 1)
        note_parts.append(rest.strip())
    if re.search(r"\bto taste\b", text, re.IGNORECASE):
        note_parts.append("to taste")
        text = re.sub(r"\bto taste\b", " ", text, flags=re.IGNORECASE)

    tokens = text.split()
    quantity = None
    unit = None

    # Leading quantity: digits, unicode fractions, ranges, or number words.
    m = re.match(rf"\s*({RANGE})\b\s*", text)
    if m:
        quantity = _parse_quantity(m.group(1))
        tokens = text[m.end():].split()
    elif tokens and tokens[0].lower() in NUMBER_WORDS:
        quantity = float(NUMBER_WORDS[tokens[0].lower()])
        tokens = tokens[1:]
        if tokens and tokens[0].lower() == "half":  # "a half cup"
            quantity *= 0.5
            tokens = tokens[1:]

    # Unit: one or two words ("fl oz"), with "T" = tablespoon and "t" = teaspoon.
    if tokens:
        two = " ".join(tokens[:2])
        if len(tokens) > 1 and canonical_unit(two) == "fl oz":
            unit, tokens = "fl oz", tokens[2:]
        elif tokens[0] == "T":
            unit, tokens = "tbsp", tokens[1:]
        elif tokens[0] == "t":
            unit, tokens = "tsp", tokens[1:]
        elif canonical_unit(tokens[0]) is not None:
            # Size words count as units only here, for counted items ("2 large eggs");
            # in "1 cup large shrimp" the unit is already "cup".
            unit, tokens = canonical_unit(tokens[0]), tokens[1:]
        if tokens and tokens[0].lower() == "of":
            tokens = tokens[1:]

    # A size word after a real unit ("1 can large olives") is just a descriptor.
    words = [t for t in tokens if t.lower().strip(".") not in PREP_WORDS]
    if unit not in SIZE_UNITS:
        words = [w for w in words if w.lower() not in SIZE_UNITS]
    food = " ".join(words).strip(" .;:-").lower()

    if quantity is None and "to taste" not in note_parts:
        warnings.append("no amount given")

    return ParsedLine(
        original=original,
        quantity=quantity,
        unit=unit,
        food=food,
        note="; ".join(p for p in note_parts if p),
        package_grams=package_grams,
        warnings=warnings,
    )
