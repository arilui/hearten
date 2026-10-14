import pytest

from app.ingredients.grams import Portion, read_portion, to_grams
from app.ingredients.match import FoodIndex
from app.ingredients.parse import parse_line

FOODS = [
    (1, "Kale, raw"),
    (2, "Kale, cooked, from fresh, fat added"),
    (3, "Kale soup"),
    (4, "Egg, whole, raw"),
    (5, "Egg salad sandwich"),
    (6, "Flour, white, all purpose"),
    (7, "Olive oil"),
    (8, "Onions, raw"),
    (9, "Green onions, raw"),
    (10, "Beans, black, canned, drained"),
    (11, "Salt, table"),
    (12, "Baby food, carrots"),
    (13, "Carrots, raw"),
    (14, "Chicken breast, roasted, skin not eaten"),
]


@pytest.fixture(scope="module")
def index():
    return FoodIndex(FOODS)


@pytest.mark.parametrize(("text", "expected"), [
    ("kale", "Kale, raw"),
    ("cooked kale", "Kale, cooked, from fresh, fat added"),
    ("eggs", "Egg, whole, raw"),
    ("all-purpose flour", "Flour, white, all purpose"),
    ("extra virgin olive oil", "Olive oil"),
    ("onion", "Onions, raw"),
    ("scallions", "Green onions, raw"),
    ("black beans", "Beans, black, canned, drained"),
    ("kosher salt", "Salt, table"),
    ("carrots", "Carrots, raw"),
])
def test_best_match(index, text, expected):
    assert index.search(text)[0].description == expected


def test_dishes_rank_below_ingredients(index):
    names = [c.description for c in index.search("kale")]
    assert names.index("Kale, raw") < names.index("Kale soup")


def test_read_portion():
    p = read_portion(Portion("1 cup, chopped", 67.0))
    assert (p.amount, p.unit, p.modifier, p.grams) == (1.0, "cup", "chopped", 67.0)
    p = read_portion(Portion("1 large", 50.0))
    assert (p.unit, p.grams) == ("large", 50.0)


KALE = [Portion("1 cup, chopped", 67.0), Portion("1 cup, whole leaves", 21.0),
        Portion("1 leaf", 35.0)]
EGG = [Portion("1 large", 50.0), Portion("1 medium", 44.0), Portion("1 cup", 243.0)]


@pytest.mark.parametrize(("line", "portions", "grams"), [
    ("2 cups chopped kale", KALE, 134.0),
    ("1 cup kale leaves", KALE, 21.0),
    ("1 tbsp chopped kale", KALE, 67.0 / 16),
    ("2 large eggs", EGG, 100.0),
    ("3 eggs", EGG, 132.0),            # no size given: medium
    ("1 lb kale", KALE, 453.592),
    ("1 (15 oz) can black beans", [], 425.24),
    ("1 stick butter", [], 113.0),
])
def test_to_grams(line, portions, grams):
    assert to_grams(parse_line(line), portions).grams == pytest.approx(grams, abs=0.05)


def test_volume_without_portions_estimates_and_warns():
    result = to_grams(parse_line("1 cup mystery liquid"), [])
    assert result.grams == pytest.approx(236.6, abs=0.1)
    assert result.warnings


def test_no_amount():
    assert to_grams(parse_line("salt to taste"), []).grams is None
