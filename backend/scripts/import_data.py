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

Foods whose codes changed between survey cycles simply have no added-sugar or
price row; the importer reports how many.
"""

import io
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

# Nutrients that exist only in FPED get ids far above FoodData Central's own.
ADDED_SUGARS_ID = 900001
ALCOHOLIC_DRINKS_ID = 900002
# FPED measures added sugars in teaspoon equivalents; 1 tsp eq = 4.2 g
# (FPED 2017-2018 Methodology and User Guide).
GRAMS_PER_TSP_ADDED_SUGAR = 4.2

PRICE_CURRENCY = "USD"


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
    nutrient = fndds["nutrient"].rename(columns={"id": "nutrient_id", "unit_name": "unit"})
    nutrient = nutrient[nutrient["nutrient_id"].isin(used)][["nutrient_id", "name", "unit"]]
    nutrient = pd.concat([nutrient, pd.DataFrame([
        {"nutrient_id": ADDED_SUGARS_ID, "name": "Added sugars (FPED)", "unit": "G"},
        {"nutrient_id": ALCOHOLIC_DRINKS_ID, "name": "Alcoholic drinks (FPED)", "unit": "DRINK"},
    ])])

    fp = fndds["food_portion"]
    fp = fp[fp["fdc_id"].isin(fdc_to_code.index) & (fp["gram_weight"] > 0)]
    food_portion = pd.DataFrame({
        "food_code": fp["fdc_id"].map(fdc_to_code).astype(int),
        "description": fp["portion_description"].astype(str),
        "gram_weight": fp["gram_weight"],
    })

    food_price = prices[prices["food_code"].isin(known)]

    return Tables(
        food=food[["food_code", "description", "category"]],
        nutrient=nutrient,
        food_nutrient=food_nutrient,
        food_portion=food_portion,
        food_price=food_price,
    )


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
            _copy(cur, "food", tables.food)
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
    n = len(tables.food)
    fn = tables.food_nutrient
    with_sugar = fn.loc[fn["nutrient_id"] == ADDED_SUGARS_ID, "food_code"]
    priced = tables.food_price["food_code"]
    return "\n".join([
        f"foods:             {n:,}",
        f"nutrient values:   {len(tables.food_nutrient):,} across {len(tables.nutrient)} nutrients",
        f"portion sizes:     {len(tables.food_portion):,}",
        f"with added sugars: {with_sugar.nunique():,} ({with_sugar.nunique() / n:.0%})",
        f"with a price:      {priced.nunique():,} ({priced.nunique() / n:.0%})",
    ])


def main() -> None:
    from app.db import get_engine

    fndds = read_fndds(RAW / "fndds")
    fped = read_fped(RAW / "fped_1720.xls")
    prices, label = read_prices(
        RAW / "ppnap" / "pp_national_average_prices_csv.csv", RAW / "cpi_food_at_home.csv"
    )
    tables = build_tables(fndds, fped, prices)
    print(f"Prices: {label}")
    print(coverage_report(tables))
    print("Loading into the database...", flush=True)
    load(get_engine(), tables)
    print("Done.")


if __name__ == "__main__":
    main()
