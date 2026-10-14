"""
Load the downloaded USDA datasets into Postgres.

Run from the backend folder after `python -m scripts.download_data`:

    python -m scripts.import_data

It replaces the contents of the food tables in one transaction, so it is safe
to re-run: either everything loads or nothing changes.

Sources and how they join
-------------------------
- FNDDS 2021-2023: foods, nutrients per 100 g, household portion weights.
  Foods are keyed by FNDDS food code (survey_fndds_food.csv maps fdc_id to it).
- FPED 2017-March 2020: added sugars and alcoholic drinks per 100 g, by food code.
- PP-NAP: national average price per 100 edible g, by food code. The latest
  period (2017/2018) is used and adjusted to today's dollars with the CPI.
- CPI (BLS CUUR0000SAF11, food at home): monthly index for that adjustment.
- SR Legacy (April 2018): plain recipe ingredients, keyed by fdc_id. Added
  sugars come from a rule (scripts/sr_legacy.py) and prices are carried over
  from FNDDS foods made of essentially that one ingredient; see sr_legacy.py.

Foods whose codes changed between survey cycles simply have no added-sugar or
price row; the importer reports how many.
"""

import io
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from scripts import sr_legacy

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

# Nutrients that exist only in FPED get ids far above FoodData Central's own.
ADDED_SUGARS_ID = 900001
ALCOHOLIC_DRINKS_ID = 900002
# FPED measures added sugars in teaspoon equivalents; 1 tsp eq = 4.2 g
# (FPED 2017-2018 Methodology and User Guide).
GRAMS_PER_TSP_ADDED_SUGAR = 4.2

PRICE_CURRENCY = "USD"
TOTAL_SUGARS_NBR = 269


@dataclass
class Tables:
    food: pd.DataFrame
    nutrient: pd.DataFrame
    food_nutrient: pd.DataFrame
    food_portion: pd.DataFrame
    food_price: pd.DataFrame


# ----------------------------------------------------------------- readers ----

def read_fndds(folder: Path) -> dict[str, pd.DataFrame]:
    def read(name: str) -> pd.DataFrame:
        matches = list(folder.rglob(name))
        if not matches:
            raise FileNotFoundError(f"{name} not found under {folder}")
        return pd.read_csv(matches[0], low_memory=False)

    return {name: read(f"{name}.csv") for name in (
        "food", "nutrient", "food_nutrient", "food_portion",
        "survey_fndds_food", "wweia_food_category",
    )}


def read_fped(path: Path) -> pd.DataFrame:
    """Added sugars (g) and alcoholic drinks per 100 g, by food code."""
    raw = pd.read_csv(path) if path.suffix == ".csv" else pd.read_excel(path)
    return pd.DataFrame({
        "food_code": raw["FOODCODE"].astype(int),
        "added_sugars_g": raw["ADD_SUGARS (tsp eq)"] * GRAMS_PER_TSP_ADDED_SUGAR,
        "alcoholic_drinks": raw["A_DRINKS (no. of drinks)"],
    })


def read_prices(ppnap_path: Path, cpi_path: Path) -> tuple[pd.DataFrame, str]:
    """Latest-period prices per 100 g, inflated to the latest CPI month, in cents."""
    prices = pd.read_csv(ppnap_path, encoding="latin-1")
    prices = prices.dropna(subset=["food_code", "price_100gm"])
    period = sorted(prices["year"].dropna().unique())[-1]          # e.g. "2017/2018"
    latest = prices[prices["year"] == period]
    latest = latest.groupby(latest["food_code"].astype(int))["price_100gm"].mean()

    cpi = pd.read_csv(cpi_path, parse_dates=["observation_date"])
    cpi = cpi.rename(columns={cpi.columns[1]: "index"}).dropna()
    years = [int(y) for y in str(period).split("/")]
    base = cpi[cpi["observation_date"].dt.year.isin(years)]["index"].mean()
    now = cpi.sort_values("observation_date").iloc[-1]
    factor = now["index"] / base

    label = f"{period} @ CPI {now['observation_date']:%Y-%m}"
    frame = pd.DataFrame({
        "food_code": latest.index,
        "currency": PRICE_CURRENCY,
        "amount_minor_per_100g": (latest.values * 100 * factor).round(4),
        "source": "USDA ERS PP-NAP, CPI-adjusted (BLS CUUR0000SAF11)",
        "price_period": label,
    })
    return frame, label


def read_sr(folder: Path) -> dict[str, pd.DataFrame]:
    if not folder.exists():
        raise FileNotFoundError(f"{folder} not found. Run: python -m scripts.download_data")
    foods = sr_legacy.read_foods(folder)
    food_nutrient = pd.read_csv(next(folder.rglob("food_nutrient.csv")), low_memory=False,
                                usecols=["fdc_id", "nutrient_id", "amount"])
    return {
        "foods": foods,
        "portions": sr_legacy.read_portions(folder, set(foods["fdc_id"])),
        "food_nutrient": food_nutrient[food_nutrient["fdc_id"].isin(foods["fdc_id"])],
        "nutrient": pd.read_csv(next(folder.rglob("nutrient.csv"))),
    }


def read_input_food(fndds_folder: Path) -> pd.DataFrame:
    return pd.read_csv(next(fndds_folder.rglob("input_food.csv")), low_memory=False)


# ------------------------------------------------------------- transforms ----

def build_tables(fndds: dict[str, pd.DataFrame], fped: pd.DataFrame,
                 prices: pd.DataFrame) -> Tables:
    codes = fndds["survey_fndds_food"][["fdc_id", "food_code", "wweia_category_number"]]
    categories = fndds["wweia_food_category"].rename(columns={
        "wweia_food_category": "wweia_category_number",
        "wweia_food_category_description": "category",
    })
    food = (
        fndds["food"][["fdc_id", "description"]]
        .merge(codes, on="fdc_id")
        .merge(categories, on="wweia_category_number", how="left")
    )
    fdc_to_code = food.set_index("fdc_id")["food_code"]
    known = set(food["food_code"])

    fn = fndds["food_nutrient"][["fdc_id", "nutrient_id", "amount"]].dropna()
    fn = fn[fn["fdc_id"].isin(fdc_to_code.index)]
    food_nutrient = pd.DataFrame({
        "food_code": fn["fdc_id"].map(fdc_to_code).astype(int),
        "nutrient_id": fn["nutrient_id"].astype(int),
        "amount_per_100g": fn["amount"],
    })

    fped = fped[fped["food_code"].isin(known)]
    extra = pd.concat([
        pd.DataFrame({"food_code": fped["food_code"], "nutrient_id": ADDED_SUGARS_ID,
                      "amount_per_100g": fped["added_sugars_g"].round(4)}),
        pd.DataFrame({"food_code": fped["food_code"], "nutrient_id": ALCOHOLIC_DRINKS_ID,
                      "amount_per_100g": fped["alcoholic_drinks"]}),
    ])
    food_nutrient = (
        pd.concat([food_nutrient, extra])
        .drop_duplicates(subset=["food_code", "nutrient_id"])
    )

    used = set(food_nutrient["nutrient_id"])
    nutrient = _nutrient_table(fndds["nutrient"], set(fn["nutrient_id"].astype(int)))
    nutrient = nutrient[nutrient["nutrient_id"].isin(used)]
    nutrient = pd.concat([nutrient, pd.DataFrame([
        {"nutrient_id": ADDED_SUGARS_ID, "name": "Added sugars (FPED)", "unit": "G"},
        {"nutrient_id": ALCOHOLIC_DRINKS_ID, "name": "Alcoholic drinks (FPED)", "unit": "DRINK"},
    ])])
    missing = set(food_nutrient["nutrient_id"]) - set(nutrient["nutrient_id"])
    if missing:
        raise ValueError(f"Food data references unknown nutrients: {sorted(missing)[:10]}")

    fp = fndds["food_portion"]
    fp = fp[fp["fdc_id"].isin(fdc_to_code.index) & (fp["gram_weight"] > 0)]
    food_portion = pd.DataFrame({
        "food_code": fp["fdc_id"].map(fdc_to_code).astype(int),
        "description": fp["portion_description"].astype(str),
        "gram_weight": fp["gram_weight"],
    })

    food_price = prices[prices["food_code"].isin(known)]

    food = food.assign(source="fndds", recipe_uses=0)
    return Tables(
        food=food[["food_code", "description", "category", "source", "recipe_uses"]],
        nutrient=nutrient,
        food_nutrient=food_nutrient,
        food_portion=food_portion,
        food_price=food_price,
    )


def add_sr_legacy(base: Tables, sr: dict[str, pd.DataFrame], input_food: pd.DataFrame,
                  fndds_foods: pd.DataFrame) -> Tables:
    """
    Add SR Legacy ingredients to the FNDDS tables.

    fndds_foods: FNDDS fdc_id, food_code, description, used to carry prices
    over from single-ingredient FNDDS foods.
    """
    foods = sr["foods"]
    usage = sr_legacy.usage_counts(input_food, foods)
    food = pd.DataFrame({
        "food_code": foods["fdc_id"],
        "description": foods["description"],
        "category": foods["category_id"].map(sr_legacy.CATEGORY_NAMES),
        "source": "sr_legacy",
        "recipe_uses": foods["fdc_id"].map(usage).fillna(0).astype(int),
    })

    # SR food_nutrient refers to nutrients by id; the table is keyed by nutrient
    # number like FNDDS. Nutrients without a number are left out.
    sr_nutrient = sr["nutrient"].dropna(subset=["nutrient_nbr"])
    id_to_nbr = sr_nutrient.set_index(sr_nutrient["id"].astype(int))["nutrient_nbr"].astype(int)
    fn = sr["food_nutrient"].dropna(subset=["amount"])
    fn = fn[fn["nutrient_id"].isin(id_to_nbr.index)]
    food_nutrient = pd.DataFrame({
        "food_code": fn["fdc_id"].astype(int),
        "nutrient_id": fn["nutrient_id"].map(id_to_nbr).astype(int),
        "amount_per_100g": fn["amount"],
    }).drop_duplicates(subset=["food_code", "nutrient_id"])

    sugars = food_nutrient[food_nutrient["nutrient_id"] == TOTAL_SUGARS_NBR]
    sugars = sugars.set_index("food_code")["amount_per_100g"]
    added = []
    for row in foods.itertuples(index=False):
        total = sugars.get(row.fdc_id)
        value = sr_legacy.sr_added_sugars(row.description, row.category_id,
                                          None if pd.isna(total) else float(total))
        if value is not None:
            added.append({"food_code": row.fdc_id, "nutrient_id": ADDED_SUGARS_ID,
                          "amount_per_100g": round(value, 4)})
    food_nutrient = pd.concat([food_nutrient, pd.DataFrame(added)], ignore_index=True)

    known = set(base.nutrient["nutrient_id"])
    new_ids = set(food_nutrient["nutrient_id"]) - known
    extra_nutrients = pd.DataFrame({
        "nutrient_id": sr_nutrient["nutrient_nbr"].astype(int),
        "name": sr_nutrient["name"],
        "unit": sr_nutrient["unit_name"],
    }).drop_duplicates("nutrient_id")
    extra_nutrients = extra_nutrients[extra_nutrients["nutrient_id"].isin(new_ids)]

    portions = sr["portions"]
    food_portion = pd.DataFrame({
        "food_code": portions["fdc_id"],
        "description": portions["description"],
        "gram_weight": portions["gram_weight"],
    })

    food_price = _sr_prices(foods, input_food, fndds_foods, base.food_price)

    return Tables(
        food=pd.concat([base.food, food], ignore_index=True),
        nutrient=pd.concat([base.nutrient, extra_nutrients], ignore_index=True),
        food_nutrient=pd.concat([base.food_nutrient, food_nutrient], ignore_index=True),
        food_portion=pd.concat([base.food_portion, food_portion], ignore_index=True),
        food_price=pd.concat([base.food_price, food_price], ignore_index=True),
    )


def _sr_prices(foods: pd.DataFrame, input_food: pd.DataFrame, fndds_foods: pd.DataFrame,
               fndds_prices: pd.DataFrame) -> pd.DataFrame:
    """Median price of the single-ingredient FNDDS foods made from each SR food."""
    links = sr_legacy.single_ingredient_links(input_food, foods,
                                              fndds_foods[["fdc_id", "description"]])
    links = links.merge(fndds_foods[["fdc_id", "food_code"]]
                        .rename(columns={"fdc_id": "fndds_fdc_id"}), on="fndds_fdc_id")
    priced = links.merge(fndds_prices, on="food_code")
    if priced.empty:
        return fndds_prices.iloc[0:0]
    grouped = priced.groupby(["sr_fdc_id", "currency"])
    out = grouped.agg(amount_minor_per_100g=("amount_minor_per_100g", "median"),
                      n=("food_code", "nunique"), price_period=("price_period", "first"))
    out = out.reset_index()
    return pd.DataFrame({
        "food_code": out["sr_fdc_id"],
        "currency": out["currency"],
        "amount_minor_per_100g": out["amount_minor_per_100g"].round(4),
        "source": "USDA ERS PP-NAP via " + out["n"].astype(str)
                  + " single-ingredient FNDDS food(s), CPI-adjusted",
        "price_period": out["price_period"],
    })


def _nutrient_table(raw: pd.DataFrame, referenced: set[int]) -> pd.DataFrame:
    """
    FNDDS food_nutrient rows refer to nutrients by their legacy nutrient number
    (e.g. 307 = sodium), not by nutrient.csv's id column (e.g. 1093). Key the
    table by whichever of the two the food data actually uses.
    """
    by_number = raw.dropna(subset=["nutrient_nbr"]).copy()
    by_number["key"] = by_number["nutrient_nbr"].astype(int)
    by_id = raw.assign(key=raw["id"].astype(int))
    hits_number = len(referenced & set(by_number["key"]))
    hits_id = len(referenced & set(by_id["key"]))
    chosen = by_number if hits_number >= hits_id else by_id
    chosen = chosen.drop_duplicates(subset=["key"])
    return pd.DataFrame({
        "nutrient_id": chosen["key"],
        "name": chosen["name"],
        "unit": chosen["unit_name"],
    })


# -------------------------------------------------------------------- load ----

def _copy(cursor, table: str, frame: pd.DataFrame) -> None:
    columns = ", ".join(frame.columns)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, header=False)
    buffer.seek(0)
    with cursor.copy(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv)") as copy:
        while chunk := buffer.read(1 << 20):
            copy.write(chunk)


def load(engine, tables: Tables) -> None:
    """Replace all food data in one transaction (bulk COPY for speed)."""
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(
                "TRUNCATE food_tag, food_price, food_portion, food_nutrient, nutrient, food"
            )
            _copy(cur, "food", tables.food)  # includes source and recipe_uses
            _copy(cur, "nutrient", tables.nutrient)
            _copy(cur, "food_nutrient", tables.food_nutrient)
            _copy(cur, "food_portion", tables.food_portion)
            _copy(cur, "food_price", tables.food_price)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def coverage_report(tables: Tables) -> str:
    fn = tables.food_nutrient
    with_sugar = set(fn.loc[fn["nutrient_id"] == ADDED_SUGARS_ID, "food_code"])
    priced = set(tables.food_price["food_code"])
    lines = [
        f"nutrient values:   {len(tables.food_nutrient):,} across {len(tables.nutrient)} nutrients",
        f"portion sizes:     {len(tables.food_portion):,}",
    ]
    for source, group in tables.food.groupby("source", sort=False):
        codes = set(group["food_code"])
        n = len(codes)
        sugar, price = len(codes & with_sugar), len(codes & priced)
        lines += [
            f"{source} foods: {n:,}",
            f"  with added sugars: {sugar:,} ({sugar / n:.0%})",
            f"  with a price:      {price:,} ({price / n:.0%})",
        ]
    return "\n".join(lines)


def main() -> None:
    from app.db import get_engine

    fndds = read_fndds(RAW / "fndds")
    fped = read_fped(RAW / "fped_1720.xls")
    prices, label = read_prices(
        RAW / "ppnap" / "pp_national_average_prices_csv.csv", RAW / "cpi_food_at_home.csv"
    )
    tables = build_tables(fndds, fped, prices)
    tables = add_sr_legacy(tables, read_sr(RAW / "sr_legacy"), read_input_food(RAW / "fndds"),
                           fndds["food"][["fdc_id", "description"]]
                           .merge(fndds["survey_fndds_food"][["fdc_id", "food_code"]],
                                  on="fdc_id"))
    print(f"Prices: {label}")
    print(coverage_report(tables))
    print("Loading into the database...", flush=True)
    load(get_engine(), tables)
    print("Done.")


if __name__ == "__main__":
    main()
