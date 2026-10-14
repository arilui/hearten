"""
Download Hearten's source datasets into data/raw/ and print what's inside each one.

Run from the backend folder, with the virtual environment active:

    pip install -e ".[data]"
    python -m scripts.download_data            # download (skips files already present)
    python -m scripts.download_data --inspect  # print the columns and sample rows

The inspect output is what the import scripts are written against.
"""

import argparse
import sys
import urllib.request
import zipfile
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

SOURCES = {
    # FNDDS 2021-2023 (survey foods) from FoodData Central, released October 2024.
    "fndds.zip": "https://fdc.nal.usda.gov/fdc-datasets/"
    "FoodData_Central_survey_food_csv_2024-10-31.zip",
    # Added sugars per 100 g for each FNDDS food (Food Patterns Equivalents Database).
    "fped_1720.xls": "https://www.ars.usda.gov/ARSUserFiles/80400530/apps/FPED_1720.xls",
    # Purchase to Plate national average prices, all periods.
    "ppnap.zip": "https://www.ers.usda.gov/media/6557/"
    "purchase-to-plate-national-average-prices-for-nhanes-csv-format.zip?v=87915",
    # CPI, food at home, U.S. city average (monthly).
    "cpi_food_at_home.csv": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CUUR0000SAF11",
}

MANUAL_PAGES = {
    "fndds.zip": "https://fdc.nal.usda.gov/download-datasets (FNDDS 2021-2023, CSV)",
    "fped_1720.xls": "https://www.ars.usda.gov/northeast-area/beltsville-md-bhnrc/"
    "beltsville-human-nutrition-research-center/food-surveys-research-group/docs/fped-databases/",
    "ppnap.zip": "https://www.ers.usda.gov/data-products/purchase-to-plate (PP-NAP, CSV)",
    "cpi_food_at_home.csv": "https://fred.stlouisfed.org/series/CUUR0000SAF11 (Download, CSV)",
}


def download() -> bool:
    RAW.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, url in SOURCES.items():
        target = RAW / name
        if target.exists():
            print(f"have      {name}")
            continue
        print(f"download  {name} ...", flush=True)
        try:
            headers = {"User-Agent": "Mozilla/5.0 hearten-data"}
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=300) as response:
                target.write_bytes(response.read())
        except Exception as e:  # report every failure, then keep going
            ok = False
            print(f"  FAILED: {e}")
            print(f"  Download it by hand from {MANUAL_PAGES[name]}")
            print(f"  and save it as {target}")
    for name in ("fndds.zip", "ppnap.zip"):
        path = RAW / name
        if path.exists():
            with zipfile.ZipFile(path) as z:
                z.extractall(RAW / path.stem)
    return ok


def inspect() -> None:
    import pandas as pd

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_colwidth", 40)

    def show(label: str, frame: pd.DataFrame, rows: int) -> None:
        print(f"\n=== {label}: {len(frame):,} rows")
        print("columns:", list(frame.columns))
        print(frame.head(rows).to_string(index=False))

    fndds_files = sorted((RAW / "fndds").rglob("*.csv")) if (RAW / "fndds").exists() else []
    print("FNDDS files:", [f.name for f in fndds_files])
    wanted = {"food.csv", "nutrient.csv", "food_nutrient.csv", "food_portion.csv",
              "survey_fndds_food.csv", "wweia_food_category.csv", "input_food.csv",
              "measure_unit.csv"}
    for f in fndds_files:
        if f.name in wanted:
            show(f"FNDDS {f.name}", pd.read_csv(f, low_memory=False), 3)

    if (RAW / "fped_1720.xls").exists():
        fped = pd.read_excel(RAW / "fped_1720.xls")
        show("FPED", fped, 3)

    ppnap_files = sorted((RAW / "ppnap").rglob("*.csv")) if (RAW / "ppnap").exists() else []
    print("\nPP-NAP files:", [f.name for f in ppnap_files])
    for f in ppnap_files:
        show(f"PP-NAP {f.name}", pd.read_csv(f, low_memory=False, encoding="latin-1"), 3)

    if (RAW / "cpi_food_at_home.csv").exists():
        cpi = pd.read_csv(RAW / "cpi_food_at_home.csv")
        show("CPI", cpi.tail(3), 3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true", help="print columns and sample rows")
    args = parser.parse_args()
    if args.inspect:
        inspect()
    else:
        sys.exit(0 if download() else 1)


if __name__ == "__main__":
    main()
