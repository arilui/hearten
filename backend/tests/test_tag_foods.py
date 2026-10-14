import os
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from scripts.import_data import build_tables, load, read_fndds, read_fped, read_prices
from scripts.tag_foods import (
    compute_tags,
    read_foods,
    read_fped_groups,
    read_ingredients,
    write_tags,
)

RAW = Path(__file__).parent / "fixtures" / "raw"
NO_OVERRIDES = pd.DataFrame(columns=["food_code", "tag", "action", "note"])


@pytest.fixture(scope="module")
def inputs():
    foods = read_foods(RAW / "fndds")
    return foods, read_ingredients(RAW / "fndds", foods), read_fped_groups(RAW / "fped.csv")


def tags_of(tags: pd.DataFrame, code: int) -> set[str]:
    return set(tags.loc[tags["food_code"] == code, "tag"])


def test_nested_ingredients_are_included(inputs):
    foods, ingredients, _ = inputs
    kale_fdc = int(foods.loc[foods["food_code"] == 72118300, "fdc_id"].item())
    # Kale dish includes FNDDS food 1 (whole milk) as an ingredient.
    assert any("Milk" in i for i in ingredients[kale_fdc])


def test_rules_tag_from_ingredients_and_fped(inputs):
    tags, _ = compute_tags(*inputs, NO_OVERRIDES)
    assert "dairy" in tags_of(tags, 11111000)
    assert "dairy" in tags_of(tags, 72118300)  # via nested milk ingredient
    assert "alcohol" in tags_of(tags, 93401010)
    assert set(tags["set_by"]) == {"rule"}


def test_overrides_add_remove_and_confirm(inputs):
    overrides = pd.DataFrame([
        {"food_code": 72118300, "tag": "dairy", "action": "remove", "note": "test"},
        {"food_code": 72118300, "tag": "sesame", "action": "add", "note": "test"},
        {"food_code": 93401010, "tag": "alcohol", "action": "add", "note": "confirm"},
    ])
    tags, _ = compute_tags(*inputs, overrides)
    assert tags_of(tags, 72118300) == {"sesame"}
    assert tags_of(tags, 11111000) == {"dairy"}  # other foods untouched
    confirmed = tags[(tags.food_code == 93401010) & (tags.tag == "alcohol")]
    assert confirmed["set_by"].item() == "review"


@pytest.mark.skipif(
    os.getenv("ALLOW_DESTRUCTIVE_TESTS") != "1",
    reason="replaces the food tables; runs only in CI, never against your real data",
)
def test_write_tags(inputs, db_engine):
    prices, _ = read_prices(RAW / "ppnap" / "pp_national_average_prices_csv.csv", RAW / "cpi.csv")
    load(db_engine, build_tables(read_fndds(RAW / "fndds"), read_fped(RAW / "fped.csv"), prices))
    tags, _ = compute_tags(*inputs, NO_OVERRIDES)
    write_tags(db_engine, tags)
    write_tags(db_engine, tags)  # re-running replaces rather than duplicates
    with db_engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM food_tag")).scalar()
    assert n == len(tags) > 0
