"""Units found in recipes, and how they relate to each other."""

# Canonical unit -> spellings seen in recipes. Matching is case-insensitive
# except for "T" (tablespoon) vs "t" (teaspoon), handled in the parser.
UNIT_ALIASES: dict[str, list[str]] = {
    "cup": ["cup", "cups", "c"],
    "tbsp": ["tablespoon", "tablespoons", "tbsp", "tbsps", "tbs", "tbl", "tblsp"],
    "tsp": ["teaspoon", "teaspoons", "tsp", "tsps"],
    "fl oz": ["fluid ounce", "fluid ounces", "fl oz", "fl. oz", "fl. oz."],
    "oz": ["ounce", "ounces", "oz", "oz."],
    "lb": ["pound", "pounds", "lb", "lbs", "lb.", "lbs."],
    "g": ["gram", "grams", "g", "gr"],
    "kg": ["kilogram", "kilograms", "kg"],
    "ml": ["milliliter", "milliliters", "millilitre", "millilitres", "ml"],
    "l": ["liter", "liters", "litre", "litres", "l"],
    "pint": ["pint", "pints", "pt"],
    "quart": ["quart", "quarts", "qt"],
    "pinch": ["pinch", "pinches"],
    "dash": ["dash", "dashes"],
    "stick": ["stick", "sticks"],
    "can": ["can", "cans"],
    "clove": ["clove", "cloves"],
    "slice": ["slice", "slices"],
    "piece": ["piece", "pieces"],
    "sprig": ["sprig", "sprigs"],
    "bunch": ["bunch", "bunches"],
    "head": ["head", "heads"],
    "stalk": ["stalk", "stalks", "rib", "ribs"],
    "leaf": ["leaf", "leaves"],
    "large": ["large", "lg"],
    "medium": ["medium", "med"],
    "small": ["small", "sm"],
}

# Mass units in grams.
MASS_G = {"g": 1.0, "kg": 1000.0, "oz": 28.3495, "lb": 453.592}

# Volume units in teaspoons, so any volume converts to any other.
VOLUME_TSP = {
    "tsp": 1.0,
    "tbsp": 3.0,
    "fl oz": 6.0,
    "cup": 48.0,
    "pint": 96.0,
    "quart": 192.0,
    "ml": 1 / 4.92892,
    "l": 1000 / 4.92892,
    "pinch": 1 / 16,
    "dash": 1 / 8,
}

# Units that count things; their weight comes from the food's own portions.
COUNT_UNITS = {"clove", "slice", "piece", "sprig", "bunch", "head", "stalk", "leaf",
               "large", "medium", "small", "can", "stick"}

# A butter or margarine stick is a standard 1/2 cup = 113 g.
STICK_GRAMS = 113.0


def canonical_unit(word: str) -> str | None:
    w = word.strip().lower().rstrip(".")
    for unit, aliases in UNIT_ALIASES.items():
        if w in aliases or w + "." in aliases:
            return unit
    return None
