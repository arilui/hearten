"""Tagging rules on foods chosen to catch false positives and misses."""

import pytest

from scripts.tag_rules import tag_food

POULT = {"PF_POULT (oz eq)": 1.0}
SEAFOOD = {"PF_SEAFD_HI (oz eq)": 1.0}

CASES = [
    # description, ingredients, fped, must have, must not have
    ("Pizza, pepperoni", ["Pepperoni, beef and pork", "Wheat flour", "Cheese, mozzarella"], {},
     {"pork", "meat", "wheat", "gluten", "dairy"}, set()),
    ("Kidney beans, cooked", ["Beans, kidney, red, mature seeds"], {},
     set(), {"meat"}),
    ("Crab cake", ["Crab, blue, cooked", "Bread crumbs, dry", "Egg, whole"], {},
     {"crustacean", "wheat", "egg"}, {"meat", "fish"}),
    ("Peanut butter sandwich", ["Peanut butter, smooth", "Bread, white, wheat"], {},
     {"peanut", "wheat"}, {"dairy", "tree_nut"}),
    ("Eggplant parmesan", ["Eggplant, raw", "Cheese, parmesan"], {},
     {"dairy"}, {"egg"}),
    ("Ginger ale", ["Carbonated beverage, ginger ale"], {},
     set(), {"alcohol", "barley", "gluten"}),
    ("Rice cake, plain", ["Rice, brown, puffed"], {},
     set(), {"wheat", "gluten"}),
    ("Tortilla, corn", ["Masa harina, corn"], {},
     set(), {"wheat", "gluten"}),
    ("Buffalo wings", ["Chicken, broilers or fryers, wing"], POULT,
     {"poultry"}, {"meat"}),
    ("Coconut milk", ["Nuts, coconut milk, canned"], {},
     set(), {"dairy", "tree_nut"}),
    ("Butternut squash soup", ["Squash, winter, butternut", "Cream, fluid, heavy"], {},
     {"dairy"}, {"tree_nut"}),
    ("Salad with red wine vinegar dressing", ["Vinegar, red wine", "Oil, olive"], {},
     set(), {"alcohol"}),
    ("Beef stew with red wine", ["Beef, chuck", "Wine, table, red"], {},
     {"beef", "meat", "alcohol"}, set()),
    ("Chicken sausage", ["Chicken sausage"], POULT,
     {"poultry"}, {"pork"}),
    ("Sausage, NFS", ["Sausage, pork and beef"], {},
     {"pork", "meat"}, set()),
    ("Caesar salad", ["Lettuce, cos", "Worcestershire sauce", "Cheese, parmesan"], {},
     {"fish", "dairy"}, set()),
    ("Vanilla cake", ["Wheat flour, white", "Vanilla extract", "Butter, salted", "Egg, whole"], {},
     {"wheat", "alcohol_trace", "dairy", "egg"}, {"alcohol"}),
    ("Hummus", ["Chickpeas", "Tahini"], {},
     {"sesame"}, set()),
    ("Fish, NFS, baked", [], SEAFOOD,
     {"fish"}, set()),
    ("Shrimp scampi", ["Shrimp, cooked", "Butter", "Pasta, cooked"], SEAFOOD,
     {"crustacean", "dairy", "wheat"}, {"fish"}),
    ("Marshmallows", ["Gelatin, dry powder"], {},
     {"gelatin"}, set()),
    ("Doughnut, glazed", ["Wheat flour", "Sugar"], {},
     {"wheat"}, {"tree_nut"}),
    ("Cornish game hen, roasted", ["Cornish game hens"], POULT,
     {"poultry"}, {"meat"}),
    ("Catfish, fried", ["Fish, catfish", "Cornmeal"], SEAFOOD,
     {"fish", "nonkosher_fish"}, {"wheat"}),
    ("Oatmeal", ["Oats"], {},
     {"oats", "gluten"}, {"wheat"}),
    ("Honeydew melon", ["Melons, honeydew"], {},
     set(), {"honey"}),
]


@pytest.mark.parametrize(("description", "ingredients", "fped", "must", "must_not"), CASES,
                         ids=[c[0] for c in CASES])
def test_tags(description, ingredients, fped, must, must_not):
    tags = tag_food(description, ingredients, fped).tags
    assert must <= tags, f"missing {must - tags}; got {sorted(tags)}"
    assert not (must_not & tags), f"wrongly tagged {must_not & tags}; got {sorted(tags)}"


def test_unclear_meat_goes_to_review():
    result = tag_food("Hot dog, NFS", [], {})
    assert "pork" in result.tags  # conservative until a person confirms
    assert "meat species unclear" in result.review_reasons


def test_unclear_seafood_goes_to_review():
    result = tag_food("Seafood stew", [], SEAFOOD)
    assert "fish" in result.tags
    assert "seafood type unclear" in result.review_reasons
