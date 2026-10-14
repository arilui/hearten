import pytest

from app.ingredients.parse import parse_line

CASES = [
    # line, quantity, unit, food
    ("1 ½ cups finely chopped kale, stems removed", 1.5, "cup", "kale"),
    ("2 large eggs", 2, "large", "eggs"),
    ("1 1/2 cups all-purpose flour", 1.5, "cup", "all-purpose flour"),
    ("3/4 tsp salt", 0.75, "tsp", "salt"),
    ("1 T olive oil", 1, "tbsp", "olive oil"),
    ("1 t vanilla extract", 1, "tsp", "vanilla extract"),
    ("2-3 cloves garlic, minced", 2.5, "clove", "garlic"),
    ("1 (15 oz) can black beans, drained and rinsed", 1, "can", "black beans"),
    ("1 lb. ground beef", 1, "lb", "ground beef"),
    ("½ medium onion, diced", 0.5, "medium", "onion"),
    ("1 cup large shrimp, peeled", 1, "cup", "shrimp"),
    ("a pinch of salt", 1, "pinch", "salt"),
    ("200 g spaghetti", 200, "g", "spaghetti"),
    ("8 fl oz milk", 8, "fl oz", "milk"),
    ("1 stick butter, softened", 1, "stick", "butter"),
    ("2 c. sugar", 2, "cup", "sugar"),
    ("10-12 cherry tomatoes", 11, None, "cherry tomatoes"),
    ("4 boneless skinless chicken breasts", 4, None, "boneless skinless chicken breasts"),
]


@pytest.mark.parametrize(("line", "quantity", "unit", "food"), CASES, ids=[c[0] for c in CASES])
def test_parse(line, quantity, unit, food):
    parsed = parse_line(line)
    assert parsed.quantity == pytest.approx(quantity)
    assert parsed.unit == unit
    assert parsed.food == food


def test_package_size_in_parentheses():
    parsed = parse_line("1 (15 oz) can black beans")
    assert parsed.package_grams == pytest.approx(425.24, abs=0.1)


def test_salt_to_taste_has_no_amount_but_no_warning():
    parsed = parse_line("Salt to taste")
    assert parsed.quantity is None
    assert parsed.food == "salt"
    assert "to taste" in parsed.note
    assert parsed.warnings == []


def test_missing_amount_is_warned():
    assert parse_line("olive oil").warnings == ["no amount given"]
