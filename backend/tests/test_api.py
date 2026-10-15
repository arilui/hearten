"""The /check endpoint, against a small in-memory catalogue (no database needed)."""

import pytest
from fastapi.testclient import TestClient

from app import nutrients as N
from app.catalog import Catalog, Food
from app.ingredients.grams import Portion
from app.main import app, get_catalog

FOODS = {
    1: Food(1, "Salt, table", "sr_legacy", 2164, [Portion("1 tsp", 6.0)],
            {N.SODIUM_MG: 38758.0, N.ADDED_SUGARS_G: 0.0, N.CARBOHYDRATE_G: 0.0}, set(), 1.0),
    2: Food(2, "Chicken, broiler or fryers, breast, skinless, boneless, meat only, raw",
            "sr_legacy", 40, [],
            {N.SODIUM_MG: 45.0, N.ADDED_SUGARS_G: 0.0, N.CARBOHYDRATE_G: 0.0},
            {"poultry"}, 92.6),
    3: Food(3, "Rice, white, long-grain, regular, raw, enriched", "sr_legacy", 20,
            [Portion("1 cup", 185.0)],
            {N.SODIUM_MG: 5.0, N.ADDED_SUGARS_G: 0.0, N.CARBOHYDRATE_G: 80.0}, set(), 39.0),
}


@pytest.fixture
def client():
    app.dependency_overrides[get_catalog] = lambda: Catalog(FOODS)
    yield TestClient(app)
    app.dependency_overrides.clear()


RECIPE = "- 1 lb chicken breast\n1 cup long-grain white rice\n1 tsp salt\n1 tbsp zhoug\n"


def test_check_returns_matches_and_result(client):
    response = client.post("/check", json={
        "recipe": RECIPE, "servings": 4,
        "profile": {"conditions": ["hypertension"], "diets": ["vegetarian"],
                    "budget_minor_per_meal": 300},
    })
    assert response.status_code == 200
    body = response.json()
    lines = {i["line"]: i for i in body["ingredients"]}
    assert lines["1 lb chicken breast"]["food_code"] == 2
    assert lines["1 lb chicken breast"]["grams"] == pytest.approx(453.6)
    assert lines["1 tbsp zhoug"]["food_code"] is None

    result = body["result"]
    sodium = next(c for c in result["nutrients"] if c["key"] == "sodium")
    # (6 g salt x 387.58 + 453.6 g x 0.45 + 185 g x 0.05) / 4 servings
    assert sodium["per_serving"] == pytest.approx((2325.5 + 204.1 + 9.25) / 4, abs=0.5)
    assert sodium["source"]["name"] == "NHLBI DASH eating plan"
    assert result["diet"][0]["status"] == "doesnt_fit"
    assert result["not_counted"] == [{"line": "1 tbsp zhoug",
                                      "reason": "couldn't identify the food"}]
    assert result["fits_plan"] is False
    assert result["budget"]["currency"] == "USD"


def test_price_overrides_arrive_as_json_object_keys(client):
    response = client.post("/check", json={
        "recipe": "1 lb chicken breast", "servings": 1,
        "profile": {"budget_minor_per_meal": 1000,
                    "price_overrides_minor_per_100g": {"2": 200}},
    })
    assert response.json()["result"]["budget"]["cost_minor_per_serving"] == 907


@pytest.mark.parametrize(("payload", "detail"), [
    ({"recipe": "For the sauce:\n\n", "servings": 2}, "No ingredient lines"),
    ({"recipe": "\n".join(["1 tsp salt"] * 61), "servings": 2}, "limit is 60"),
])
def test_bad_recipes_get_a_clear_message(client, payload, detail):
    response = client.post("/check", json=payload)
    assert response.status_code == 422
    assert detail in response.json()["detail"]


def test_invalid_profile_is_rejected(client):
    response = client.post("/check", json={"recipe": "1 tsp salt", "servings": 1,
                                           "profile": {"diets": ["carnivore"]}})
    assert response.status_code == 422
    response = client.post("/check", json={"recipe": "1 tsp salt", "servings": 0})
    assert response.status_code == 422
