"""
Rules that decide what a food contains.

Tags describe contents ("pork", "dairy", "wheat"), never diets. The rules
engine later turns a user's requirements into tags to exclude: vegetarian
excludes meat, poultry, fish, crustacean, mollusk and gelatin, for example.

Each food is judged on three kinds of evidence:
  1. FPED food-group amounts (e.g. poultry ounce-equivalents > 0)
  2. keywords in the food's own description
  3. keywords in its USDA ingredient list

When a rule can't be sure (a "sausage" of unknown meat, gelatin of unknown
source), it tags conservatively, so a restricted user is never shown something
they avoid, and the food is listed for human review.
"""

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------- vocabulary --

TAGS = {
    "meat": "Red meat, game or organ meat of any animal",
    "beef": "Beef or veal",
    "pork": "Pork, including ham, bacon and lard",
    "poultry": "Chicken, turkey, duck or other birds",
    "fish": "Finfish",
    "crustacean": "Shrimp, crab, lobster, crayfish",
    "mollusk": "Clams, oysters, mussels, scallops, squid, octopus, snails",
    "egg": "Eggs",
    "dairy": "Milk and milk products, including butter, whey and casein",
    "gelatin": "Gelatin (source usually unknown)",
    "honey": "Honey",
    "alcohol": "Wine, beer or spirits, including in cooking",
    "alcohol_trace": "Small amounts from flavor extracts",
    "wheat": "Wheat and wheat varieties",
    "barley": "Barley and malt",
    "rye": "Rye",
    "oats": "Oats (often cross-contact with wheat)",
    "gluten": "Wheat, barley, rye or oats",
    "soy": "Soybeans and soy products",
    "peanut": "Peanuts",
    "tree_nut": "Tree nuts",
    "sesame": "Sesame",
    "nonkosher_fish": "Fish without fins and scales",
    "nonhalal_animal": "Animals that are never halal other than pork",
}

# FPED column -> tags implied when the amount is above zero.
FPED_GROUPS = {
    "PF_MEAT (oz eq)": ["meat"],
    "PF_CUREDMEAT (oz eq)": ["meat"],
    "PF_ORGAN (oz eq)": ["meat"],
    "PF_POULT (oz eq)": ["poultry"],
    "PF_EGGS (oz eq)": ["egg"],
    "PF_SOY (oz eq)": ["soy"],
    "D_TOTAL (cup eq)": ["dairy"],
    "A_DRINKS (no. of drinks)": ["alcohol"],
}


def _words(*terms: str) -> re.Pattern:
    """Whole-word, case-insensitive match for any of the terms (plurals allowed)."""
    body = "|".join(re.escape(t).replace(r"\ ", r"\s+") for t in terms)
    return re.compile(rf"\b(?:{body})(?:e?s)?\b", re.IGNORECASE)


def _any(*patterns: re.Pattern | str) -> re.Pattern:
    """Combine compiled patterns and raw regex strings into one case-insensitive pattern."""
    parts = [p.pattern if isinstance(p, re.Pattern) else p for p in patterns]
    return re.compile("|".join(f"(?:{p})" for p in parts), re.IGNORECASE)


# USDA ingredient names are often inverted ("Beans, kidney"; "Vinegar, red wine";
# "Nuts, coconut milk"), so exclusions cover both word orders.

# Phrases removed before matching, so "peanut butter" isn't dairy and
# "eggplant" isn't egg. Each applies only to the tags listed.
EXCLUSIONS: dict[str, re.Pattern] = {
    "dairy": _words(
        "peanut butter", "almond butter", "cashew butter", "nut butter", "seed butter",
        "sunflower butter", "cocoa butter", "apple butter", "butternut", "butterbur",
        "soy milk", "soymilk", "almond milk", "oat milk", "rice milk", "coconut milk",
        "cashew milk", "coconut cream", "cream of tartar", "non-dairy", "nondairy",
        "cream soda",
        "dairy-free", "milkfish", "butter bean", "butterhead", "milk thistle",
    ),
    "egg": _words("eggplant", "egg-free", "eggless", "egg substitute"),
    "wheat": _words("buckwheat", "wheat-free", "gluten-free"),
    "tree_nut": _any(
        _words("butternut", "nutmeg", "doughnut", "donut", "coconut", "water chestnut",
               "nut-free", "peanut"),
        r"\bnuts?,\s*coconut[\w ]*",
    ),
    "fish": _words("goldfish cracker", "shellfish"),
    "pork": _words("pork-free", "turkey bacon", "turkey ham", "beef bacon",
                   "chicken sausage", "turkey sausage", "beef sausage", "vegetarian sausage",
                   "meatless"),
    "meat": _words("meatless", "vegetarian", "meat substitute", "imitation meat",
                   "crab meat", "crabmeat", "lobster meat", "coconut meat", "nut meat",
                   "kidney bean", "game hen", "buffalo wing", "buffalo sauce",
                   "buffalo chicken", "buffalo-style", "beans, kidney",
                   # USDA describes poultry and fish cuts as "meat only", "light meat"...
                   "meat only", "light meat", "dark meat", "white meat", "meat and skin",
                   "meat, skin"),
    "poultry": _words("duck sauce"),
    "honey": _words("honeydew", "honeycrisp"),
    "alcohol": _any(
        _words("non-alcoholic", "nonalcoholic", "alcohol-free", "root beer", "ginger beer",
               "birch beer", "ginger ale", "wine vinegar"),
        r"\bvinegar,\s*(?:[\w-]+\s+)*?wine\b",
    ),
    "barley": _words("root beer", "ginger beer", "birch beer", "ginger ale"),
    "gelatin": _words("agar", "gelatin-free"),
    "sesame": _words("sesame-free"),
}

KEYWORDS: dict[str, re.Pattern] = {
    "beef": _words(
        "beef", "veal", "steak", "brisket", "hamburger", "cheeseburger", "burger",
        "corned beef", "pastrami", "roast beef", "suet", "oxtail", "beef broth",
    ),
    "pork": _words(
        "pork", "ham", "bacon", "lard", "prosciutto", "pancetta", "chorizo", "pepperoni",
        "salami", "sausage", "bratwurst", "kielbasa", "frankfurter", "hot dog", "bologna",
        "spam", "chitterlings", "pork rind", "cracklings", "luncheon meat", "carnitas",
        "scrapple", "liverwurst", "mortadella", "guanciale",
    ),
    "meat": _words(
        "lamb", "mutton", "goat", "venison", "bison", "buffalo", "elk", "moose",
        "rabbit", "liver", "kidney", "tripe", "tongue", "meatball", "meatloaf", "gyro",
        "jerky", "meat", "game",
    ),
    "poultry": _words(
        "chicken", "turkey", "duck", "goose", "quail", "pheasant", "cornish hen",
        "chicken broth", "giblets",
    ),
    "fish": _words(
        "fish", "salmon", "tuna", "cod", "tilapia", "trout", "sardine", "anchovy",
        "anchovies", "mackerel", "herring", "halibut", "haddock", "pollock", "flounder",
        "sole", "catfish", "bass", "snapper", "grouper", "mahi", "swordfish", "eel",
        "shark", "carp", "perch", "pike", "whitefish", "lox", "caviar", "roe",
        "fish sauce", "worcestershire", "surimi",
    ),
    "crustacean": _words("shrimp", "prawn", "crab", "lobster", "crayfish", "crawfish",
                         "langostino", "krill", "shellfish"),
    "mollusk": _words("clam", "oyster", "mussel", "scallop", "squid", "calamari", "octopus",
                      "snail", "escargot", "abalone", "conch", "whelk", "oyster sauce",
                      "shellfish"),
    "egg": _words("egg", "eggs", "egg white", "egg yolk", "eggnog", "mayonnaise", "meringue",
                  "albumin", "egg noodle", "custard", "hollandaise", "aioli"),
    "dairy": _words(
        "milk", "cheese", "butter", "buttermilk", "cream", "yogurt", "yoghurt", "whey",
        "casein", "caseinate", "ghee", "kefir", "ricotta", "mozzarella", "parmesan",
        "cheddar", "custard", "ice cream", "sour cream", "half and half", "lactose",
        "paneer", "queso", "alfredo",
    ),
    "gelatin": _words("gelatin", "gelatine", "jell-o", "jello", "marshmallow", "gummy",
                      "gummies"),
    "honey": _words("honey"),
    "alcohol": _words(
        "wine", "beer", "ale", "lager", "rum", "vodka", "whiskey", "whisky", "bourbon",
        "gin", "tequila", "brandy", "cognac", "liqueur", "sherry", "sake", "mirin",
        "champagne", "vermouth", "marsala", "cordial", "margarita", "daiquiri",
        "alcoholic beverage",
    ),
    "alcohol_trace": _words("vanilla extract", "almond extract", "lemon extract",
                            "imitation vanilla"),
    "wheat": _words(
        "wheat", "flour", "bread", "breadcrumbs", "bread crumbs", "crouton", "pasta",
        "spaghetti", "macaroni", "noodle", "couscous", "bulgur", "semolina", "durum",
        "farina", "spelt", "seitan", "cracker", "biscuit", "bagel", "tortilla, flour",
        "flour tortilla", "pita", "croissant", "muffin", "pancake", "waffle", "cake",
        "cookie", "pie crust", "pastry", "pretzel", "soy sauce", "teriyaki", "bun",
        "roll", "dumpling", "ravioli", "lasagna", "batter", "breaded",
    ),
    "barley": _words("barley", "malt", "malted", "beer", "ale", "lager"),
    "rye": _words("rye", "pumpernickel"),
    "oats": _words("oat", "oats", "oatmeal", "granola"),
    "soy": _words("soy", "soya", "soybean", "tofu", "tempeh", "edamame", "miso",
                  "soy sauce", "teriyaki"),
    "peanut": _words("peanut", "peanuts", "peanut butter", "groundnut", "satay"),
    "tree_nut": _words(
        "almond", "cashew", "pecan", "walnut", "pistachio", "hazelnut", "filbert",
        "macadamia", "brazil nut", "pine nut", "pignoli", "chestnut", "praline",
        "marzipan", "nougat", "pesto", "gianduja", "nuts", "mixed nuts",
    ),
    "sesame": _words("sesame", "tahini", "hummus", "halvah", "halva", "benne"),
    "nonkosher_fish": _words("catfish", "eel", "shark", "swordfish", "monkfish", "skate",
                             "sturgeon"),
    "nonhalal_animal": _words("frog", "alligator", "turtle", "snake", "crocodile"),
}

# Words that tag conservatively but need a person to confirm. Each trigger is
# (pattern, resolver): it fires only when the pattern matches and nothing in the
# text already settles the question (e.g. "Wheat flour" settles "flour").
SPECIES = _words(
    "beef", "veal", "pork", "ham", "bacon", "chicken", "turkey", "duck", "lamb", "mutton",
    "goat", "venison", "bison", "fish", "salmon", "tuna", "shrimp", "crab", "clam",
    "vegetable", "vegetables", "mushroom", "seafood", "meatless", "vegetarian",
)
GRAINS = _words(
    "wheat", "rice", "corn", "cornmeal", "masa", "oat", "oats", "rye", "barley",
    "buckwheat", "potato", "tapioca", "chickpea", "almond flour", "coconut flour",
)
NAMED_NUTS = _words(
    "almond", "cashew", "pecan", "walnut", "pistachio", "hazelnut", "filbert", "macadamia",
    "brazil nut", "pine nut", "chestnut", "peanut", "coconut",
)

REVIEW_TRIGGERS: dict[str, tuple[re.Pattern, re.Pattern | None]] = {
    "meat species unclear": (
        _words("sausage", "hot dog", "frankfurter", "bologna", "salami", "pepperoni",
               "luncheon meat", "meatball", "meatloaf", "gyro", "jerky"),
        SPECIES,
    ),
    "gelatin source unknown": (_words("gelatin", "gelatine", "marshmallow", "gummy"), None),
    "flour type unclear": (
        _words("flour", "batter", "breaded", "dumpling", "tortilla"),
        GRAINS,
    ),
    "broth or stock source unclear": (
        _words("broth", "stock", "bouillon", "gravy"),
        SPECIES,
    ),
    "nut type unclear": (_words("nuts", "mixed nuts", "nut"), NAMED_NUTS),
    "coconut: not a major allergen in current FDA guidance, check": (_words("coconut"), None),
}

# Gluten-free grain words that cancel a generic "flour"/"bread" wheat match.
GLUTEN_FREE_GRAINS = _words(
    "rice flour", "corn flour", "cornmeal", "almond flour", "coconut flour",
    "potato flour", "tapioca", "masa", "corn tortilla", "tortilla, corn", "rice noodle",
    "rice noodles", "rice cake", "rice cracker", "gluten-free", "chickpea flour", "buckwheat",
)

# Contents that imply others.
IMPLIES = {
    "beef": ["meat"],
    "pork": ["meat"],
    "wheat": ["gluten"],
    "barley": ["gluten"],
    "rye": ["gluten"],
    "oats": ["gluten"],
}


@dataclass
class TagResult:
    tags: set[str] = field(default_factory=set)
    review_reasons: list[str] = field(default_factory=list)


def _match(tag: str, text: str) -> bool:
    exclusion = EXCLUSIONS.get(tag)
    if exclusion is not None:
        text = exclusion.sub(" ", text)
    return bool(KEYWORDS[tag].search(text))


def tag_food(description: str, ingredients: list[str], fped: dict[str, float]) -> TagResult:
    """Decide the content tags for one food."""
    result = TagResult()
    text = " | ".join([description, *ingredients]).lower()

    for column, implied in FPED_GROUPS.items():
        if (fped.get(column) or 0) > 0:
            result.tags.update(implied)

    for tag in KEYWORDS:
        if _match(tag, text):
            result.tags.add(tag)

    # A generic "flour" or "noodle" match is wheat unless every grain named is
    # gluten-free (e.g. "Tortilla, corn", "Rice noodles").
    if "wheat" in result.tags and not re.search(r"\bwheat\b", text):
        remainder = GLUTEN_FREE_GRAINS.sub(" ", text)
        if not _match("wheat", remainder):
            result.tags.discard("wheat")

    # FPED counts seafood in one group; keywords decide fish vs. shellfish.
    seafood = (fped.get("PF_SEAFD_HI (oz eq)") or 0) + (fped.get("PF_SEAFD_LOW (oz eq)") or 0)
    if seafood > 0 and not result.tags & {"fish", "crustacean", "mollusk"}:
        result.tags.add("fish")
        result.review_reasons.append("seafood type unclear")

    # FPED groups peanuts with tree nuts and seeds; keywords decide which.
    nuts = fped.get("PF_NUTSDS (oz eq)") or 0
    if nuts > 0 and not result.tags & {"peanut", "tree_nut", "sesame"}:
        result.review_reasons.append("nut or seed type unclear")

    for tag, implied in IMPLIES.items():
        if tag in result.tags:
            result.tags.update(implied)

    for reason, (pattern, resolver) in REVIEW_TRIGGERS.items():
        if pattern.search(text) and not (resolver and resolver.search(text)):
            result.review_reasons.append(reason)

    return result
