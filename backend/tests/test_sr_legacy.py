import os
import re
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from app.ingredients.match import FoodIndex, query_text
from app.ingredients.parse import parse_line
from scripts import sr_legacy
from scripts.import_data import (
    ADDED_SUGARS_ID,
    add_sr_legacy,
    build_tables,
    load,
    read_fndds,
    read_fped,
    read_input_food,
    read_prices,
    read_sr,
)
from scripts.tag_rules import tag_sr_food

RAW = Path(__file__).parent / "fixtures" / "raw"
EVAL_LINES = Path(__file__).parents[1] / "data" / "eval" / "ingredient_lines.csv"

MILK, KALE, SUGAR, CHICKEN, PEACHES, BABYFOOD = 171265, 168421, 169655, 171077, 169108, 167900


@pytest.fixture(scope="module")
def sr():
    return read_sr(RAW / "sr_legacy")


@pytest.fixture(scope="module")
def tables(sr):
    fndds = read_fndds(RAW / "fndds")
    prices, _ = read_prices(RAW / "ppnap" / "pp_national_average_prices_csv.csv", RAW / "cpi.csv")
    base = build_tables(fndds, read_fped(RAW / "fped.csv"), prices)
    fndds_foods = fndds["food"][["fdc_id", "description"]].merge(
        fndds["survey_fndds_food"][["fdc_id", "food_code"]], on="fdc_id")
    return add_sr_legacy(base, sr, read_input_food(RAW / "fndds"), fndds_foods)


# ------------------------------------------------------------------ reading --

def test_baby_and_restaurant_categories_are_left_out(sr):
    assert BABYFOOD not in set(sr["foods"]["fdc_id"])
    assert MILK in set(sr["foods"]["fdc_id"])


def test_portions_are_described_like_fndds_and_ordered(sr):
    p = sr["portions"]
    assert p[p.fdc_id == KALE]["description"].item() == "1 cup chopped"
    assert p[p.fdc_id == SUGAR]["description"].tolist() == ["1 cup", "1 tsp"]  # seq_num order
    assert p[p.fdc_id == CHICKEN]["description"].tolist() == ["0.5 breast, bone and skin removed"]


def test_usage_counts_link_by_ndb_number(sr):
    usage = sr_legacy.usage_counts(read_input_food(RAW / "fndds"), sr["foods"])
    assert usage == {MILK: 1, KALE: 1}


# ------------------------------------------------------------ added sugars --

@pytest.mark.parametrize(("description", "category", "expected"), [
    ("Sugars, granulated", 19, 99.8),
    ("Honey", 19, 99.8),
    ("Honey roll sausage, beef", 7, None),
    ("Kale, raw", 11, 0.0),
    ("Apples, raw, with skin", 9, 0.0),
    ("Peaches, canned, heavy syrup pack, solids and liquids", 9, None),
    ("Yogurt, fruit, low fat", 1, None),
    ("Milk, whole, 3.25% milkfat, with added vitamin D", 1, 0.0),
    ("Cookies, oatmeal", 18, None),
])
def test_added_sugars_rule(description, category, expected):
    assert sr_legacy.sr_added_sugars(description, category, 99.8) == expected


# ------------------------------------------------------------------- tables --

def test_sr_foods_join_the_food_table_with_source_and_usage(tables):
    food = tables.food.set_index("food_code")
    assert food.loc[MILK, "source"] == "sr_legacy"
    assert food.loc[11111000, "source"] == "fndds"
    assert food.loc[MILK, "recipe_uses"] == 1
    assert food.loc[SUGAR, "recipe_uses"] == 0
    assert food.loc[KALE, "category"] == "Vegetables and Vegetable Products"
    assert BABYFOOD not in food.index


def test_sr_nutrients_are_keyed_by_number_and_new_ones_are_added(tables):
    fn = tables.food_nutrient
    sodium = fn[(fn.food_code == MILK) & (fn.nutrient_id == 307)]["amount_per_100g"]
    assert sodium.item() == 43.0
    names = tables.nutrient.set_index("nutrient_id")["name"]
    assert names.loc[601] == "Cholesterol"
    assert set(fn["nutrient_id"]) <= set(tables.nutrient["nutrient_id"])
    assert not tables.nutrient["nutrient_id"].duplicated().any()


def test_sr_added_sugars_rows(tables):
    fn = tables.food_nutrient
    added = fn[fn.nutrient_id == ADDED_SUGARS_ID].set_index("food_code")["amount_per_100g"]
    assert added.loc[SUGAR] == pytest.approx(99.8)
    assert added.loc[KALE] == 0.0
    assert PEACHES not in added.index  # unknown, so no row rather than a guess


def test_prices_carry_over_from_single_ingredient_fndds_foods(tables):
    price = tables.food_price.set_index("food_code")["amount_minor_per_100g"]
    assert price.loc[MILK] == pytest.approx(price.loc[11111000])
    assert price.loc[KALE] == pytest.approx(price.loc[72118300])
    assert SUGAR not in price.index


def test_single_ingredient_links_need_agreeing_names():
    foods = pd.DataFrame({"fdc_id": [MILK], "description": ["Milk, whole"],
                          "category_id": [1], "ndb_number": [1077]})
    inputs = pd.DataFrame({"fdc_id": [10, 11], "sr_code": [1077, 1077],
                           "gram_weight": [100.0, 100.0]})
    names = pd.DataFrame({"fdc_id": [10, 11], "description": ["Milk, whole", "Cheese, paneer"]})
    links = sr_legacy.single_ingredient_links(inputs, foods, names)
    assert links["fndds_fdc_id"].tolist() == [10]


def test_portion_zero_weight_dropped(tables):
    p = tables.food_portion
    assert "1 quantity not specified" not in set(p[p.food_code == CHICKEN]["description"])


@pytest.mark.skipif(
    os.getenv("ALLOW_DESTRUCTIVE_TESTS") != "1",
    reason="empties the food tables; runs only in CI, never against your real data",
)
def test_load_with_sr_foods(tables, db_engine):
    load(db_engine, tables)
    with db_engine.connect() as conn:
        rows = dict(conn.execute(text(
            "SELECT source, count(*) FROM food GROUP BY source")).all())
        uses = conn.execute(text(
            f"SELECT recipe_uses FROM food WHERE food_code = {MILK}")).scalar()
    assert rows == {"fndds": 3, "sr_legacy": 5}
    assert uses == 1


# ------------------------------------------------------------------ tagging --

@pytest.mark.parametrize(("description", "category", "expected", "unexpected"), [
    ("Chicken, broilers or fryers, thigh, meat only, raw", 5, {"poultry"}, {"meat"}),
    ("Pork, fresh, loin, tenderloin, separable lean only, raw", 10, {"pork", "meat"}, set()),
    ("Beef, round, top round, raw", 13, {"beef", "meat"}, set()),
    ("Crustaceans, shrimp, raw", 15, {"crustacean"}, {"fish"}),
    ("Fish, salmon, Atlantic, wild, raw", 15, {"fish"}, set()),
    ("Dulce de Leche", 1, {"dairy"}, set()),
    ("Egg, whole, raw, fresh", 1, {"egg"}, {"dairy"}),
])
def test_sr_category_tags(description, category, expected, unexpected):
    tags = tag_sr_food(description, category).tags
    assert expected <= tags
    assert not unexpected & tags


# ----------------------------------------------------------------- matching --

def test_usage_prior_breaks_ties_between_variants():
    foods = [(1, "Tomatoes, green, raw"), (2, "Tomatoes, red, ripe, raw, year round average")]
    assert FoodIndex(foods).search("tomatoes")[0].food_code == 2
    assert FoodIndex(foods, usage={1: 0, 2: 70}).search("tomatoes")[0].food_code == 2


def test_branded_and_part_only_foods_rank_lower():
    foods = [(1, "Yogurt, Greek, plain, nonfat (Includes foods for USDA's Food Distribution "
                 "Program)"),
             (2, "Yogurt, Greek, plain, CHOBANI"),
             (3, "Potatoes, raw, skin"), (4, "Potatoes, flesh and skin, raw")]
    index = FoodIndex(foods)
    assert index.search("plain greek yogurt")[0].food_code == 1
    assert index.search("potatoes")[0].food_code == 4


def test_category_heads_and_canned_hint():
    foods = [(1, "Oil, corn, peanut, and olive"), (2, "Oil, olive, salad or cooking"),
             (3, "Beans, black, mature seeds, raw"),
             (4, "Beans, black turtle, mature seeds, canned")]
    index = FoodIndex(foods)
    assert index.search("olive oil")[0].food_code == 2
    assert index.search(query_text(parse_line("1 can (15 oz) black beans")))[0].food_code == 4
    assert index.search("black beans")[0].food_code == 3


def test_eval_set_is_well_formed():
    lines = pd.read_csv(EVAL_LINES)
    assert set(lines["split"]) == {"dev", "test"}
    assert not lines["line"].duplicated().any()
    for pattern in lines["accept"]:
        re.compile(pattern)


# ------------------------------------------------------------ staple prices --

def test_bls_prices_use_the_latest_month_and_skip_stale_series():
    from scripts.import_data import read_bls_prices

    staples = read_bls_prices(RAW / "bls_average_prices.csv",
                              Path(__file__).parent / "fixtures" / "bls_staples.csv")
    price = staples.set_index("food_code")
    # $0.60 per lb -> 60 cents / 453.592 g -> 13.2277 cents per 100 g
    assert price.loc[168894, "amount_minor_per_100g"] == pytest.approx(13.2277, abs=1e-3)
    assert price.loc[168894, "price_period"] == "2026-08"
    # $3.00 per dozen eggs, 600 g -> 50 cents per 100 g
    assert price.loc[MILK, "amount_minor_per_100g"] == pytest.approx(50.0)
    assert KALE not in price.index  # series ended in 1988


def test_staple_prices_replace_carried_over_estimates(tables):
    from scripts.import_data import apply_staple_prices, read_bls_prices

    staples = read_bls_prices(RAW / "bls_average_prices.csv",
                              Path(__file__).parent / "fixtures" / "bls_staples.csv")
    before = tables.food_price.set_index("food_code")["amount_minor_per_100g"]
    assert MILK in before.index and before.loc[MILK] != pytest.approx(50.0)
    updated = apply_staple_prices(tables, staples).food_price
    milk = updated[updated.food_code == MILK]
    assert len(milk) == 1
    assert milk["amount_minor_per_100g"].item() == pytest.approx(50.0)
    assert milk["source"].item().startswith("BLS average price")
