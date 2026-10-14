import os
from pathlib import Path

import pandas as pd
import pytest

from app.catalog import Catalog, recipe_lines
from app.rules.engine import check_recipe
from app.rules.profile import Profile
from scripts.import_data import (
    add_sr_legacy,
    build_tables,
    load,
    read_fndds,
    read_fped,
    read_input_food,
    read_prices,
    read_sr,
)
from scripts.tag_foods import compute_tags, read_foods, read_ingredients, write_tags

RAW = Path(__file__).parent / "fixtures" / "raw"


def test_recipe_lines_skip_blanks_bullets_and_headings():
    text = "For the sauce:\n- 2 tbsp soy sauce\n\n• 1 cup chopped kale\n  ▢ 1 tsp sugar  \n"
    assert recipe_lines(text) == ["2 tbsp soy sauce", "1 cup chopped kale", "1 tsp sugar"]


@pytest.fixture(scope="module")
def catalog(db_engine):
    if os.getenv("ALLOW_DESTRUCTIVE_TESTS") != "1":
        pytest.skip("empties the food tables; runs only in CI, never against your real data")
    fndds = read_fndds(RAW / "fndds")
    prices, _ = read_prices(RAW / "ppnap" / "pp_national_average_prices_csv.csv", RAW / "cpi.csv")
    fndds_foods = fndds["food"][["fdc_id", "description"]].merge(
        fndds["survey_fndds_food"][["fdc_id", "food_code"]], on="fdc_id")
    tables = add_sr_legacy(build_tables(fndds, read_fped(RAW / "fped.csv"), prices),
                           read_sr(RAW / "sr_legacy"), read_input_food(RAW / "fndds"),
                           fndds_foods)
    load(db_engine, tables)
    foods = read_foods(RAW / "fndds", RAW / "sr_legacy")
    no_overrides = pd.DataFrame(columns=["food_code", "tag", "action", "note"])
    tags, _ = compute_tags(foods, read_ingredients(RAW / "fndds", foods), {}, no_overrides)
    write_tags(db_engine, tags)
    return Catalog.load(db_engine)


def test_catalog_loads_foods_with_data(catalog):
    kale = catalog.foods[168421]
    assert kale.source == "sr_legacy"
    assert kale.nutrients[307] == 53.0
    assert kale.price_minor_per_100g is not None
    assert "poultry" in catalog.foods[171077].tags


def test_resolve_prefers_the_sr_ingredient_and_converts_grams(catalog):
    ing = catalog.resolve("2 cups chopped kale")
    assert ing.food_code == 168421          # SR "Kale, raw", not the FNDDS food
    assert ing.grams == pytest.approx(42.0)  # SR portion "1 cup chopped" = 21 g
    assert catalog.resolve("1 tbsp zhoug").food_code is None


def test_end_to_end_check(catalog):
    lines = ["2 cups chopped kale", "1 cup whole milk", "1 tsp sugar", "1 tbsp zhoug"]
    ingredients = [catalog.resolve(line) for line in lines]
    result = check_recipe(ingredients, 2, Profile(conditions={"hypertension"},
                                                  diets={"vegan"}))
    sodium = next(c for c in result.nutrients if c.key == "sodium")
    assert sodium.per_serving > 0
    assert result.diet[0].status == "doesnt_fit"   # milk isn't vegan
    assert [n.line for n in result.not_counted] == ["1 tbsp zhoug"]
