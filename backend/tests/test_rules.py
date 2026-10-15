import pytest
from pydantic import ValidationError

from app import nutrients as N
from app.rules.engine import Ingredient, check_budget, check_diet, check_recipe
from app.rules.profile import Profile


def ing(line, grams, *, code=1, tags=(), price=None, **per_100g):
    keys = {"sodium": N.SODIUM_MG, "added": N.ADDED_SUGARS_G, "carbs": N.CARBOHYDRATE_G,
            "fiber": N.FIBER_G, "kcal": N.ENERGY_KCAL, "potassium": N.POTASSIUM_MG,
            "alcohol": N.ALCOHOL_G}
    return Ingredient(line=line, food_words=line, food_code=code, description=line,
                      grams=grams, nutrients_per_100g={keys[k]: v for k, v in per_100g.items()},
                      tags=frozenset(tags), price_minor_per_100g=price)


def by_key(result, key):
    return next(c for c in result.nutrients if c.key == key)


HT = Profile(conditions={"hypertension"})
T2D = Profile(conditions={"type2_diabetes"})


# ------------------------------------------------------------------ sodium --

def test_sodium_within_meal_share_fits():
    # 2,300 mg / 3 meals = 767 mg per meal. 2 servings of 1,200 mg total = 600 each.
    r = check_recipe([ing("salt", 1, sodium=120000)], 2, HT)
    sodium = by_key(r, "sodium")
    assert sodium.status == "fits"
    assert sodium.per_serving == pytest.approx(600)
    assert sodium.meal_share == pytest.approx(766.67, abs=0.01)
    assert "fits your plan" in sodium.message


def test_sodium_over_share_is_flagged_with_its_share_of_the_day():
    r = check_recipe([ing("soy sauce", 20, sodium=5750)], 1, HT)   # 1,150 mg
    sodium = by_key(r, "sodium")
    assert sodium.status == "over"
    assert "half your day" in sodium.message
    assert sodium.contributors[0].line == "soy sauce"
    assert r.fits_plan is False


def test_strict_and_custom_sodium_limits():
    food = [ing("broth", 100, sodium=600)]  # 600 mg
    assert by_key(check_recipe(food, 1, HT), "sodium").status == "fits"
    strict = Profile(conditions={"hypertension"}, sodium="strict")  # 500 mg per meal
    assert by_key(check_recipe(food, 1, strict), "sodium").status == "over"
    custom = Profile(conditions={"hypertension"}, sodium="custom", sodium_custom_mg=2000)
    check = by_key(check_recipe(food, 1, custom), "sodium")
    assert check.daily_value == 2000
    assert check.source.name == "Your care team's recommendation"


def test_custom_sodium_needs_a_number():
    with pytest.raises(ValidationError):
        Profile(sodium="custom")


def test_snack_gets_a_fraction_of_a_meal():
    snack = Profile(conditions={"hypertension"}, snack_fraction=0.25)  # 192 mg
    r = check_recipe([ing("pretzels", 20, sodium=1300)], 1, snack)     # 260 mg
    assert by_key(r, "sodium").status == "over"


def test_missing_data_is_incomplete_not_zero():
    food = [ing("salt", 0.5, sodium=38758), ing("mystery sauce", 30, kcal=50)]
    sodium = by_key(check_recipe(food, 1, HT), "sodium")
    assert sodium.status == "incomplete"
    assert sodium.missing_data == ["mystery sauce"]
    assert sodium.message.startswith("At least")


def test_known_part_already_over_is_over_even_with_missing_data():
    food = [ing("salt", 3, sodium=38758), ing("mystery sauce", 30, kcal=50)]
    assert by_key(check_recipe(food, 1, HT), "sodium").status == "over"


def test_no_condition_shows_nutrients_without_flags():
    r = check_recipe([ing("soy sauce", 20, sodium=5750)], 1, Profile())
    assert by_key(r, "sodium").status == "info"


# --------------------------------------------------------------- diabetes --

def test_added_sugars_flag_at_50_g_a_day_and_custom():
    food = [ing("sugar", 30, added=100)]  # 30 g; meal share 16.7 g
    assert by_key(check_recipe(food, 1, T2D), "added_sugars").status == "over"
    loose = Profile(conditions={"type2_diabetes"}, added_sugars_custom_g=100)
    assert by_key(check_recipe(food, 1, loose), "added_sugars").status == "fits"
    # Hypertension alone shows added sugars but doesn't flag them.
    assert by_key(check_recipe(food, 1, HT), "added_sugars").status == "info"


def test_carbs_shown_as_carb_servings_and_flagged_only_against_a_target():
    food = [ing("rice", 150, carbs=40)]  # 60 g carbs = 4 carb servings
    carbs = by_key(check_recipe(food, 1, T2D), "carbohydrate")
    assert carbs.status == "info"
    assert "4.0 carb servings" in carbs.message
    target = Profile(conditions={"type2_diabetes"}, carb_target_g_per_meal=45)
    assert by_key(check_recipe(food, 1, target), "carbohydrate").status == "over"


def test_fiber_ratio_per_1000_kcal():
    beans = [ing("beans", 100, fiber=7, kcal=130)]   # 54 g per 1,000 kcal
    assert by_key(check_recipe(beans, 1, T2D), "fiber").status == "meets_goal"
    bread = [ing("white bread", 100, fiber=2, kcal=270)]  # 7.4 g per 1,000 kcal
    fiber = by_key(check_recipe(bread, 1, T2D), "fiber")
    assert fiber.status == "below_goal"
    assert "below the goal" in fiber.message


# ------------------------------------------------------- potassium, alcohol --

def test_potassium_is_progress_with_caution_never_a_failure():
    r = check_recipe([ing("potato", 200, potassium=425)], 1, HT)
    k = by_key(r, "potassium")
    assert k.status == "progress"
    assert k.daily_value == 2600  # sex not given: the lower goal
    assert any("kidney" in n for n in k.notes)
    male = Profile(conditions={"hypertension"}, sex="male")
    assert by_key(check_recipe([ing("potato", 200, potassium=425)], 1, male),
                  "potassium").daily_value == 3400


def test_alcohol_in_cooking_counts_with_notes():
    wine = [ing("1/2 cup wine", 118, alcohol=10.6)]   # 12.5 g = 0.9 drinks
    insulin = Profile(conditions={"type2_diabetes"}, takes_insulin=True)
    alcohol = by_key(check_recipe(wine, 4, insulin), "alcohol")
    assert alcohol.per_serving == pytest.approx(12.5 / 14 / 4, abs=0.01)
    assert alcohol.status == "fits"
    assert any("low blood sugar" in n for n in alcohol.notes)
    assert by_key(check_recipe(wine, 1, HT), "alcohol").status == "over"


# ------------------------------------------------------------------ budget --

def test_budget_per_serving_and_most_expensive():
    food = [ing("salmon", 450, code=1, price=300), ing("rice", 200, code=2, price=20)]
    # (1,350 + 40) / 4 servings = 347.5 cents
    profile = Profile(budget_minor_per_meal=300)
    budget = check_budget(food, 4, profile)
    assert budget.cost_minor_per_serving == 348
    assert budget.status == "over"
    assert budget.most_expensive[0].line == "salmon"
    assert check_budget(food, 4, Profile(budget_minor_per_meal=400)).status == "fits"


def test_price_overrides_and_missing_prices():
    food = [ing("salmon", 450, code=1, price=300), ing("saffron", 1, code=2)]
    profile = Profile(budget_minor_per_meal=400, price_overrides_minor_per_100g={1: 200})
    budget = check_budget(food, 4, profile)
    assert budget.cost_minor_per_serving == 225
    assert budget.status == "incomplete"
    assert budget.missing_prices == ["saffron"]


# -------------------------------------------------------------------- diet --

CHICKEN = ing("chicken breast", 200, code=1, tags={"poultry"})
BUTTER = ing("butter", 14, code=2, tags={"dairy"})
SHRIMP = ing("shrimp", 200, code=3, tags={"crustacean"})
BACON = ing("bacon", 30, code=4, tags={"pork", "meat"})
WINE = ing("white wine", 118, code=5, tags={"alcohol"})
VANILLA = ing("vanilla extract", 4, code=6, tags={"alcohol_trace"})
RICE = ing("rice", 100, code=7)


def diet_status(food, **profile):
    return {d.requirement: d.status for d in check_diet(food, Profile(**profile))}


def test_vegetarian_vegan_pescatarian():
    assert diet_status([CHICKEN, RICE], diets={"vegetarian"}) == {"Vegetarian": "doesnt_fit"}
    assert diet_status([BUTTER, RICE], diets={"vegetarian"}) == {"Vegetarian": "fits"}
    assert diet_status([BUTTER], diets={"vegan"}) == {"Vegan": "doesnt_fit"}
    assert diet_status([SHRIMP], diets={"pescatarian"}) == {"Pescatarian": "fits"}


def test_halal_excludes_pork_and_alcohol_and_asks_to_check_meat():
    assert diet_status([BACON], diets={"halal"})["Halal"] == "doesnt_fit"
    assert diet_status([WINE], diets={"halal"})["Halal"] == "doesnt_fit"
    assert diet_status([CHICKEN], diets={"halal"})["Halal"] == "check"
    assert diet_status([CHICKEN], diets={"halal"}, buys_certified=True)["Halal"] == "fits"
    assert diet_status([VANILLA], diets={"halal"})["Halal"] == "check"


def test_kosher_shellfish_and_meat_with_dairy():
    assert diet_status([SHRIMP], diets={"kosher"})["Kosher"] == "doesnt_fit"
    checks = check_diet([CHICKEN, BUTTER], Profile(diets={"kosher"}, buys_certified=True))
    assert checks[0].status == "doesnt_fit"
    assert "meat or poultry with dairy" in checks[0].conflicts[0].reason


def test_allergens_and_label_reminder():
    r = check_recipe([SHRIMP, RICE], 1, Profile(allergens={"crustacean"}))
    assert r.diet[0].requirement == "Crustacean shellfish allergy"
    assert r.diet[0].status == "doesnt_fit"
    assert any("product labels" in n for n in r.notes)


def test_wheat_allergy_vs_gluten_free():
    barley = ing("barley", 100, code=8, tags={"barley", "gluten"})
    assert diet_status([barley], allergens={"wheat"})["Wheat allergy"] == "fits"
    assert diet_status([barley], diets={"gluten_free"})["Gluten-free"] == "doesnt_fit"


def test_custom_exclusion_matches_words_and_plurals():
    food = [ing("1/4 cup chopped cilantro", 4, code=9), RICE]
    assert diet_status(food, custom_exclusions=["cilantro"]) == {"No cilantro": "doesnt_fit"}
    assert diet_status(food, custom_exclusions=["mushroom"]) == {"No mushroom": "fits"}


def test_unmatched_lines_make_diet_incomplete_and_are_reported():
    mystery = Ingredient("1 tbsp zhoug", "zhoug", None, None, None)
    r = check_recipe([RICE, mystery], 1, Profile(diets={"vegan"}))
    assert r.diet[0].status == "incomplete"
    assert r.not_counted[0].line == "1 tbsp zhoug"
    assert r.fits_plan is None


# ----------------------------------------------------------------- overall --

def test_everything_fits():
    food = [ing("rice", 100, code=1, sodium=1, added=0, carbs=28, fiber=0.4, kcal=130,
                potassium=35, alcohol=0, price=20)]
    profile = Profile(conditions={"hypertension", "type2_diabetes"}, diets={"vegan"},
                      budget_minor_per_meal=300)
    r = check_recipe(food, 1, profile)
    assert {c.key: c.status for c in r.nutrients} == {
        "sodium": "fits", "added_sugars": "fits", "carbohydrate": "info",
        "fiber": "below_goal", "potassium": "progress"}  # no alcohol, so no alcohol line
    assert r.fits_plan is True  # goals below target are shown, never failures
    assert r.summary == "This recipe fits your plan."


def test_servings_must_be_positive():
    with pytest.raises(ValueError):
        check_recipe([RICE], 0, Profile())


def test_alcohol_line_only_when_the_recipe_has_alcohol():
    keys = {c.key for c in check_recipe([ing("rice", 100, alcohol=0)], 1, HT).nutrients}
    assert "alcohol" not in keys
    keys = {c.key for c in check_recipe([ing("wine", 100, alcohol=10)], 1, HT).nutrients}
    assert "alcohol" in keys


def test_certification_notes_are_specific_to_each_line():
    checks = check_diet([CHICKEN, VANILLA], Profile(diets={"halal"}))[0]
    reasons = {c.line: c.reason for c in checks.to_check}
    assert reasons["chicken breast"] == "Check that the meat is certified halal."
    assert "alcohol" in reasons["vanilla extract"]
