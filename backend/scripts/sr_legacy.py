"""
USDA SR Legacy (April 2018): the ingredient catalogue for recipe matching.

FNDDS describes foods as eaten in the US survey ("Chicken breast, baked") and
lacks many plain recipe ingredients: flour, salt, baking soda, spices, dry
pasta, raw chicken, broth. SR Legacy has them. Recipes are matched against SR
first, with FNDDS as the fallback for prepared foods.

SR foods are keyed by their FoodData Central id (fdc_id, 6 digits), which can't
collide with 8-digit FNDDS food codes, so both live in the same food table.

FNDDS's input_food.csv lists the SR ingredients in each survey recipe (by SR's
NDB number). That link gives two things:
  - usage: how many survey recipes use each SR food, a prior for "the everyday
    version" when variants tie (red vs. green tomatoes);
  - prices: an FNDDS food made of essentially one SR ingredient lends its
    PP-NAP price to that ingredient.
"""

import re
from pathlib import Path

import pandas as pd

from app.ingredients import match

# SR food categories left out of the ingredient catalogue: baby foods, fast
# foods, meals and entrees, American Indian/Alaska Native foods, restaurant foods.
EXCLUDED_CATEGORIES = {3, 21, 22, 24, 25}

CATEGORY_NAMES = {
    1: "Dairy and Egg Products", 2: "Spices and Herbs", 3: "Baby Foods", 4: "Fats and Oils",
    5: "Poultry Products", 6: "Soups, Sauces, and Gravies", 7: "Sausages and Luncheon Meats",
    8: "Breakfast Cereals", 9: "Fruits and Fruit Juices", 10: "Pork Products",
    11: "Vegetables and Vegetable Products", 12: "Nut and Seed Products",
    13: "Beef Products", 14: "Beverages", 15: "Finfish and Shellfish Products",
    16: "Legumes and Legume Products", 17: "Lamb, Veal, and Game Products",
    18: "Baked Products", 19: "Sweets", 20: "Cereal Grains and Pasta", 21: "Fast Foods",
    22: "Meals, Entrees, and Side Dishes", 23: "Snacks",
    24: "American Indian/Alaska Native Foods", 25: "Restaurant Foods",
}

# An FNDDS food lends its price to an SR ingredient only when that ingredient
# makes up at least this share of the recipe's weight (water excluded).
SINGLE_INGREDIENT_SHARE = 0.9
WATER_NDB = {14411, 14429, 14555}


def _find(folder: Path, name: str) -> Path:
    matches = sorted(folder.rglob(name))
    if not matches:
        raise FileNotFoundError(f"{name} not found under {folder}")
    return matches[0]


def read_foods(folder: Path) -> pd.DataFrame:
    """fdc_id, description, category_id, ndb_number for catalogue foods."""
    food = pd.read_csv(_find(folder, "food.csv"))
    sr = pd.read_csv(_find(folder, "sr_legacy_food.csv"))
    food = food[food["data_type"] == "sr_legacy_food"].merge(sr, on="fdc_id")
    food = food[~food["food_category_id"].isin(EXCLUDED_CATEGORIES)]
    return pd.DataFrame({
        "fdc_id": food["fdc_id"].astype(int),
        "description": food["description"],
        "category_id": food["food_category_id"].astype(int),
        "ndb_number": food["NDB_number"].astype(int),
    }).reset_index(drop=True)


def read_portions(folder: Path, fdc_ids: set[int]) -> pd.DataFrame:
    """fdc_id, description ("1 cup, chopped"), gram_weight."""
    fp = pd.read_csv(_find(folder, "food_portion.csv"))
    fp = fp[fp["fdc_id"].isin(fdc_ids) & (fp["gram_weight"] > 0)]
    fp = fp.sort_values(["fdc_id", "seq_num"])  # USDA lists the usual measure first
    units = pd.read_csv(_find(folder, "measure_unit.csv")).set_index("id")["name"]
    unit = fp["measure_unit_id"].map(units).fillna("undetermined")

    def describe(amount, unit_name, modifier, portion_description) -> str:
        words = [f"{amount:g}"]
        if unit_name != "undetermined":
            words.append(unit_name)
        for extra in (modifier, portion_description):
            if isinstance(extra, str) and extra.strip():
                words.append(extra.strip())
        return " ".join(words)

    return pd.DataFrame({
        "fdc_id": fp["fdc_id"].astype(int),
        "description": [describe(a, u, m, d) for a, u, m, d in zip(
            fp["amount"].fillna(1), unit, fp["modifier"], fp["portion_description"],
            strict=True)],
        "gram_weight": fp["gram_weight"],
    }).reset_index(drop=True)


def usage_counts(input_food: pd.DataFrame, foods: pd.DataFrame) -> dict[int, int]:
    """SR fdc_id -> number of FNDDS survey recipes that use it."""
    rows = input_food.dropna(subset=["sr_code"])
    per_recipe = rows.drop_duplicates(["fdc_id", "sr_code"])
    counts = per_recipe["sr_code"].astype(int).value_counts()
    ndb_to_fdc = foods.set_index("ndb_number")["fdc_id"]
    return {int(ndb_to_fdc[ndb]): int(n) for ndb, n in counts.items() if ndb in ndb_to_fdc.index}


def single_ingredient_links(input_food: pd.DataFrame, foods: pd.DataFrame,
                            fndds_names: pd.DataFrame) -> pd.DataFrame:
    """
    (fndds_fdc_id, sr_fdc_id) pairs where the FNDDS food is essentially that one
    SR ingredient, so its price can stand in for the ingredient's:
      - the ingredient is >= 90% of the recipe's weight, water aside;
      - the names agree: the FNDDS name's first part shares a word with the SR
        food's head ("Carrots, cooked" ~ "Carrots, raw"; not "Cheese, paneer" ~
        "Milk, whole"), and it isn't a dish or product ("Lemon-butter sauce");
      - raw FNDDS versions are used when there are any, since cooking changes
        weight and so price per 100 g.
    fndds_names: fdc_id, description for FNDDS foods.
    """
    rows = input_food.dropna(subset=["sr_code", "gram_weight"]).copy()
    rows["sr_code"] = rows["sr_code"].astype(int)
    rows = rows[~rows["sr_code"].isin(WATER_NDB)]
    totals = rows.groupby("fdc_id")["gram_weight"].sum()
    top = rows.sort_values("gram_weight").groupby("fdc_id").tail(1)
    top = top[top["gram_weight"] >= SINGLE_INGREDIENT_SHARE * top["fdc_id"].map(totals)]
    ndb_to_fdc = foods.set_index("ndb_number")["fdc_id"]
    top = top[top["sr_code"].isin(ndb_to_fdc.index)]
    links = pd.DataFrame({
        "fndds_fdc_id": top["fdc_id"].astype(int),
        "sr_fdc_id": top["sr_code"].map(ndb_to_fdc).astype(int),
    })

    sr_names = foods.set_index("fdc_id")["description"]
    names = fndds_names.set_index("fdc_id")["description"]
    links = links[links["fndds_fdc_id"].isin(names.index)]

    def agrees(fndds_id: int, sr_id: int) -> bool:
        fndds_desc, sr_desc = names[fndds_id], sr_names[sr_id]
        fndds_head = set(match.tokens(fndds_desc.split(",")[0]))
        sr_head, sr_category = match._head_and_category(sr_desc)
        sr_words = set(match.tokens(match.normalize(sr_desc)))
        dish = (set(match.tokens(fndds_desc)) & match.DISH_WORDS) - sr_words
        return bool(fndds_head & (set(sr_head) | sr_category)) and not dish

    links = links[[agrees(f, s) for f, s in zip(links["fndds_fdc_id"], links["sr_fdc_id"],
                                                 strict=True)]]
    raw = links["fndds_fdc_id"].map(names).str.contains(r"\braw\b", case=False)
    has_raw = raw.groupby(links["sr_fdc_id"]).transform("any")
    return links[raw | ~has_raw].reset_index(drop=True)


# ------------------------------------------------------------ added sugars ----
#
# SR Legacy reports total sugars but not added sugars. Recipe ingredients are
# mostly easy cases, so a rule fills the gap and anything unclear is left
# unknown rather than guessed:
#   - sweeteners (sugar, honey, syrups, molasses): all of their sugar is added,
#     as FDA counts honey and syrups used in a recipe as added sugars;
#   - plain foods from categories with no added sugar (produce, meat, fish,
#     grains, legumes, nuts, spices, oils, plain dairy): 0 g;
#   - everything else, or any name suggesting sweetening: unknown (no value).

SWEETENER_HEADS = {"sugar", "sugars", "honey", "syrup", "syrups", "molasses", "sweetener",
                   "sweeteners"}
NO_ADDED_SUGAR_CATEGORIES = {1, 2, 4, 5, 9, 10, 11, 12, 13, 15, 16, 17, 20}
MAYBE_SWEETENED = re.compile(
    r"sweeten|syrup|candied|glaze|honey|sugar|frost|jam\b|jelly|preserves|maple|chocolate"
    r"|flavor|dessert|ice cream|frozen yogurt|pudding|custard|eggnog|milk shake|fruit"
    r"|vanilla|caramel|toffee|teriyaki|barbecue|bbq|ketchup|catsup|relish|pickle"
    r"|salad dressing|mayonnaise|margarine|spread|cocktail|baked beans|beans, baked"
    r"|breaded|batter|dulce|condensed|dried, sweet|cranberr|coated|cereal|granola"
    r"|seasoning mix|dessert topping|whipped topping|dressing|sauce",
    re.IGNORECASE,
)
# Fruits name themselves ("Apples, raw"), so "fruit" only signals sweetening in
# non-fruit categories (e.g. "Yogurt, fruit").
FRUIT_CATEGORY = 9


def sr_added_sugars(description: str, category_id: int, total_sugars: float | None) -> float | None:
    """Added sugars in g per 100 g, or None when it can't be known from SR data."""
    if description.split(",")[0].strip().lower() in SWEETENER_HEADS:
        return total_sugars
    if category_id not in NO_ADDED_SUGAR_CATEGORIES:
        return None
    text = description
    if category_id == FRUIT_CATEGORY:
        text = re.sub(r"\bfruits?\b", " ", text, flags=re.IGNORECASE)
    if MAYBE_SWEETENED.search(text):
        return None
    return 0.0
