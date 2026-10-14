import os
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from scripts.import_data import (
    ADDED_SUGARS_ID,
    ALCOHOLIC_DRINKS_ID,
    build_tables,
    load,
    read_fndds,
    read_fped,
    read_prices,
)

RAW = Path(__file__).parent / "fixtures" / "raw"


@pytest.fixture(scope="module")
def tables():
    prices, _ = read_prices(RAW / "ppnap" / "pp_national_average_prices_csv.csv", RAW / "cpi.csv")
    return build_tables(read_fndds(RAW / "fndds"), read_fped(RAW / "fped.csv"), prices)


def test_foods_are_keyed_by_food_code_with_category(tables):
    food = tables.food.set_index("food_code")
    assert sorted(food.index) == [11111000, 72118300, 93401010]
    assert food.loc[72118300, "category"] == "Other vegetables"


def test_nutrients_from_unknown_foods_are_dropped(tables):
    assert set(tables.food_nutrient["food_code"]) <= set(tables.food["food_code"])


def test_added_sugars_convert_teaspoons_to_grams_and_skip_old_codes(tables):
    fn = tables.food_nutrient
    wine_drinks = fn[(fn.food_code == 93401010) & (fn.nutrient_id == ALCOHOLIC_DRINKS_ID)]
    assert wine_drinks["amount_per_100g"].item() == pytest.approx(0.68)
    assert 55555555 not in set(fn["food_code"])
    assert ADDED_SUGARS_ID in set(tables.nutrient["nutrient_id"])


def test_only_used_nutrients_are_kept(tables):
    assert 999 not in set(tables.nutrient["nutrient_id"])


def test_nutrients_are_keyed_by_number_as_the_food_data_uses(tables):
    # Every nutrient referenced by a food must exist, or the foreign key load fails.
    assert set(tables.food_nutrient["nutrient_id"]) <= set(tables.nutrient["nutrient_id"])
    names = tables.nutrient.set_index("nutrient_id")["name"]
    assert names.loc[307] == "Sodium, Na"


def test_zero_gram_portions_are_dropped(tables):
    assert "Quantity not specified" not in set(tables.food_portion["description"])
    assert len(tables.food_portion) == 2


def test_prices_use_latest_period_and_cpi_adjustment(tables):
    price = tables.food_price.set_index("food_code")
    # 2017/2018 base CPI = mean(240, 250) = 245; latest = 300.
    # Milk: $0.10 per 100 g = 10 cents x 300/245.
    assert price.loc[11111000, "amount_minor_per_100g"] == pytest.approx(10 * 300 / 245, abs=1e-3)
    assert price.loc[11111000, "price_period"] == "2017/2018 @ CPI 2026-08"
    assert 93401010 not in price.index  # no price row for wine


@pytest.mark.skipif(
    os.getenv("ALLOW_DESTRUCTIVE_TESTS") != "1",
    reason="empties the food tables; runs only in CI, never against your real data",
)
def test_load_writes_all_tables(tables, db_engine):
    load(db_engine, tables)
    with db_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM food")).scalar()
        sodium = conn.execute(text(
            "SELECT amount_per_100g FROM food_nutrient WHERE food_code = 72118300 "
            "AND nutrient_id = 307"
        )).scalar()
    assert count == 3
    assert sodium == Decimal("53.0000")
    load(db_engine, tables)  # re-running replaces rather than duplicates
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM food")).scalar() == 3
