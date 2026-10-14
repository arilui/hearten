"""
Dietary requirements as exclusion rules over food content tags.

Tags describe what a food contains (scripts/tag_rules.py); each requirement
names the tags it rules out. Requirements combine by union, so vegetarian plus
an egg allergy gives lacto-vegetarian. The app can rule ingredients out; it
can't certify a dish as safe, halal or kosher, and it says so.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Requirement:
    label: str
    excludes: frozenset[str]
    # Tags that don't rule a food out but need a check ("check certification").
    check: frozenset[str] = field(default_factory=frozenset)
    check_note: str = ""
    cant_know: str = ""


ANIMAL_FLESH = {"meat", "beef", "pork", "poultry", "fish", "crustacean", "mollusk"}

DIETS: dict[str, Requirement] = {
    "vegetarian": Requirement(
        "Vegetarian", frozenset(ANIMAL_FLESH | {"gelatin"}),
        cant_know="Some cheeses use animal rennet."),
    "vegan": Requirement(
        "Vegan", frozenset(ANIMAL_FLESH | {"gelatin", "dairy", "egg", "honey"}),
        cant_know="Branded products can contain animal-derived additives."),
    "pescatarian": Requirement(
        "Pescatarian", frozenset({"meat", "beef", "pork", "poultry", "gelatin"}),
        cant_know="Some cheeses use animal rennet."),
    "no_beef": Requirement(
        "No beef", frozenset({"beef", "gelatin"}),
        cant_know="Branded products can contain beef-derived additives."),
    "halal": Requirement(
        "Halal", frozenset({"pork", "nonhalal_animal", "gelatin", "alcohol"}),
        check=frozenset({"meat", "beef", "poultry", "alcohol_trace"}),
        check_note="Check certification: whether meat was slaughtered to halal standards, "
                   "and whether flavor extracts contain alcohol.",
        cant_know="Whether meat was slaughtered to halal standards."),
    "kosher": Requirement(
        "Kosher", frozenset({"pork", "nonhalal_animal", "crustacean", "mollusk",
                             "nonkosher_fish", "gelatin"}),
        check=frozenset({"meat", "beef", "poultry", "alcohol", "alcohol_trace"}),
        check_note="Check certification for meat, poultry, wine and processed foods.",
        cant_know="Whether meat, wine and processed foods are certified."),
    "gluten_free": Requirement(
        "Gluten-free", frozenset({"gluten"}),
        cant_know="Cross-contact in processing; oats count unless labeled gluten-free."),
    "dairy_free": Requirement(
        "Dairy-free", frozenset({"dairy"}),
        cant_know="Branded products can contain milk derivatives."),
    "alcohol_free": Requirement(
        "Alcohol-free", frozenset({"alcohol", "alcohol_trace"}),
        cant_know="Branded flavorings can contain alcohol."),
}

# The 9 major allergens (FDA) -> content tags. A wheat allergy excludes wheat
# only; celiac disease (gluten-free) also excludes barley, rye and oats.
ALLERGENS: dict[str, Requirement] = {
    name: Requirement(label, frozenset({tag}), cant_know="Cross-contact; recipes and brands vary.")
    for name, label, tag in [
        ("milk", "Milk allergy", "dairy"),
        ("egg", "Egg allergy", "egg"),
        ("fish", "Fish allergy", "fish"),
        ("crustacean", "Crustacean shellfish allergy", "crustacean"),
        ("tree_nut", "Tree nut allergy", "tree_nut"),
        ("peanut", "Peanut allergy", "peanut"),
        ("wheat", "Wheat allergy", "wheat"),
        ("soy", "Soy allergy", "soy"),
        ("sesame", "Sesame allergy", "sesame"),
    ]
}

# Kosher law forbids combining meat or poultry with dairy in one dish.
KOSHER_MEAT = {"meat", "beef", "poultry"}
