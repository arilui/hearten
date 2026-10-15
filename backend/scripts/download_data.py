"""
Download Hearten's source datasets into data/raw/ and print what's inside each one.

Run from the backend folder, with the virtual environment active:

    pip install -e ".[data]"
    python -m scripts.download_data            # download (skips files already present)
    python -m scripts.download_data --inspect  # print the columns and sample rows

The inspect output is what the import scripts are written against.
"""

import argparse
import csv
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
BLS_STAPLES = Path(__file__).resolve().parents[1] / "data" / "bls_staples.csv"


def bls_series_ids() -> list[str]:
    """The BLS average-price series named in data/bls_staples.csv, in order."""
    with BLS_STAPLES.open(encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return list(dict.fromkeys(row["series_id"] for row in rows))

SOURCES = {
    # FNDDS 2021-2023 (survey foods) from FoodData Central, released October 2024.
    "fndds.zip": "https://fdc.nal.usda.gov/fdc-datasets/"
    "FoodData_Central_survey_food_csv_2024-10-31.zip",
    # SR Legacy: the basic-ingredient database FNDDS recipes are built from (flour,
    # salt, spices, raw meats, dry grains). Final release, April 2018.
    "sr_legacy.zip": "https://fdc.nal.usda.gov/fdc-datasets/"
    "FoodData_Central_sr_legacy_food_csv_2018-04.zip",
    # Added sugars per 100 g for each FNDDS food (Food Patterns Equivalents Database).
    "fped_1720.xls": "https://www.ars.usda.gov/ARSUserFiles/80400530/apps/FPED_1720.xls",
    # Purchase to Plate national average prices, all periods.
    "ppnap.zip": "https://www.ers.usda.gov/media/6557/"
    "purchase-to-plate-national-average-prices-for-nhanes-csv-format.zip?v=87915",
    # CPI, food at home, U.S. city average (monthly).
    "cpi_food_at_home.csv": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CUUR0000SAF11",
}

# BLS average retail prices for staples PP-NAP doesn't cover (flour, uncooked rice,
# dry pasta, eggs...), monthly, from the BLS public API (no key needed for up to 25
# series per request). Saved as one CSV, one column per series. Delete the file and
# re-run to refresh prices.
BLS_FILE = "bls_average_prices.csv"
BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

MANUAL_PAGES = {
    "fndds.zip": "https://fdc.nal.usda.gov/download-datasets (FNDDS 2021-2023, CSV)",
    "sr_legacy.zip": "https://fdc.nal.usda.gov/download-datasets (SR Legacy, April 2018, CSV)",
    "fped_1720.xls": "https://www.ars.usda.gov/northeast-area/beltsville-md-bhnrc/"
    "beltsville-human-nutrition-research-center/food-surveys-research-group/docs/fped-databases/",
    "ppnap.zip": "https://www.ers.usda.gov/data-products/purchase-to-plate (PP-NAP, CSV)",
    "cpi_food_at_home.csv": "https://fred.stlouisfed.org/series/CUUR0000SAF11 (Download, CSV)",
    "bls_average_prices.csv": "https://data.bls.gov/cgi-bin/srgate (paste the series ids "
    "from backend/data/bls_staples.csv), saved as observation_date plus one column per series",
}


def fetch(url: str, timeout: int = 120, attempts: int = 3) -> bytes:
    """GET with a few retries, since public data sites time out now and then."""
    headers = {"User-Agent": "Mozilla/5.0 hearten-data"}
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(3 * attempt)
    raise AssertionError("unreachable")


def bls_to_columns(payload: dict) -> dict[str, dict[str, str]]:
    """BLS API JSON -> {series: {"YYYY-MM-01": value}} for monthly observations."""
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError("; ".join(payload.get("message", [])) or payload.get("status"))
    columns = {}
    for series in payload["Results"]["series"]:
        values = {}
        for obs in series["data"]:
            period, value = obs["period"], obs["value"]
            if period.startswith("M") and period != "M13" and value not in ("", "-"):
                values[f"{obs['year']}-{period[1:]}-01"] = value
        if values:
            columns[series["seriesID"]] = values
    return columns


def download_bls_prices(target: Path) -> bool:
    """Fetch the staple series from the BLS API and save them as one CSV keyed by date."""
    wanted = bls_series_ids()
    body = json.dumps({"seriesid": wanted}).encode("utf-8")
    try:
        request = urllib.request.Request(BLS_API, data=body, headers={
            "Content-Type": "application/json", "User-Agent": "hearten-data"})
        with urllib.request.urlopen(request, timeout=120) as response:
            columns = bls_to_columns(json.load(response))
    except Exception as e:
        print(f"  FAILED: {e}")
        print(f"  Re-run later, or download by hand from {MANUAL_PAGES[BLS_FILE]}")
        return False
    dates = sorted({d for values in columns.values() for d in values})
    with target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["observation_date", *columns])
        for d in dates:
            writer.writerow([d, *(columns[s].get(d, "") for s in columns)])
    missing = [s for s in wanted if s not in columns]
    print(f"  got {len(columns)} of {len(wanted)} series"
          + (f" (no data: {', '.join(missing)})" if missing else ""))
    return not missing


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
            target.write_bytes(fetch(url, timeout=300))
        except Exception as e:  # report every failure, then keep going
            ok = False
            print(f"  FAILED: {e}")
            print(f"  Download it by hand from {MANUAL_PAGES[name]}")
            print(f"  and save it as {target}")
    target = RAW / BLS_FILE
    if target.exists():
        print(f"have      {BLS_FILE}")
    else:
        print(f"download  {BLS_FILE} (BLS API) ...", flush=True)
        ok = download_bls_prices(target) and ok
    for name in ("fndds.zip", "sr_legacy.zip", "ppnap.zip"):
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

    sr_files = sorted((RAW / "sr_legacy").rglob("*.csv")) if (RAW / "sr_legacy").exists() else []
    print("\nSR Legacy files:", [f.name for f in sr_files])
    for f in sr_files:
        if f.name in {"food.csv", "sr_legacy_food.csv", "food_portion.csv", "nutrient.csv"}:
            show(f"SR Legacy {f.name}", pd.read_csv(f, low_memory=False), 3)
        elif f.name == "food_nutrient.csv":
            show("SR Legacy food_nutrient.csv (first rows only)", pd.read_csv(f, nrows=5), 3)

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
